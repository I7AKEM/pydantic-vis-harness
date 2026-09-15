# vis_agent/reviewer/models.py
"""What the reviewer reads and what it returns."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vis_agent.analyst.models import Cell, ColumnKind
from vis_agent.designer.models import ChartType
from vis_agent.findings import Finding
from vis_agent.models import QuestionAnswer


class ReviewColumn(BaseModel):
    name: str
    meaning: str
    kind: ColumnKind
    unit: str | None = None


class ReviewerPrompt(BaseModel):
    """The picture travels beside this as binary content; nothing here is the dataset, the SQL, or the profile."""

    question: str
    language: str
    clarifications: list[QuestionAnswer] = []  # the caller's answers change what the chart must show
    chart: ChartType
    spec: str
    columns: list[ReviewColumn]
    rows: list[list[Cell]]
    row_count: int
    rows_are_partial: bool
    summary: str | None = None
    assumptions: list[str] = []
    compromises: list[str] = []
    warnings: list[str] = []
    caveats: list[str] = []
    round: int = 1


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "revise"]
    summary: str
    findings: list[Finding] = Field(default_factory=list)


class ReviewReport(BaseModel):
    review: Review | None = None
    warnings: list[str] = Field(default_factory=list)
    model: str | None = None
    requests: int = 0
    round: int = 1
    seconds: float
    created_at: datetime
