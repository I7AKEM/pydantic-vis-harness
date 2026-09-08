"""Requests and artifacts in the datasets database. All IDs are generated here."""

import re
from datetime import datetime, timezone
from uuid import uuid4

from vis_agent.requests.models import (
    DEFAULT_DEADLINE_SECONDS, Artifact, ArtifactSummary, Caller, Request, RequestSummary, RequestType,
)
from vis_agent.store import DatasetStore

REQUEST_ID = re.compile(r"rq_[0-9a-f]{32}\Z")
ARTIFACT_ID = re.compile(r"art_[0-9a-f]{32}\Z")


class RequestNotFound(ValueError):
    """The ID is well formed but no request has it."""


class ArtifactNotFound(ValueError):
    """The ID is well formed but no artifact has it."""


def now() -> datetime:
    return datetime.now(timezone.utc)


class RequestStore:
    """Two tables next to the datasets table, sharing its connection and lock."""

    def __init__(self, datasets: DatasetStore):
        self.datasets = datasets
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS requests (id VARCHAR PRIMARY KEY, record JSON NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS artifacts (id VARCHAR PRIMARY KEY, dataset_id VARCHAR NOT NULL, "
                "request_id VARCHAR NOT NULL, record JSON NOT NULL)"
            )

    def connect(self):
        return self.datasets.connect()

    @staticmethod
    def check_request_id(request_id: str) -> str:
        if not REQUEST_ID.fullmatch(request_id or ""):
            raise ValueError("Invalid request ID. Use the rq_ ID a tool returned.")
        return request_id

    @staticmethod
    def check_artifact_id(artifact_id: str) -> str:
        if not ARTIFACT_ID.fullmatch(artifact_id or ""):
            raise ValueError("Invalid artifact ID. Use the art_ ID a tool returned.")
        return artifact_id

    def new_request(self, type: RequestType, dataset_id: str, question: str, caller: Caller,
                    parent_artifact_id: str | None = None, redo_analysis: bool = False,
                    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS) -> Request:
        """Create a running request. The dataset must exist; a revision's parent must exist and match it."""
        self.datasets.get_upload(dataset_id)
        if type == "revise" and parent_artifact_id is None:
            raise ValueError("A revision names the artifact to change.")
        if type == "new" and parent_artifact_id is not None:
            raise ValueError("A new request does not name a parent artifact; ask for a revision instead.")
        if parent_artifact_id is not None and self.get_artifact(parent_artifact_id).dataset_id != dataset_id:
            raise ValueError("The artifact belongs to another dataset.")
        if not question or not question.strip():
            raise ValueError("The request needs a question or a change.")
        moment = now()
        request = Request(
            request_id=f"rq_{uuid4().hex}", type=type, dataset_id=dataset_id, question=question.strip(),
            parent_artifact_id=parent_artifact_id, redo_analysis=redo_analysis, caller=caller,
            deadline_seconds=deadline_seconds, created_at=moment, updated_at=moment,
        )
        with self.connect() as connection:
            connection.execute("INSERT INTO requests (id, record) VALUES (?, ?)",
                               [request.request_id, request.model_dump_json()])
        return request

    def save_request(self, request: Request) -> Request:
        request.updated_at = now()
        with self.connect() as connection:
            connection.execute("UPDATE requests SET record = ? WHERE id = ?",
                               [request.model_dump_json(), request.request_id])
        return request

    def get_request(self, request_id: str) -> Request:
        self.check_request_id(request_id)
        with self.connect() as connection:
            row = connection.execute("SELECT record FROM requests WHERE id = ?", [request_id]).fetchone()
        if row is None:
            raise RequestNotFound("Request ID not found.")
        return Request.model_validate_json(row[0])

    def list_requests(self, dataset_id: str | None = None, conversation_id: str | None = None,
                      unfinished_only: bool = False, limit: int = 50) -> list[RequestSummary]:
        """Newest first. Unfinished means any status but done."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT record FROM requests ORDER BY json_extract_string(record, '$.created_at') DESC"
            ).fetchall()
        moment = now()
        summaries = []
        for (record,) in rows:
            request = Request.model_validate_json(record)
            if dataset_id and request.dataset_id != dataset_id:
                continue
            if conversation_id and request.caller.conversation_id != conversation_id:
                continue
            if unfinished_only and request.status == "done":
                continue
            summaries.append(request.summary(moment))
        return summaries[:limit]

    @staticmethod
    def new_artifact_id() -> str:
        return f"art_{uuid4().hex}"

    def save_artifact(self, artifact: Artifact) -> Artifact:
        self.check_artifact_id(artifact.artifact_id)
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO artifacts (id, dataset_id, request_id, record) VALUES (?, ?, ?, ?)",
                [artifact.artifact_id, artifact.dataset_id, artifact.request_id, artifact.model_dump_json()],
            )
        return artifact

    def get_artifact(self, artifact_id: str) -> Artifact:
        self.check_artifact_id(artifact_id)
        with self.connect() as connection:
            row = connection.execute("SELECT record FROM artifacts WHERE id = ?", [artifact_id]).fetchone()
        if row is None:
            raise ArtifactNotFound("Artifact ID not found.")
        return Artifact.model_validate_json(row[0])

    def artifact_for_request(self, request_id: str) -> Artifact | None:
        self.check_request_id(request_id)
        with self.connect() as connection:
            row = connection.execute("SELECT record FROM artifacts WHERE request_id = ?", [request_id]).fetchone()
        return Artifact.model_validate_json(row[0]) if row else None

    def list_artifacts(self, dataset_id: str | None = None, artifact_id: str | None = None,
                       limit: int = 50) -> list[ArtifactSummary]:
        """Newest first. With artifact_id: that artifact's lineage, ancestors and descendants included."""
        if artifact_id is not None:
            dataset_id = self.get_artifact(artifact_id).dataset_id
        with self.connect() as connection:
            if dataset_id is not None:
                rows = connection.execute(
                    "SELECT record FROM artifacts WHERE dataset_id = ? "
                    "ORDER BY json_extract_string(record, '$.created_at') DESC", [dataset_id]).fetchall()
            else:
                rows = connection.execute(
                    "SELECT record FROM artifacts ORDER BY json_extract_string(record, '$.created_at') DESC"
                ).fetchall()
        artifacts = [Artifact.model_validate_json(record) for (record,) in rows]
        if artifact_id is not None:
            by_id = {a.artifact_id: a for a in artifacts}
            related = {artifact_id}
            cursor = by_id[artifact_id].parent_artifact_id
            while cursor is not None and cursor not in related:
                related.add(cursor)
                cursor = by_id[cursor].parent_artifact_id if cursor in by_id else None
            grew = True
            while grew:
                grew = False
                for candidate in artifacts:
                    if candidate.parent_artifact_id in related and candidate.artifact_id not in related:
                        related.add(candidate.artifact_id)
                        grew = True
            artifacts = [a for a in artifacts if a.artifact_id in related]
        return [a.summary() for a in artifacts[:limit]]
