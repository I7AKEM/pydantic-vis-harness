"""Local CSV files and a single DuckDB database. All IDs are generated here."""

import csv
import hashlib
import io
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

import duckdb

from vis_agent.models import DataBrief, DatasetSummary, UploadedDataset
from vis_agent.profiler.models import DatasetProfile


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class DatasetNotFound(ValueError):
    """The ID is well formed but no upload has it."""


class DatasetStore:
    def __init__(self, directory: Path, max_upload_bytes: int = 20 * 1024 * 1024, database: Path | None = None):
        self.directory = directory.resolve()
        self.uploads = self.directory / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.database = (database or self.directory / "datasets.duckdb").resolve()
        self.max_upload_bytes = max_upload_bytes
        self._lock = RLock()
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS datasets "
                "(id VARCHAR PRIMARY KEY, metadata JSON NOT NULL, profile JSON)"
            )

    @contextmanager
    def connect(self):
        # Short-lived connections keep reloads simple. One thread makes aggregates repeatable.
        with self._lock, duckdb.connect(str(self.database), config={"threads": 1}) as connection:
            yield connection

    @staticmethod
    def table_name(dataset_id: str) -> str:
        if not re.fullmatch(r"ds_[0-9a-f]{32}", dataset_id):
            raise ValueError("Invalid file ID. Use the ID returned by the upload page.")
        return dataset_id

    def save_upload(self, filename: str, content: bytes, brief: DataBrief | None = None) -> UploadedDataset:
        if Path(filename).suffix.lower() != ".csv":
            raise ValueError("Choose a .csv file.")
        if not content or not content.strip():
            raise ValueError("The CSV file is empty.")
        if len(content) > self.max_upload_bytes:
            raise ValueError("The CSV exceeds the upload size limit.")
        # Geometry, JSON, and other large cells are stored locally, not sent to a model.
        csv.field_size_limit(self.max_upload_bytes)
        try:
            reader = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
            headers = next(reader)
            if not headers or any(not name.strip() for name in headers):
                raise ValueError("Every CSV column needs a header.")
            if len({name.casefold() for name in headers}) != len(headers):
                raise ValueError("CSV column headers must be unique, ignoring case.")
            if len(headers) > 100:
                raise ValueError("This profiler supports up to 100 columns per CSV.")
            for line, row in enumerate(reader, start=2):
                if len(row) != len(headers):
                    raise ValueError(f"CSV row {line} has {len(row)} fields; expected {len(headers)}.")
        except UnicodeDecodeError as exc:
            raise ValueError("Save the CSV with UTF-8 encoding and upload it again.") from exc
        except (csv.Error, StopIteration) as exc:
            raise ValueError("The CSV could not be parsed. Check its header and quoting.") from exc

        dataset = UploadedDataset(
            dataset_id=f"ds_{uuid4().hex}",
            filename=Path(filename).name,
            sha256=hashlib.sha256(content).hexdigest(),
            headers=headers,
            uploaded_at=datetime.now(timezone.utc),
            brief=brief,
        )
        path = self.uploads / f"{dataset.dataset_id}.csv"
        try:
            path.write_bytes(content)
            with self.connect() as connection:
                connection.execute(
                    "INSERT INTO datasets (id, metadata) VALUES (?, ?)",
                    [dataset.dataset_id, dataset.model_dump_json()],
                )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return dataset

    def get_upload(self, dataset_id: str) -> UploadedDataset:
        self.table_name(dataset_id)
        with self.connect() as connection:
            row = connection.execute("SELECT metadata FROM datasets WHERE id = ?", [dataset_id]).fetchone()
        if row is None:
            raise DatasetNotFound("File ID not found. Upload the CSV first.")
        return UploadedDataset.model_validate_json(row[0])

    def update_brief(self, dataset_id: str, brief: DataBrief | None) -> UploadedDataset:
        dataset = self.get_upload(dataset_id).model_copy(update={"brief": brief})
        with self.connect() as connection:
            connection.execute(
                "UPDATE datasets SET metadata = ? WHERE id = ?", [dataset.model_dump_json(), dataset_id]
            )
        return dataset

    def list_datasets(self) -> list[DatasetSummary]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT metadata, json_extract_string(profile, '$.status'), "
                "CAST(json_extract(profile, '$.deterministic.row_count') AS INTEGER) FROM datasets "
                "ORDER BY json_extract_string(metadata, '$.uploaded_at') DESC"
            ).fetchall()
        summaries = []
        for metadata, status, row_count in rows:
            dataset = UploadedDataset.model_validate_json(metadata)
            summaries.append(DatasetSummary(
                dataset_id=dataset.dataset_id,
                filename=dataset.filename,
                uploaded_at=dataset.uploaded_at,
                has_brief=dataset.brief is not None,
                profile_status=status or "none",
                row_count=row_count,
            ))
        return summaries

    def import_csv(self, dataset_id: str) -> UploadedDataset:
        dataset = self.get_upload(dataset_id)
        table = quote_identifier(self.table_name(dataset_id))
        path = self.uploads / f"{dataset_id}.csv"
        with self.connect() as connection:
            # A single CREATE statement is atomic; retries reuse the imported table.
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {table} AS "
                "SELECT * FROM read_csv(?, header=true, delim=',', sample_size=-1, "
                "strict_mode=true, null_padding=false, parallel=false)",
                [str(path)],
            )
        return dataset

    def get_profile(self, dataset_id: str) -> DatasetProfile | None:
        self.get_upload(dataset_id)
        with self.connect() as connection:
            row = connection.execute("SELECT profile FROM datasets WHERE id = ?", [dataset_id]).fetchone()
        return DatasetProfile.model_validate_json(row[0]) if row and row[0] else None

    def save_profile(self, profile: DatasetProfile) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE datasets SET profile = ? WHERE id = ?",
                [profile.model_dump_json(), profile.source.dataset_id],
            )
