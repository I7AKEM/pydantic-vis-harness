"""Read the data agent's finished CSV without analyzing or replacing its values."""

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from vis_agent.analyst.models import Analysis, AnalysisReport, QueryResult, ResultColumn
from vis_agent.models import DataBrief, UploadedDataset
from vis_agent.profiler.measurements import (
    GEOMETRY_NAME, MAX_MODEL_VALUE_BYTES, NUMERIC_TYPES, TIME_TYPES, WKT_SQL_PATTERN,
)
from vis_agent.store import DatasetStore, quote_identifier

# A resource bound, never a sample presented as the complete source.
SOURCE_ROW_CAP = 10_000
TIME_NAME = re.compile(r"(^|[_\s])(year|month|date|period|hijri|سنة|السنة|عام|العام|شهر|الشهر|تاريخ|التاريخ|هجري)($|[_\s])", re.I)


@dataclass
class SourceTable:
    source: UploadedDataset
    table: str
    columns: list[ResultColumn]
    types: list[str]
    omitted: list[str]
    row_count: int


def prepare_csv_source(store: DatasetStore, dataset_id: str, brief: DataBrief | None = None) -> SourceTable:
    """Build a shared read-only view preserving source labels and parsing numeric representations.

    The typed import is only a type hint. All values come from the original all-text
    snapshot, so identifiers and dates never inherit lossy CSV type inference.
    Arabic-Indic numeric measurements are parsed in SQL; dates and leading-zero
    labels remain text. Geometry and oversized values remain local.
    """
    source = store.import_csv(dataset_id)
    brief = brief or source.brief
    imported = quote_identifier(store.table_name(dataset_id))
    raw = quote_identifier(f"{dataset_id}_source")
    table = f"{dataset_id}_values"
    metadata, selections, types, omitted = [], [], [], []
    with store.connect() as connection:
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {raw} AS SELECT * FROM read_csv(?, "
            "header=true, delim=',', all_varchar=true, strict_mode=true, null_padding=false, parallel=false)",
            [str(store.uploads / f"{dataset_id}.csv")],
        )
        row_count = connection.execute(f"SELECT count(*) FROM {raw}").fetchone()[0]
        for name, physical_type, *_ in connection.execute(f"DESCRIBE {imported}").fetchall():
            column = quote_identifier(name)
            normalized = f"replace(translate({column}, '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬', '01234567890123456789.,'), ',', '')"
            maximum_bytes, geometry, leading_zero, localized, numeric_text, integer_text = connection.execute(
                f"SELECT coalesce(max(octet_length(encode({column}))), 0), "
                f"coalesce(bool_or(regexp_matches({column}, ?, 'i')), false), "
                f"coalesce(bool_or(regexp_matches({normalized}, '^[-+]?0[0-9]+')), false), "
                f"coalesce(bool_or(regexp_matches({column}, '[٠-٩۰-۹]')), false), "
                f"coalesce(bool_and({column} IS NULL OR try_cast({normalized} AS DOUBLE) IS NOT NULL), false), "
                f"coalesce(bool_and({column} IS NULL OR regexp_full_match({normalized}, '[-+]?[0-9]+')), false) "
                f"FROM {raw}", [WKT_SQL_PATTERN],
            ).fetchone()
            numeric = physical_type.startswith(NUMERIC_TYPES) and not leading_zero
            localized_number = localized and numeric_text and not leading_zero and not TIME_NAME.search(name)
            if localized_number:
                physical_type = "DOUBLE"
                if integer_text:
                    fits = connection.execute(
                        f"SELECT bool_and({column} IS NULL OR try_cast({normalized} AS BIGINT) IS NOT NULL) FROM {raw}"
                    ).fetchone()[0]
                    if fits:
                        physical_type = "BIGINT"
                expression = f"CAST({normalized} AS {physical_type})"
                numeric = True
            else:
                expression = f"CAST({column} AS {physical_type})" if numeric else column
            selections.append(f"{expression} AS {column}")
            if GEOMETRY_NAME.search(name) or geometry or maximum_bytes > MAX_MODEL_VALUE_BYTES:
                omitted.append(name)
                continue
            coded = brief and (brief.code_meanings.get(name) or any(
                labels.value_labels.get(name) for labels in brief.display_labels.values()
            ))
            kind = "category" if coded else "measure" if numeric else "time" if physical_type.startswith(TIME_TYPES) or TIME_NAME.search(name) else "category"
            types.append(physical_type if numeric else "VARCHAR")
            metadata.append(ResultColumn(
                name=name, meaning=(brief.column_descriptions.get(name) if brief else None) or name,
                kind=kind, unit=brief.units.get(name) if brief and kind == "measure" else None,
                source=name, aggregate="none",
            ))
        connection.execute(f"CREATE OR REPLACE VIEW {quote_identifier(table)} AS SELECT {', '.join(selections)} FROM {raw}")
    return SourceTable(source, table, metadata, types, omitted, row_count)


def load_csv_report(
    store: DatasetStore, dataset_id: str, question: str, *, brief: DataBrief | None = None,
    columns: list[ResultColumn] | None = None, language: str | None = None,
) -> AnalysisReport:
    """Load every supplied row for charting; expert annotations affect metadata only."""
    from vis_agent.analyst.agent import detect_language

    started = time.perf_counter()
    prepared = prepare_csv_source(store, dataset_id, brief)
    brief = brief or prepared.source.brief
    if prepared.row_count > SOURCE_ROW_CAP:
        raise ValueError(
            f"The supplied CSV has {prepared.row_count} rows; the direct renderer supports at most {SOURCE_ROW_CAP}. "
            "No rows were sampled or aggregated. A smaller selection requires an explicit request."
        )
    if not prepared.columns:
        raise ValueError("The CSV has no columns that can be sent to the visualization team.")
    metadata = prepared.columns
    overrides = {column.name: column for column in columns or []}
    if len(overrides) != len(columns or []):
        raise ValueError("Column annotations must have distinct names.")
    unknown = overrides.keys() - {column.name for column in metadata}
    if unknown:
        raise ValueError("Column annotations must name available CSV columns: " + ", ".join(sorted(unknown)))
    metadata = [overrides.get(column.name, column).model_copy(update={"source": column.name, "aggregate": "none"})
                for column in metadata]
    sql = f"SELECT {', '.join(quote_identifier(column.name) for column in metadata)} FROM {quote_identifier(prepared.table)}"
    with store.connect() as connection:
        rows = [list(row) for row in connection.execute(sql).fetchall()]
    warnings = (["Columns kept local because they contain geometry or oversized values: " + ", ".join(prepared.omitted)]
                if prepared.omitted else [])
    language = language or detect_language(question, brief, [column.name for column in metadata])
    result = QueryResult(sql=sql, columns=[column.name for column in metadata], types=prepared.types,
                         rows=rows, row_count=prepared.row_count, seconds=time.perf_counter() - started)
    return AnalysisReport(
        dataset_id=dataset_id, question=question, language=language,
        brief_fingerprint=brief.fingerprint() if brief else None,
        analysis=Analysis(sql=sql, columns=metadata, summary=""), result=result,
        warnings=warnings, seconds=time.perf_counter() - started, created_at=datetime.now(timezone.utc),
    )
