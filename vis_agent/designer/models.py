"""The designer's contracts: the spec, the recommendation, the check, and the compromises."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ChartType = Literal[
    "column", "bar", "grouped_column", "stacked_column", "grouped_bar", "stacked_bar",
    "line", "multi_line", "area", "stacked_area", "pie", "donut", "scatter", "histogram",
    "boxplot", "treemap", "radar", "dual_axes", "word_cloud", "table",
]
SortOrder = Literal["value desc", "value asc", "category asc", "category desc", "none"]
Theme = Literal["default", "dark", "academy"]
Language = Literal["ar", "en"]
Direction = Literal["ltr", "rtl"]
Digits = Literal["western", "arabic"]
ScaleKind = Literal["linear", "log"]
Switch = Literal["on", "off"]
Role = Literal["category", "value", "group", "time", "x", "y", "value2"]
ROLES: tuple[str, ...] = ("category", "value", "group", "time", "x", "y", "value2")


class NumberFormat(BaseModel):
    """How a number is written. Built from the `format` pattern or from the defaults."""

    model_config = ConfigDict(extra="forbid")

    thousands: bool = True
    decimals: int | None = None  # None: up to two, trailing zeros trimmed
    compact: bool = False
    unit: str | None = None
    digits: Digits = "western"


class Spec(BaseModel):
    """A parsed chart spec. Field names are the spec keys in snake case."""

    model_config = ConfigDict(extra="forbid")

    type: ChartType
    title: str | None = None
    subtitle: str | None = None
    description: str | None = None
    language: Language = "en"
    theme: Theme = "default"
    width: int | None = None
    height: int | None = None
    axis_x_title: str | None = None
    axis_y_title: str | None = None
    inner_radius: float | None = None
    bin_number: int | None = None
    bind: dict[str, str] = Field(default_factory=dict)
    sort: SortOrder | None = None
    limit: int | None = None
    other: str | None = None
    unknown: str | None = None
    emphasis: list[str] = Field(default_factory=list)
    palette: list[str] = Field(default_factory=list)
    background_color: str | None = None
    direction: Direction | None = None
    zero: bool | None = None
    axis_y_min: float | None = None
    axis_y_max: float | None = None
    axis_x_min: float | None = None
    axis_x_max: float | None = None
    axis_y_scale: ScaleKind = "linear"
    percent: bool = False
    labels: Switch | None = None
    legend: Switch | None = None
    format: str | None = None
    digits: Digits = "western"


class SpecIssue(BaseModel):
    line: int
    message: str


class SpecError(Exception):
    """Raised by parse with every issue found."""

    def __init__(self, issues: list[SpecIssue]):
        self.issues = issues
        super().__init__("; ".join(f"line {i.line}: {i.message}" for i in issues))


class Compromise(BaseModel):
    key: str
    message: str


class RuleScore(BaseModel):
    rule: str
    score: int
    explanation: str


class Candidate(BaseModel):
    name: str
    score: int
    binding: dict[str, str]
    breakdown: list[RuleScore]


class Rejection(BaseModel):
    name: str
    rule: str
    explanation: str


class Recommendation(BaseModel):
    candidates: list[Candidate]
    rejected: list[Rejection]


class Violation(BaseModel):
    rule: str
    message: str
    fix: str
    line: int | None = None


class SpecCheck(BaseModel):
    ok: bool
    violations: list[Violation] = Field(default_factory=list)
    compromises: list[Compromise] = Field(default_factory=list)
    canonical: str | None = None
