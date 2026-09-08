"""Contracts for requests, their checkpoints, and the artifacts they deliver."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vis_agent.analyst.models import AnalysisReport, Clarification, ResultColumn
from vis_agent.designer.models import ChartType, Compromise, Design

RequestType = Literal["new", "revise"]
StepName = Literal["understand", "profile", "analyze", "design", "render", "review", "deliver"]
STEPS: tuple[StepName, ...] = ("understand", "profile", "analyze", "design", "render", "review", "deliver")
RequestStatus = Literal["running", "waiting", "done", "failed", "stopped"]
CallerKind = Literal["chat", "terminal", "agent"]
MAX_QUESTIONS = 2
DEFAULT_DEADLINE_SECONDS = 24 * 60 * 60
LEAD_ROWS = 50


class Caller(BaseModel):
    """Who asked: the chat with its conversation, the terminal, or a program with a return address."""

    model_config = ConfigDict(extra="forbid")

    kind: CallerKind
    conversation_id: str | None = None
    identity: str | None = None
    return_address: str | None = None

    @field_validator("return_address")
    @classmethod
    def _http_only(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("The return address must be an http or https URL.")
        return value


class Exchange(BaseModel):
    """One question the request asked, and the answer once it arrived."""

    step: StepName
    question: str
    reason: str
    asked_at: datetime
    deadline: datetime
    answer: str | None = None
    answered_at: datetime | None = None
    answered_by: CallerKind | None = None

    def overdue(self, now: datetime) -> bool:
        return self.answer is None and now > self.deadline


class RequestSummary(BaseModel):
    request_id: str
    type: RequestType
    dataset_id: str
    question: str
    status: RequestStatus
    artifact_id: str | None = None
    pending_question: str | None = None
    overdue: bool = False
    created_at: datetime
    updated_at: datetime


class Request(BaseModel):
    """One piece of work about one dataset, with the saved output of every completed step."""

    request_id: str
    type: RequestType
    dataset_id: str
    question: str
    parent_artifact_id: str | None = None
    redo_analysis: bool = False
    caller: Caller
    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS
    language: str | None = None
    status: RequestStatus = "running"
    steps: dict[str, Any] = Field(default_factory=dict)
    clarifications: list[Exchange] = Field(default_factory=list)
    artifact_id: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    def pending(self) -> Exchange | None:
        """The question waiting for an answer, if any."""
        for exchange in reversed(self.clarifications):
            if exchange.answer is None:
                return exchange
        return None

    def next_step(self) -> StepName | None:
        """The first step with no saved output, or None when every step has one."""
        for step in STEPS:
            if step not in self.steps:
                return step
        return None

    def summary(self, now: datetime) -> RequestSummary:
        pending = self.pending()
        return RequestSummary(
            request_id=self.request_id, type=self.type, dataset_id=self.dataset_id, question=self.question,
            status=self.status, artifact_id=self.artifact_id,
            pending_question=pending.question if pending else None,
            overdue=pending.overdue(now) if pending else False,
            created_at=self.created_at, updated_at=self.updated_at,
        )


class Lineage(BaseModel):
    """What the artifact was built from, enough to rebuild it."""

    profile_created_at: datetime | None = None
    brief_fingerprint: str | None = None
    catalogue_version: str
    rules_version: str
    renderer: str = "gptvis"
    analyst_model: str | None = None
    designer_model: str | None = None


class ArtifactSummary(BaseModel):
    artifact_id: str
    request_id: str
    dataset_id: str
    version: int
    parent_artifact_id: str | None = None
    question: str
    change: str | None = None
    chart: ChartType | None = None
    png_url: str | None = None
    created_at: datetime


class Artifact(BaseModel):
    """The unit of delivery and memory: the numbers, the chart, the files, and where they came from."""

    artifact_id: str
    request_id: str
    dataset_id: str
    version: int = 1
    parent_artifact_id: str | None = None
    question: str
    change: str | None = None
    report: AnalysisReport
    design: Design | None = None
    no_chart_reason: str | None = None
    render_id: str | None = None
    png_url: str | None = None
    html_url: str | None = None
    review: dict[str, Any] | None = None
    clarifications: list[Exchange] = Field(default_factory=list)
    lineage: Lineage
    created_at: datetime

    def summary(self) -> ArtifactSummary:
        return ArtifactSummary(
            artifact_id=self.artifact_id, request_id=self.request_id, dataset_id=self.dataset_id,
            version=self.version, parent_artifact_id=self.parent_artifact_id, question=self.question,
            change=self.change, chart=self.design.chart if self.design else None, png_url=self.png_url,
            created_at=self.created_at,
        )


class LeadArtifact(BaseModel):
    """What the lead sees of an artifact: the table bounded to LEAD_ROWS rows, the chart, the explanation."""

    artifact_id: str
    request_id: str
    dataset_id: str
    version: int
    parent_artifact_id: str | None = None
    question: str
    change: str | None = None
    summary: str | None = None
    assumptions: list[str] = []
    columns: list[ResultColumn] = []
    rows: list[list] = []
    row_count: int = 0
    sql: str | None = None
    chart: ChartType | None = None
    spec: str | None = None
    explanation: str | None = None
    compromises: list[Compromise] = []
    no_chart_reason: str | None = None
    png_url: str | None = None
    html_url: str | None = None
    warnings: list[str] = []

    @classmethod
    def from_artifact(cls, artifact: Artifact) -> "LeadArtifact":
        analysis, table, design = artifact.report.analysis, artifact.report.result, artifact.design
        return cls(
            artifact_id=artifact.artifact_id, request_id=artifact.request_id, dataset_id=artifact.dataset_id,
            version=artifact.version, parent_artifact_id=artifact.parent_artifact_id,
            question=artifact.question, change=artifact.change,
            summary=analysis.summary if analysis else None,
            assumptions=analysis.assumptions if analysis else [],
            columns=analysis.columns if analysis else [],
            rows=table.rows[:LEAD_ROWS] if table else [], row_count=table.row_count if table else 0,
            sql=analysis.sql if analysis else None,
            chart=design.chart if design else None, spec=design.spec if design else None,
            explanation=design.explanation if design else None,
            compromises=design.compromises if design else [],
            no_chart_reason=artifact.no_chart_reason, png_url=artifact.png_url, html_url=artifact.html_url,
            warnings=list(artifact.report.warnings),
        )


class RequestOutcome(BaseModel):
    """What a run returns: the artifact, the question the request waits on, or the failure."""

    request_id: str
    status: RequestStatus
    artifact: LeadArtifact | None = None
    clarification: Clarification | None = None
    overdue: bool = False
    error: str | None = None
    warnings: list[str] = []
