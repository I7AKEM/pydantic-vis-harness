"""The analyst contracts: the query result, the analysis, the clarification, and the report."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vis_agent.profiler.models import ProfileCheck

ColumnKind = Literal["category", "ordinal", "time", "measure", "share", "geography", "identifier"]
Aggregate = Literal["sum", "avg", "count", "count_distinct", "min", "max", "share", "none"]
Cell = str | int | float | bool | None


class ResultColumn(BaseModel):
    """What one result column holds, written by the model when it runs the query."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The column name exactly as it appears in the result.")
    meaning: str = Field(description="What the column holds, in plain words, in the caller's language.")
    kind: ColumnKind = Field(description="category: a label. ordinal: an ordered label. time: a date or period. "
                                         "measure: a number. share: a percentage or fraction. geography: a place or "
                                         "coordinate. identifier: a key.")
    unit: str | None = Field(default=None, description="Unit of a measure or share, such as SAR or %. Null otherwise.")
    source: str | None = Field(default=None, description="The dataset column this comes from, or null when computed "
                                                         "from several.")
    aggregate: Aggregate = Field(default="none", description="How the source was aggregated, or none.")
    denominator: str | None = Field(default=None, description="For a share: what the share is of, in words.")

    @field_validator("unit", "source", "denominator", mode="before")
    @classmethod
    def _placeholder_is_null(cls, value):
        # Models sometimes write the word null, or a dash, instead of a JSON null. A unit like that would be
        # printed on the picture, and a source like that fails the column check and can end a run.
        if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "n/a", "na", "-"}:
            return None
        return value

    @model_validator(mode="after")
    def _consistent(self):
        if self.unit is not None and self.kind not in ("measure", "share"):
            raise ValueError("unit belongs only on a measure or a share")
        if self.kind == "share" and not self.denominator:
            # A missing denominator is a gap in the description, not a wrong result; rejecting it cost whole runs.
            self.denominator = "not stated"
        return self


class PreviousAnalysis(BaseModel):
    """The analysis being revised: what produced the earlier result, and what must differ."""

    model_config = ConfigDict(extra="forbid")

    sql: str
    columns: list[ResultColumn]
    change: str


class QueryResult(BaseModel):
    """What run_query returns when the statement ran: the bounded table and the checks."""

    sql: str
    columns: list[str]
    types: list[str]
    rows: list[list[Cell]]
    row_count: int
    checks: list[ProfileCheck] = Field(default_factory=list)
    seconds: float


class QueryError(BaseModel):
    """What run_query returns when the statement was rejected or failed. The model reads it and repairs."""

    sql: str
    error: str
    hint: str | None = None


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str
    columns: list[ResultColumn]
    summary: str
    assumptions: list[str] = Field(default_factory=list)


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    reason: str


class AnalysisReport(BaseModel):
    """What every caller receives."""

    dataset_id: str
    question: str
    language: str
    brief_fingerprint: str | None = None
    analysis: Analysis | None = None
    clarification: Clarification | None = None
    result: QueryResult | None = None
    checks: list[ProfileCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str | None = None
    seconds: float
    created_at: datetime
