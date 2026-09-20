# vis_agent/reviewer/models.py
"""What the reviewer reads and what it returns."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vis_agent.analyst.models import Cell, ColumnKind
from vis_agent.designer.models import ChartType
from vis_agent.findings import Finding
from vis_agent.models import DisplayLabels, QuestionAnswer


class ReviewColumn(BaseModel):
    name: str
    meaning: str
    kind: ColumnKind
    unit: str | None = None


class ReviewerPrompt(BaseModel):
    """The picture travels beside this as binary content; nothing here is the dataset, the SQL, or the profile."""

    question: str
    original_question: str | None = None
    caveats: list[str] = Field(default_factory=list)
    language: str
    clarifications: list[QuestionAnswer] = []  # the caller's answers change what the chart must show
    chart: ChartType
    spec: str
    columns: list[ReviewColumn]
    rows: list[dict[str, Cell]]
    row_ids: list[int] = Field(default_factory=list, description="One-based source-result row numbers, aligned with rows.")
    row_count: int
    rows_are_partial: bool
    truncated_cells: dict[int, list[str]] = Field(default_factory=dict)
    omitted_columns: list[str] = Field(default_factory=list)
    compromises: list[str] = []
    warnings: list[str] = Field(default_factory=list)
    image_id: str | None = None
    round: int = 1
    code_meanings: dict[str, dict[str, str]] = Field(default_factory=dict)
    display_labels: DisplayLabels = Field(default_factory=DisplayLabels)

    @model_validator(mode="before")
    @classmethod
    def read_legacy_rows(cls, value):
        """Old saved prompts used metadata-ordered arrays; new prompts bind using result column names."""
        if isinstance(value, dict) and value.get("rows") and isinstance(value["rows"][0], list):
            value = dict(value)
            names = [c["name"] if isinstance(c, dict) else c.name for c in value["columns"]]
            value["rows"] = [dict(zip(names, row, strict=True)) for row in value["rows"]]
        return value


EvidenceText = Annotated[str, Field(min_length=1, pattern=r"\S")]


class ReviewReference(BaseModel):
    """An address to check, not a claim that the model's perception is true."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["cell", "column", "spec", "request", "image", "source"] = Field(
        description="cell: exact named source cell; column: metadata; spec/request: supplied text; "
        "image: directly visible readability/drawing defect; source: a claim requiring the complete source rows.",
    )
    row: int | None = Field(default=None, ge=1, description="Source row ID for a cell reference, not image position.")
    column: str | None = None
    quote: str | None = Field(default=None, description="Exact supporting source text/value for cell, column, spec or request.")


class VisualFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: Literal["R-1", "R-2", "R-3", "R-4", "R-5"]
    level: Literal["error", "warning"]
    owner: Literal["designer", "renderer", "none"]
    location: EvidenceText = Field(description="The image region, mark, label or series where the defect is visible.")
    observed: EvidenceText = Field(description="What the picture visibly shows, not a hypothesis or requested edit.")
    expected: EvidenceText = Field(description="What the cited reference requires, or the unreadable content's role.")
    reference: ReviewReference


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "revise", "uncertain"] = Field(
        description="revise: a material defect was reported, regardless of owner; this does not schedule repair. "
        "uncertain: no reported error, but material inspection uncertainty remains. pass: neither.",
    )
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[VisualFinding] = Field(default_factory=list, description="Same order as findings; absent in legacy reviews.")
    uncertainties: list[str] = Field(default_factory=list)
    image_id: str | None = None


class ReviewReport(BaseModel):
    review: Review | None = None
    warnings: list[str] = Field(default_factory=list)
    model: str | None = None
    requests: int = 0
    round: int = 1
    seconds: float
    created_at: datetime
