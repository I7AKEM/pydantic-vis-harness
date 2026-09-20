"""The profile contracts: measurements, interpretation, checks, and the saved profile."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

from vis_agent.models import UploadedDataset
from vis_agent.units import COUNT_UNITS

PROFILE_VERSION = "2.0"

MeasurementLevel = Literal[
    "nominal", "ordinal", "interval", "discrete", "continuous", "time", "geographic", "hijri", "arabic_digits",
]
GeographicRole = Literal["latitude", "longitude", "wkt", "place_name"]


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
    # Measurement labels. Every one is assigned from a DuckDB query result.
    measurement_levels: list[MeasurementLevel] = Field(default_factory=list)
    integer_valued: bool | None = None
    boolean_vocabulary: list[str] | None = None
    ordinal_pattern: str | None = None
    geographic_role: GeographicRole | None = None
    codes: list[str] | None = None


class DeterministicProfile(BaseModel):
    row_count: int
    column_count: int
    duplicate_rows: int
    columns: list[ColumnStatistics]
    sample_rows: list[dict[str, str | None]]
    sample_description: str
    warnings: list[str] = Field(default_factory=list)


UNIT_PLACEHOLDERS = frozenset({
    "", "null", "none", "nil", "n/a", "na", "nan", "-", "unknown", "unitless", "no unit", "not applicable",
    "لا يوجد", "بدون", "غير محدد",
}) | COUNT_UNITS


class ColumnSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    meaning: str | None = Field(description="What the column measures or names, in plain words.")
    role: Literal["identifier", "measure", "category", "ordinal", "time", "boolean", "geography", "text", "unknown"] = Field(
        description="identifier: unique key. measure: a number to aggregate. category: a label. ordinal: an ordered label such as Q1. "
                    "time: a date or time. boolean: yes or no. geography: coordinates, WKT, or place names. text: free text."
    )
    unit: str | None = Field(description="Unit of a measure, such as USD or kg. Null for anything that is not a measure.")
    confidence: Literal["low", "medium", "high"]
    evidence: str = Field(description="The specific measurements or sample values this interpretation rests on.")
    code_meanings: dict[str, str] | None = Field(
        default=None, description="For coded values such as F and M: each code and its meaning, when known."
    )
    brief_conflict: str | None = Field(
        default=None, description="Set when a hint in the brief contradicts the measurements. Say what the brief claimed and what the data shows."
    )

    @field_validator("unit", mode="before")
    @classmethod
    def drop_placeholder_units(cls, value):
        """A model that writes the word null, or count, means no unit: counts have none, only measures carry one."""
        if isinstance(value, str) and value.strip().casefold() in UNIT_PLACEHOLDERS:
            return None
        return value


class SemanticProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    row_meaning: str | None
    columns: list[ColumnSemantics]
    questions: list[str] = Field(default_factory=list)


class ProfileCheck(BaseModel):
    column: str | None
    check: str
    severity: Literal["error", "warning"]
    passed: bool
    message: str


class DatasetProfile(BaseModel):
    schema_version: str = PROFILE_VERSION
    source: UploadedDataset
    status: Literal["complete", "partial"]
    deterministic: DeterministicProfile
    semantic: SemanticProfile | None = None
    semantic_model: str | None = None
    brief_fingerprint: str | None = None
    review: list[ProfileCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
