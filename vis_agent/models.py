"""Contracts shared by the store, the lead, and every agent."""

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal["compare", "trend", "rank", "distribution", "composition", "relation", "share"]


class DataBrief(BaseModel):
    """Context that travels with a dataset. Hints for interpretation, never facts."""

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
    caveats: list[str] = Field(default_factory=list)
    brand_colors: list[str] = Field(default_factory=list)
    producer_agent: str | None = None

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json(exclude_none=True).encode()).hexdigest()[:16]


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
