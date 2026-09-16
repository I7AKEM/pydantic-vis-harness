"""Contracts shared by the store, the lead, and every agent."""

import hashlib
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal["compare", "trend", "rank", "distribution", "composition", "relation", "share", "summary"]


DisplayText = Annotated[str, Field(min_length=1, pattern=r"\S")]


class DisplayLabels(BaseModel):
    """Presentation metadata keyed by exact column and original category value."""

    model_config = ConfigDict(extra="forbid")

    column_labels: dict[str, DisplayText] = Field(default_factory=dict)
    value_labels: dict[str, dict[str, DisplayText]] = Field(default_factory=dict)


class DataBrief(BaseModel):
    """Upstream intent and semantic definitions; measurements still come only from the CSV."""

    model_config = ConfigDict(extra="forbid")

    source: str | None = None
    query: str | None = None
    pulled_at: datetime | None = None
    raw_question: str | None = None
    enriched_question: str | None = None
    intent: Intent | None = None
    suggested_chart_type: str | None = None
    column_descriptions: dict[str, str] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    code_meanings: dict[str, dict[str, str]] = Field(default_factory=dict)
    display_labels: dict[Literal["ar", "en"], DisplayLabels] = Field(
        default_factory=dict, description="Approved display labels by language code (ar or en). "
        "Keys inside each mapping are exact CSV column names and original category values.",
    )
    caveats: list[str] = Field(default_factory=list)
    brand_colors: list[str] = Field(default_factory=list)
    producer_agent: str | None = None

    def fingerprint(self) -> str:
        # Adding optional presentation metadata must not invalidate every legacy brief.
        exclude = {"display_labels"} if not self.display_labels else None
        return hashlib.sha256(self.model_dump_json(exclude_none=True, exclude=exclude).encode()).hexdigest()[:16]


class QuestionAnswer(BaseModel):
    """A question an agent asked and the caller's answer. Answers are the caller's decisions, never facts about the data."""

    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str


class UploadedDataset(BaseModel):
    dataset_id: str
    filename: str
    sha256: str
    headers: list[str]
    uploaded_at: datetime
    brief: DataBrief | None = None


class DatasetSummary(BaseModel):
    dataset_id: str
    filename: str
    uploaded_at: datetime
    has_brief: bool
    profile_status: Literal["none", "partial", "complete"]
    row_count: int | None = None
