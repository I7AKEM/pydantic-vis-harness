"""The data contracts shared by storage, the profiler, and the chat agent."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

PROFILE_VERSION = "1.2"


class UploadedDataset(BaseModel):
    dataset_id: str
    filename: str
    sha256: str
    headers: list[str]
    uploaded_at: datetime


class ValueCount(BaseModel):
    value: str
    count: int


class NumericStatistics(BaseModel):
    finite_count: int
    non_finite_count: int
    minimum: FiniteFloat | None
    maximum: FiniteFloat | None
    mean: FiniteFloat | None
    standard_deviation: FiniteFloat | None
    q25: FiniteFloat | None
    median: FiniteFloat | None
    q75: FiniteFloat | None


class ColumnStatistics(BaseModel):
    name: str
    original_name: str
    physical_type: str
    null_count: int
    null_percentage: float
    distinct_count: int
    maximum_value_bytes: int = 0
    values_omitted: bool = False
    common_values: list[ValueCount] = Field(default_factory=list)
    numeric: NumericStatistics | None = None
    earliest: str | None = None
    latest: str | None = None


class DeterministicProfile(BaseModel):
    row_count: int
    column_count: int
    duplicate_rows: int
    columns: list[ColumnStatistics]
    sample_rows: list[dict[str, str | None]]
    sample_description: str
    warnings: list[str] = Field(default_factory=list)


class ColumnSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    meaning: str | None
    role: Literal["identifier", "measure", "category", "time", "boolean", "text", "unknown"]
    unit: str | None
    confidence: Literal["low", "medium", "high"]
    evidence: str


class SemanticProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    row_meaning: str | None
    columns: list[ColumnSemantics]
    questions: list[str] = Field(default_factory=list)


class DatasetProfile(BaseModel):
    schema_version: str = PROFILE_VERSION
    source: UploadedDataset
    status: Literal["complete", "partial"]
    deterministic: DeterministicProfile
    semantic: SemanticProfile | None = None
    semantic_model: str | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
