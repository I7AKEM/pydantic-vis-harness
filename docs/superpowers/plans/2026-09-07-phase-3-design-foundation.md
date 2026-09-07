# Phase 3 Design Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the chart spec language, the catalogue, the rules, `recommend_charts`, `check_spec`, data resolving, and the GPT-Vis renderer, with no model anywhere, so a person can hand-write a spec and get a correct picture.

**Architecture:** Two new packages. `vis_agent/designer/` holds the spec models, the strict parser and serializer, the catalogue as data, the rules, the two functions, and resolving. `vis_agent/render/` holds the renderer protocol, the GPT-Vis renderer's Python wrapper, and its Node folder (one script, one shared formatting file, one page template, a pinned package). The CLI gains `recommend`, `check`, `render`, and `doctor`. Tests mirror the packages; the recommendation evaluation set lives in `evals/designer/`.

**Tech Stack:** Python 3.12, Pydantic, DuckDB (unchanged), Node 22+, `@antv/gpt-vis-ssr` 0.3.8 pinned, G2 5.4.8 browser build from a CDN for the page.

**Spec:** `docs/superpowers/specs/2026-09-07-phase-3-design-foundation-design.md` (the design), which argues from `docs/superpowers/specs/2026-09-06-vis-agent-design.md` (the main design) and `docs/spikes/2026-09-07-gpt-vis-server-renderer.md` (the spike).

## Global Constraints

- Nothing in this phase calls a model. No agent, no `Agent(...)`, no rulebook.
- Python 3.12, uv, `uv run pytest -q` must stay green after every task. The suite is 108 tests at the start.
- Application code lives in `vis_agent`, one subpackage per agent or code step; tests and evals mirror it. Plain language names.
- Every number in a picture comes from the result's cells or from arithmetic on them in code (sums for Other, percent stacks, unit text). Nothing is guessed.
- Unknown spec keys, duplicate keys, tabs, wrong types, and unknown chart types are errors with a line number, never skipped.
- Values are typed by key, never by look: a category `001` or `1446` stays text.
- The spec never holds rows. Binding maps result columns to roles; code inserts cells.
- Rows never reach a model; the renderer receives the analyst's `QueryResult` rows, cells already capped at 120 characters by Phase 2.
- The renderer is one Node process per render with a 20 second timeout. No server, no port.
- `@antv/gpt-vis-ssr` is pinned to 0.3.8; `node_modules` is never committed; `package-lock.json` is.
- Tests that need Node or the installed package skip with a stated reason when either is missing.
- The lead, the app, the profiler, and the analyst are not modified. `vis_agent/cli.py` gains commands only.
- The catalogue's intent vocabulary is the existing `Intent` literal in `vis_agent/models.py`: compare, trend, rank, distribution, composition, relation, share.
- Commit messages carry no tool attribution and no `Co-Authored-By` trailer; the controller commits.

---

## File map

| File | Responsibility |
|---|---|
| `vis_agent/designer/__init__.py` | Package marker |
| `vis_agent/designer/models.py` | `Spec`, `NumberFormat`, `SpecIssue`, `SpecError`, `Compromise`, `RuleScore`, `Candidate`, `Rejection`, `Recommendation`, `Violation`, `SpecCheck` |
| `vis_agent/designer/syntax.py` | `parse`, `to_text`, `parse_format`, the key table |
| `vis_agent/designer/catalogue.json`, `catalogue.py` | Twenty entries; `CatalogueEntry`, `load_catalogue`, `CATALOGUE` |
| `vis_agent/designer/shape.py` | `ColumnShape`, `ResultShape`, `describe` |
| `vis_agent/designer/rules.py` | `Context`, `RuleResult`, hard, soft, and check rules |
| `vis_agent/designer/recommend.py` | `default_binding`, `recommend_charts` |
| `vis_agent/designer/check.py` | `check_spec` |
| `vis_agent/designer/resolve.py` | `Resolved`, `ResolveError`, `resolve` |
| `vis_agent/render/__init__.py` | Package marker |
| `vis_agent/render/base.py` | `Capability`, `Rendered`, `RendererUnavailable`, `RenderFailed`, `capability_for` |
| `vis_agent/render/gptvis.py` | `CAPABILITIES`, `available`, `render`, `smoke_test` |
| `vis_agent/render/gptvis/package.json`, `package-lock.json` | Pinned dependencies (installed by the controller before Task 6) |
| `vis_agent/render/gptvis/render.mjs` | The Node script |
| `vis_agent/render/gptvis/format.js` | The one number formatting function |
| `vis_agent/render/gptvis/page.html` | The page template |
| `vis_agent/render/gptvis/conformance.mjs` | Parses base specs with the original 1.0.1 parser for the conformance test |
| `vis_agent/cli.py` | `recommend`, `check`, `render`, `doctor` |
| `evals/designer/cases.json`, `decisions.json`, `run.py` | The recommendation evaluation set |
| `tests/designer/test_syntax.py`, `test_catalogue.py`, `test_rules.py`, `test_recommend.py`, `test_check.py`, `test_resolve.py`, `test_eval.py` | Per section 12 of the design |
| `tests/render/test_gptvis.py`, `test_conformance.py` | Renderer and conformance |
| `tests/test_cli.py` | The four commands |
| `README.md`, `AGENTS.md`, `docs/phase-3-lessons.md` | Docs; the lessons file is written by the controller at the end |

Shared test helpers: `tests/designer/conftest.py` builds `ResultColumn` lists and `QueryResult` tables for the shapes every test needs (a city count table, a monthly trend, a gender share, a scatter, raw amounts). Import them, do not rebuild them in each test file.

---

### Task 1: The spec models, the parser, the serializer, the format pattern

**Files:**
- Create: `vis_agent/designer/__init__.py`, `vis_agent/designer/models.py`, `vis_agent/designer/syntax.py`
- Test: `tests/designer/__init__.py`, `tests/designer/test_syntax.py`

**Interfaces:**
- Produces `Spec`, `NumberFormat`, `SpecIssue`, `SpecError`, `Compromise`, and the later models, in `models.py` exactly as below.
- Produces `parse(text: str) -> Spec`, `to_text(spec: Spec) -> str`, `parse_format(text: str) -> NumberFormat`, `KEYS` in `syntax.py`.

- [ ] **Step 1: Write the models**

`vis_agent/designer/models.py`:

```python
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
```

- [ ] **Step 2: Write the failing parser tests**

`tests/designer/test_syntax.py` must cover, with these exact expectations:

```python
import pytest

from vis_agent.designer.models import NumberFormat, Spec, SpecError
from vis_agent.designer.syntax import parse, parse_format, to_text

DONUT = """vis donut
title نسبة المواطنين الأثرياء حسب الجنس
description حلقة تُظهر نسبة الأثرياء لكل جنس
language ar
bind
  category الجنس
  value النسبة
sort value desc
"""


def test_parses_the_worked_example():
    spec = parse(DONUT)
    assert spec.type == "donut"
    assert spec.title == "نسبة المواطنين الأثرياء حسب الجنس"
    assert spec.language == "ar"
    assert spec.bind == {"category": "الجنس", "value": "النسبة"}
    assert spec.sort == "value desc"
    assert spec.inner_radius is None and spec.width is None


def test_colon_separator_and_values_with_spaces_and_colons():
    spec = parse("vis column\ntitle: Sales: quarterly report\naxisYTitle Amount (SAR)\n")
    assert spec.title == "Sales: quarterly report"
    assert spec.axis_y_title == "Amount (SAR)"


def test_values_are_typed_by_key_not_by_look():
    spec = parse("vis column\ntitle 2025\nwidth 1200\ninnerRadius 0.6\nlimit 10\nzero false\npercent true\n"
                 "bind\n  category 001\n  value n\n")
    assert spec.title == "2025" and spec.width == 1200 and spec.inner_radius == 0.6
    assert spec.limit == 10 and spec.zero is False and spec.percent is True
    assert spec.bind["category"] == "001"


def test_sections_and_lists():
    spec = parse("vis column\nemphasis\n  - جدة\n  - الرياض\npalette\n  - #1783FF\n  - #00C9C9\n"
                 "style\n  backgroundColor #FFFFFF\n  palette\n    - #FF0000\n")
    assert spec.emphasis == ["جدة", "الرياض"]
    assert spec.background_color == "#FFFFFF"
    # style.palette and the top-level palette are the same key; the last one written wins is NOT allowed:
    # writing both is a duplicate key error, so this test uses a separate parse for the style form.


def test_style_palette_is_the_palette():
    spec = parse("vis column\nstyle\n  palette\n    - #FF0000\n")
    assert spec.palette == ["#FF0000"]
    with pytest.raises(SpecError) as error:
        parse("vis column\npalette\n  - #FF0000\nstyle\n  palette\n    - #00FF00\n")
    assert "duplicate" in str(error.value)


@pytest.mark.parametrize("text, line, fragment", [
    ("title x\n", 1, "vis"),                                  # missing type line
    ("vis funnel\n", 1, "unknown chart type"),
    ("vis column\nbogus 1\n", 2, "unknown key"),
    ("vis column\ntitle a\ntitle b\n", 3, "duplicate"),
    ("vis column\n\ttitle a\n", 2, "tab"),
    ("vis column\nbind\n   category x\n", 3, "two spaces"),
    ("vis column\nwidth wide\n", 2, "integer"),
    ("vis column\ntheme neon\n", 2, "one of"),
    ("vis column\ntitle\n", 2, "missing value"),
    ("vis column\nbind x\n", 2, "section"),
    ("vis column\ntitle a\n  more\n", 3, "indent"),
    ("vis column\nbind\n  slice x\n", 3, "role"),
    ("vis column\nemphasis\n  جدة\n", 3, "- "),
    ("vis column\nformat 0..0\n", 2, "format"),
])
def test_errors_carry_line_numbers(text, line, fragment):
    with pytest.raises(SpecError) as error:
        parse(text)
    assert any(issue.line == line and fragment in issue.message for issue in error.value.issues), error.value.issues


def test_all_errors_are_reported_together():
    with pytest.raises(SpecError) as error:
        parse("vis column\nbogus 1\nwidth wide\n")
    assert [issue.line for issue in error.value.issues] == [2, 3]


def test_round_trip_is_canonical():
    text = to_text(parse(DONUT))
    assert text.startswith("vis donut\ntitle نسبة")
    assert parse(text) == parse(DONUT)
    assert to_text(parse(text)) == text
    assert "\n\n" not in text and not text.endswith("\n\n")


def test_serializer_writes_every_key_in_fixed_order():
    spec = Spec(type="line", title="t", bind={"time": "month", "value": "n"}, zero=False, axis_y_min=80,
                format="0,0 SAR", labels="off", palette=["#000000"], emphasis=["a"])
    text = to_text(spec)
    assert text.index("title t") < text.index("bind\n") < text.index("emphasis\n") < text.index("palette\n")
    assert text.index("zero false") < text.index("axisYMin 80") < text.index("labels off") < text.index("format 0,0 SAR")
    assert parse(text) == spec


@pytest.mark.parametrize("pattern, expected", [
    ("0", NumberFormat(thousands=False)),
    ("0,0", NumberFormat(thousands=True)),
    ("0.0", NumberFormat(thousands=False, decimals=1)),
    ("0,0.00 SAR", NumberFormat(thousands=True, decimals=2, unit="SAR")),
    ("0.0%", NumberFormat(thousands=False, decimals=1, unit="%")),
    ("0k", NumberFormat(thousands=False, compact=True)),
    ("0,0.0k ريال", NumberFormat(thousands=True, decimals=1, compact=True, unit="ريال")),
])
def test_format_patterns(pattern, expected):
    assert parse_format(pattern) == expected


@pytest.mark.parametrize("pattern", ["", "1,000", "0,", "0.", "%", "k", "0 ", "0,0,0"])
def test_bad_format_patterns(pattern):
    with pytest.raises(ValueError):
        parse_format(pattern)
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest tests/designer/test_syntax.py -q`
Expected: import errors.

- [ ] **Step 4: Implement `syntax.py`**

The key table drives everything. Write it as data at the top of the module:

```python
# key in the text -> (Spec field, kind). kind: text, int, number, bool, enum:<Literal name>, section:pairs, section:list
KEYS = {
    "title": ("title", "text"), "subtitle": ("subtitle", "text"), "description": ("description", "text"),
    "language": ("language", "enum:Language"), "theme": ("theme", "enum:Theme"),
    "width": ("width", "int"), "height": ("height", "int"),
    "axisXTitle": ("axis_x_title", "text"), "axisYTitle": ("axis_y_title", "text"),
    "innerRadius": ("inner_radius", "number"), "binNumber": ("bin_number", "int"),
    "bind": ("bind", "section:pairs"), "style": ("style", "section:pairs"),
    "sort": ("sort", "enum:SortOrder"), "limit": ("limit", "int"), "other": ("other", "text"), "unknown": ("unknown", "text"),
    "emphasis": ("emphasis", "section:list"), "palette": ("palette", "section:list"),
    "direction": ("direction", "enum:Direction"), "zero": ("zero", "bool"),
    "axisYMin": ("axis_y_min", "number"), "axisYMax": ("axis_y_max", "number"),
    "axisXMin": ("axis_x_min", "number"), "axisXMax": ("axis_x_max", "number"),
    "axisYScale": ("axis_y_scale", "enum:ScaleKind"), "percent": ("percent", "bool"),
    "labels": ("labels", "enum:Switch"), "legend": ("legend", "enum:Switch"),
    "format": ("format", "format"), "digits": ("digits", "enum:Digits"),
}
STYLE_KEYS = {"backgroundColor": ("background_color", "text"), "palette": ("palette", "section:list")}
```

Parsing algorithm, line by line with 1-based numbers, collecting `SpecIssue`s and raising `SpecError` at the end when any exist:

1. Split on newlines, drop trailing whitespace per line, ignore blank lines.
2. The first kept line must match `vis <type>` at indent 0; otherwise issue "first line must be `vis <type>`" and stop parsing (every later line would be noise). An unknown type: issue "unknown chart type 'funnel'" and stop.
3. Leading whitespace containing a tab: issue "tabs are not allowed; indent with two spaces". Indent must be 0, 2, or 4 (4 only under `style` for its `palette` list); otherwise issue "indentation must be two spaces per level".
4. Split a line into key and value: if it matches `^(\S+?):(?:\s+(.*))?$` the key is before the colon; otherwise the key is the first whitespace-separated token and the value the rest, stripped. A line beginning with `- ` at indent 2 or 4 is a list item.
5. Indent 0: the key must be in `KEYS`, else "unknown key 'bogus'". A key seen before: "duplicate key 'title'" (`palette` at top level and `style` `palette` count as the same key). A section key with a value on the line: "'bind' is a section; put its lines indented below it". A scalar key with no value: "missing value for 'title'". A scalar key followed by an indented line: the indented line gets "unexpected indent under 'title'".
6. Indent 2 under `bind`: `role column`; the role must be in `ROLES`, else "unknown role 'slice'; roles are category, value, group, time, x, y, value2"; duplicate roles are duplicates. Under `style`: key must be in `STYLE_KEYS`. Under `emphasis` or `palette`: every line must start with `- `, else "list items start with '- '"; the item is the rest, stripped, and may not be empty.
7. Typing: `int` must match `^-?\d+$` else "expects an integer"; `number` must parse as a float else "expects a number"; `bool` must be `true` or `false` else "expects true or false"; `enum:X` must be one of the Literal's values else "expects one of: a, b, c" (list them); `format` must pass `parse_format` else "format pattern is not valid: <reason>". Text keys keep the value as written.
8. Build the `Spec` with `Spec.model_validate`; a validation error at that point is a bug, not a user error.

`parse_format(text)`: match `^(0)(,0)?(?:\.(0+))?(k)?(%|\s+\S.*)?$` against the stripped text; group 2 present means thousands; group 3's length is the decimals; group 4 means compact; group 5 stripped is the unit (`%` stays `%`). Anything else raises `ValueError("expected a pattern like 0,0.00 SAR, 0.0%, or 0k")`.

`to_text(spec)`: emit `vis {type}` then keys in this order, omitting `None`, empty lists, and defaults (`language en`, `theme default`, `axisYScale linear`, `percent false`, `digits western` are omitted when at default): title, subtitle, description, language, theme, width, height, axisXTitle, axisYTitle, innerRadius, binNumber, bind (roles in `ROLES` order), sort, limit, other, unknown, emphasis, palette, style (only `backgroundColor`), direction, zero, axisYMin, axisYMax, axisXMin, axisXMax, axisYScale, percent, labels, legend, format, digits. Numbers: integers as integers; floats with `repr` after stripping a trailing `.0` for whole numbers (`80.0` becomes `80`, `0.6` stays). Booleans as `true`/`false`. The text ends with exactly one newline.

- [ ] **Step 5: Run the tests until green**

Run: `uv run pytest tests/designer/test_syntax.py -q`
Expected: all pass. Then `uv run pytest -q` for the whole suite.

- [ ] **Step 6: Report**

Print the files changed and the test count. Do not commit (the controller commits).

---

### Task 2: The catalogue

**Files:**
- Create: `vis_agent/designer/catalogue.json`, `vis_agent/designer/catalogue.py`
- Test: `tests/designer/test_catalogue.py`

**Interfaces:**
- Consumes `ChartType`, `Role` from `models.py`; `Intent` from `vis_agent/models.py`; the analyst's `ColumnKind` from `vis_agent/analyst/models.py`.
- Produces `CatalogueEntry`, `RoleSpec`, `Catalogue`, `load_catalogue() -> Catalogue`, and `CATALOGUE = load_catalogue()`.

- [ ] **Step 1: Write the failing tests**

```python
from vis_agent.designer.catalogue import CATALOGUE, load_catalogue
from vis_agent.designer.models import ChartType
from typing import get_args


def test_every_chart_type_has_one_entry_in_order():
    names = [entry.name for entry in CATALOGUE.entries]
    assert names == list(get_args(ChartType))


def test_entries_are_complete():
    for entry in CATALOGUE.entries:
        assert entry.purposes, entry.name
        assert entry.roles, entry.name
        assert any(role.required for role in entry.roles.values()), entry.name
        assert entry.draw.type, entry.name
        for role in entry.roles.values():
            assert role.kinds, (entry.name, role)
        for role in entry.fields:
            assert role in entry.roles, (entry.name, role)


def test_aliases_are_unique_and_resolve():
    seen = {}
    for entry in CATALOGUE.entries:
        for alias in [entry.name, *entry.aliases]:
            assert alias not in seen, (alias, seen.get(alias), entry.name)
            seen[alias] = entry.name
    assert CATALOGUE.find("doughnut").name == "donut"
    assert CATALOGUE.find("horizontal bar").name == "bar"
    assert CATALOGUE.find("nothing") is None


def test_ratings_and_whole_charts():
    assert CATALOGUE.get("pie").rating == "caution"
    assert CATALOGUE.get("table").rating == "fallback"
    assert CATALOGUE.get("pie").additive_value and CATALOGUE.get("stacked_column").additive_value
    assert not CATALOGUE.get("column").additive_value
    assert CATALOGUE.get("histogram").raw_values and CATALOGUE.get("boxplot").raw_values


def test_keys_per_entry():
    assert "innerRadius" in CATALOGUE.get("donut").keys and "innerRadius" not in CATALOGUE.get("pie").keys
    assert "percent" in CATALOGUE.get("stacked_bar").keys and "percent" not in CATALOGUE.get("grouped_bar").keys
    assert "axisYMin" in CATALOGUE.get("line").keys and "axisYMin" not in CATALOGUE.get("column").keys
    assert "axisYScale" in CATALOGUE.get("scatter").keys and "axisXMin" in CATALOGUE.get("scatter").keys
    assert "binNumber" in CATALOGUE.get("histogram").keys


def test_prompt_text_lists_every_entry():
    text = CATALOGUE.describe()
    for entry in CATALOGUE.entries:
        assert entry.name in text
```

- [ ] **Step 2: Write `catalogue.py`**

```python
class RoleSpec(BaseModel):
    kinds: list[ColumnKind]
    required: bool = False

class Draw(BaseModel):
    type: str                          # the GPT-Vis type: column, bar, line, area, pie, scatter, histogram, boxplot, treemap, radar, dual-axes, word-cloud, spreadsheet
    options: dict[str, Any] = {}       # e.g. {"group": true}, {"stack": true}, {"innerRadius": 0.6}

class CatalogueEntry(BaseModel):
    name: ChartType
    aliases: list[str] = []
    purposes: list[Intent]
    roles: dict[Role, RoleSpec]
    fields: dict[Role, str]            # role -> field name in the GPT-Vis record, e.g. {"category": "name"} for treemap
    rating: Literal["recommended", "caution", "fallback"]
    keys: list[str]                    # extension and base keys this entry accepts beyond the common ones
    category_min: int | None = None
    category_max: int | None = None
    group_max: int | None = None
    min_points: int | None = None      # for line/area: points on the time axis
    min_rows: int | None = None        # for histogram/boxplot: raw rows
    additive_value: bool = False
    raw_values: bool = False
    draw: Draw
    summary: str                       # one sentence for the prompt

class Catalogue(BaseModel):
    entries: list[CatalogueEntry]
    def get(self, name: str) -> CatalogueEntry
    def find(self, name_or_alias: str) -> CatalogueEntry | None   # case-insensitive, also matches name with spaces for underscores
    def describe(self) -> str          # one line per entry: name, purposes, roles, rating, summary
```

Common keys every entry accepts (not listed per entry): `title`, `subtitle`, `description`, `language`, `theme`, `width`, `height`, `bind`, `style`, `palette`, `emphasis`, `direction`, `labels`, `legend`, `format`, `digits`, `sort`, `limit`, `other`, `unknown`. Per-entry `keys` add: `axisXTitle`, `axisYTitle` on every axis chart (not pie, donut, treemap, word_cloud, radar, table); `innerRadius` on donut; `binNumber` on histogram; `percent` on stacked_column, stacked_bar, stacked_area; `zero`, `axisYMin`, `axisYMax` on line, multi_line, scatter, boxplot, dual_axes; `zero` also on area and stacked_area; `axisYScale` on line, multi_line, scatter; `axisXMin`, `axisXMax` on scatter.

- [ ] **Step 3: Write `catalogue.json`**

Twenty entries in `ChartType` order. Roles, limits, and purposes exactly from section 6 of the design, using this intent vocabulary: compare, trend, rank, distribution, composition, relation, share. Kinds: label means `["category", "ordinal", "geography"]`; measure means `["measure", "share"]`.

| name | roles | purposes | rating | limits | draw |
|---|---|---|---|---|---|
| column | category: label or time (required), value: measure (required) | compare, rank | recommended | category_max 50 | column |
| bar | category: label (required), value (required) | compare, rank | recommended | category_max 50 | bar |
| grouped_column | category, group: label (required), value | compare | recommended | category_max 50, group_max 10 | column {group: true} |
| stacked_column | same, additive_value | composition, compare | recommended | same | column {stack: true} |
| grouped_bar | as grouped_column | compare | recommended | same | bar {group: true} |
| stacked_bar | as stacked_column | composition, compare | recommended | same | bar {stack: true} |
| line | time: time or ordinal (required), value (required) | trend | recommended | min_points 3 | line |
| multi_line | time, group (required), value | trend, compare | recommended | min_points 3, group_max 10 | line |
| area | time, value, additive_value | trend | recommended | min_points 3 | area |
| stacked_area | time, group, value, additive_value | trend, composition | recommended | min_points 3, group_max 10 | area {stack: true} |
| pie | category: label (required), value, additive_value | share, composition | caution | category_min 2, category_max 6 | pie |
| donut | as pie | share, composition | caution | same | pie {innerRadius: 0.6} |
| scatter | x: measure (required), y: measure (required), group: label | relation | recommended | | scatter |
| histogram | value: measure (required), raw_values | distribution | recommended | min_rows 30 | histogram |
| boxplot | category: label (required), value (required), raw_values | distribution, compare | recommended | min_rows 30 | boxplot |
| treemap | category (required), value, additive_value | share, composition | recommended | category_max 50 | treemap, fields {category: name} |
| radar | category (required), value (required), group: label | compare | caution | category_min 3, category_max 12, group_max 5 | radar, fields {category: name} |
| dual_axes | category: label or time (required), value (required), value2: measure (required) | compare, trend | caution | category_max 50 | dual-axes |
| word_cloud | category: label (required), value (required) | rank | caution | category_min 20 | word-cloud, fields {category: text} |
| table | none required; every column is shown | compare, trend, rank, distribution, composition, relation, share | fallback | | spreadsheet |

Aliases: column (vertical bar, columns), bar (horizontal bar, bars), grouped_column (grouped bars, clustered column), stacked_column (stacked bars), line (line chart, trend line), multi_line (lines, multi-line), area (area chart), stacked_area (stacked areas), pie (pie chart), donut (doughnut, ring), scatter (scatter plot, points), histogram (distribution), boxplot (box plot, box and whisker), treemap (tree map), radar (spider), dual_axes (dual axis, two axes, combo), word_cloud (word cloud, tag cloud), table (spreadsheet, grid). Every summary is one plain sentence saying what the chart is for and what it needs.

- [ ] **Step 4: Run tests until green, then the whole suite**

---

### Task 3: The result shape, the rules, and `recommend_charts`

**Files:**
- Create: `vis_agent/designer/shape.py`, `vis_agent/designer/rules.py`, `vis_agent/designer/recommend.py`
- Test: `tests/designer/conftest.py`, `tests/designer/test_rules.py`, `tests/designer/test_recommend.py`

**Interfaces:**
- Consumes `ResultColumn`, `QueryResult` from `vis_agent/analyst/models.py`; `CATALOGUE`; the models.
- Produces:
  - `shape.py`: `ColumnShape(name, kind, unit, aggregate, source, distinct, longest_label, minimum, maximum, has_negative, is_numeric, nulls)`, `ResultShape(rows, columns, labels, measures, times, identifiers)` with `column(name)`, and `describe(columns, result) -> ResultShape`.
  - `rules.py`: `Context(intent: Intent | None = None, suggested: str | None = None)`, `RuleResult(rule, score, explanation, fix, hard=False)`, `HARD_RULES`, `SOFT_RULES` (lists of functions `(entry, shape, binding, context) -> RuleResult | None`), and `check_rules(entry, spec, shape, binding) -> list[Violation]` for C4 to C17 (C1, C2, C3 live in `check.py`).
  - `recommend.py`: `default_binding(entry, shape) -> dict[str, ColumnShape] | None`, `recommend_charts(columns, result, intent=None, suggested=None) -> Recommendation`.

- [ ] **Step 1: Write the shared fixtures**

`tests/designer/conftest.py` provides functions (not fixtures, so parametrize can use them) that return `(columns, result)`:

```python
def column(name, kind, source=None, aggregate="none", unit=None, denominator=None) -> ResultColumn
def table(columns: list[ResultColumn], rows: list[list], types=None) -> QueryResult   # sql="x", row_count=len(rows), seconds=0
def cities(n=5) -> (columns, result)           # city (category, source city) + violations (measure, count); n rows, values descending
def monthly(points=12) -> (columns, result)    # month (time, "2025-01"...) + visits (measure, sum)
def gender_share() -> (columns, result)        # gender (category, source gender), label (category, source gender), n (measure count), share (share, %, denominator "all")
def grouped(cities_n=5) -> (columns, result)   # city, gender (category, 2 values), n (measure sum): cities_n*2 rows
def scatter_points(n=40) -> (columns, result)  # age (measure none), amount (measure none)
def raw_amounts(n=60) -> (columns, result)     # amount (measure, aggregate none, unit SAR), n rows
def single_number() -> (columns, result)       # total (measure sum), one row
def two_units() -> (columns, result)           # month (time) + visits (measure, unit visits) + revenue (measure, unit SAR)
```

Every generated label is short ASCII unless a test asks for long labels, which it builds itself.

- [ ] **Step 2: Write `shape.py`**

`describe` computes per column from the rows: `distinct` (over non-null cells), `longest_label` (characters of the longest non-null cell as text; only meaningful for labels), `minimum`/`maximum` over numeric cells (int or float, not bool), `has_negative`, `is_numeric` (every non-null cell is int or float), `nulls`. `labels` are kinds category, ordinal, geography; `measures` are measure and share; `times` are time; `identifiers` are identifier. `rows` is `result.row_count`.

- [ ] **Step 3: Write the rule tests**

`tests/designer/test_rules.py` has one test per rule ID with a violating and a satisfying input, named `test_h1_shape`, `test_s4_count`, `test_c12_crop`, and so on, for H1 to H12, S1 to S13 (S12 is implicit: assert table is always a candidate with score 0 on an unusual shape), and C4 to C17. Use `recommend_charts` for hard and soft rules (assert the entry is in `rejected` with the rule ID, or find its `breakdown` entry and its score) and `check_rules` for the check rules with a `Spec` built directly. Exact expectations to encode, per the design:

- H5: `cities(7)` rejects pie and donut with rule `H5`; `cities(2)` passes them.
- H7: `monthly(2)` rejects line, multi_line, area with `H7`; `monthly(3)` passes.
- H9: `raw_amounts(29)` rejects histogram with `H9`; `raw_amounts(30)` passes; `cities()` (aggregate count) rejects histogram with `H9`.
- H10: `two_units()` passes dual_axes; the same with both units `SAR` rejects with `H10`.
- H11: `cities(51)` rejects column and bar with `H11`; `cities(50)` passes.
- H12: an empty table gives no candidates and one rejection with `H12` naming every entry? No: give `candidates == []` and `rejected == [Rejection(name="*", rule="H12", ...)]`.
- S4: `cities(12)` scores column `S4` at +1, `cities(15)` at 0, `cities(25)` at −2 with the fix text containing "Other".
- S5: labels of 20 characters score bar +1 and column −2.
- S6: `gender_share()` with values 50.4 and 49.6 scores pie `S6` at −2.
- S7: `monthly()` scores line +2 and bar −2 on `S7`.
- S9: `gender_share()` scores column 0 on `S9` for the code twin (label bound, gender unbound with the same source) and −1 for the unbound `n` when share is bound; state which column the default binding picks (value is the first measure in result order: `n`, so `share` is the unbound one).
- S13: `single_number()` puts table first with +2 and every chart at −3.
- C11: a line spec with `axis_y_min=200` on `monthly()` whose values are 100 to 245 gives `C11` "inside the range"; the same key on a column spec gives `C11` "only on".
- C12: `monthly()` values 100 to 245 with `zero=False` on line gives `C12` (245/2 = 122.5 > 100, not narrow); values 200 to 245 pass.
- C13: `percent=True` on stacked_column whose value aggregate is avg gives `C13`.
- C14: `axis_y_scale="log"` with values 1 to 50 gives `C14`; 1 to 1000 passes.
- C15: `labels="on"` with 60 rows gives `C15`.
- C16: `zero=True` with `axis_y_min=10` gives `C16`.
- C17 is tested in Task 1 through `parse_format`; here assert a spec whose `format` is `"0.0%"` on a value that is not a share yields a compromise, not a violation, by returning it from `check_rules` as a `Violation` with rule `C17` and `fix` starting with "warning:"? No. Keep it simple: `check_rules` returns only violations; C17's warning is produced in Task 5's resolve as a `Compromise`. Test that `check_rules` does not flag it.

- [ ] **Step 4: Write `rules.py`**

Each rule is a function returning `None` when it has nothing to say. Hard rules return `hard=True`. Soft rules return a score in −3..+3 with a one-sentence explanation ("12 categories fit a column"). Implement exactly:

- H1 shape: every required role in `entry.roles` is in `binding`.
- H2 time kept: when `shape.times` is non-empty and no time column is bound and the entry is not `table`: reject.
- H3 whole: `entry.additive_value` and the bound `value`'s aggregate not in (sum, count, count_distinct) and kind is not share: reject.
- H4 sign: entry in (pie, donut, treemap, stacked_column, stacked_bar, stacked_area) and the bound value has negatives: reject.
- H5 slices: entry has `category_min`/`category_max` and the bound category's `distinct` is outside them (word_cloud uses `category_min` 20 here too; radar 3..12).
- H6 colors: bound group's `distinct` > `entry.group_max`.
- H7 points: entry has `min_points` and the bound time's `distinct` < it.
- H8 order: entry binds `time` and the bound column's kind is not time or ordinal.
- H9 raw: `entry.raw_values` and (`shape.rows` < `entry.min_rows` or the bound value's aggregate != "none").
- H10 units: entry is dual_axes and the two bound values have the same unit (None equals None).
- H11 many: `entry.category_max` and the bound category's `distinct` > it (this is how column/bar 50 is enforced; pie's 6 is H5, so give H11 only to entries with `category_max` 50).
- H12 empty: `shape.rows == 0`: handled in `recommend_charts` before the loop.
- S1 intent: `context.intent in entry.purposes` → +3.
- S2 suggested: `CATALOGUE.find(context.suggested)` is this entry → +2.
- S3 caution: rating caution → −1.
- S4 count: column/bar/grouped/stacked variants by the bound category's distinct: ≤12 +1, ≤20 0, else −2 with fix "sort and keep the top N with Other".
- S5 long labels: category-bound entries when the bound category's `longest_label` > 15: bar and grouped_bar and stacked_bar +1; column and grouped_column and stacked_column −2 with fix "use a horizontal bar".
- S6 balance: pie/donut when every slice is within 10% of the largest: −2, fix "use a sorted bar".
- S7 time reads: bound time or category of kind time: line, multi_line, area, stacked_area +2; bar, grouped_bar, stacked_bar −2.
- S8 composition: stacked variants +1 when intent is composition; grouped variants +1 when intent is compare.
- S9 unbound: for each measure or share not in the binding −1; for each label not in the binding −1 unless it is an identifier or shares `source` with a bound label; table never loses here.
- S10 few points: scatter with rows < 10 → −2.
- S11 words: word_cloud with the bound category's distinct < 20 → −3 (H5 already rejects; keep S11 for the case `category_min` is removed later; implement it anyway, it is two lines).
- S13 one number: rows == 1 and exactly one measure: table +2, others −3.

`check_rules(entry, spec, shape, binding)` implements C4 to C17 from section 7.3 of the design with the fixes given there. C12's "narrow" test: `minimum > 0.5 * maximum` with both positive. C14: every value positive and `maximum >= 100 * minimum`. C15: marks = rows for single-series charts, rows for grouped. C17: nothing (see Step 3).

- [ ] **Step 5: Write `recommend.py`**

`default_binding(entry, shape)`: labels sorted by distinct descending for `category` (largest first), ascending for `group` (smallest first, and not the same column as category); `time` takes the first time column, or the first ordinal when no time exists; for column, bar, and dual_axes `category` may also take a time column when no label exists; `x` and `y` take measures in result order; `value` takes the first measure or share not used by `x`/`y`, preferring a share for pie, donut, and treemap when one exists; `value2` takes the next measure. Returns `None` when a required role cannot be filled. `table` binds nothing and shows every column.

`recommend_charts`: `shape = describe(columns, result)`; empty → the H12 outcome; for each entry in catalogue order: binding (None → `Rejection(name, "H1", ...)`), then hard rules in order (first failure rejects), then soft rules (collect `RuleScore`s, sum), producing a `Candidate` with `binding` as role → column name. Sort candidates by score descending, stable, so catalogue order breaks ties.

- [ ] **Step 6: Recommend tests**

`tests/designer/test_recommend.py`: `cities()` → top is column (S1 without intent is 0, S4 +1, table 0); with `intent="rank"` column and bar both get +3 and column stays first; `monthly()` → line first; `gender_share()` with `intent="share"` → donut or pie first (S3 −1 each, S1 +3, table 0, bar 0 with S9 −1) and assert `donut` precedes `pie` only by catalogue order (pie comes first in the type list, so assert pie first and donut second); `two_units()` → dual_axes passes and line is present; `single_number()` → table first; the candidate's `binding` for `cities()` column is `{"category": "city", "value": "violations"}`; every candidate carries a breakdown with rule IDs; rejected entries carry the failing rule.

- [ ] **Step 7: Run the tests and the whole suite until green**

---

### Task 4: `check_spec` and the capability tables

**Files:**
- Create: `vis_agent/render/__init__.py`, `vis_agent/render/base.py`, `vis_agent/designer/check.py`
- Test: `tests/designer/test_check.py`

**Interfaces:**
- `base.py`:

```python
class Capability(BaseModel):
    honoured: set[str]
    degraded: dict[str, str]      # key -> what the renderer does instead
    rejected: dict[str, str]      # key -> why

class Rendered(BaseModel):
    png: Path; html: Path; config: Path
    width: int; height: int; seconds: float
    non_background_share: float
    compromises: list[Compromise]
    drawn_rows: int; folded_rows: int; dropped_rows: int

class RendererUnavailable(Exception): ...
class RenderFailed(Exception): ...

RENDERERS: dict[str, Callable[[ChartType], Capability]] = {}   # filled by gptvis.py at import; check.py imports vis_agent.render.gptvis to register
def capability_for(renderer: str, chart_type: ChartType) -> Capability
```

- `check.py`: `check_spec(text, columns, result, renderer="gptvis") -> SpecCheck`.

- [ ] **Step 1: Write the failing tests**

- A passing donut spec on `gender_share()` (bind category label, value share): `ok`, no violations, `canonical` equals `to_text(parse(text))`, and compromises contain one about the legend (from `direction`, since language ar defaults to rtl) — assert `any("legend" in c.message for c in check.compromises)`.
- A spec with three problems at once (unknown key, a bind to a column that does not exist, `innerRadius` on a column) reports three violations with rules `syntax`, `C2`, `C3` in that order, `ok` False, `canonical` None.
- Parse errors: `check_spec("title x\n", ...)` gives one violation with rule `syntax`, line 1.
- `C1`: a renderer that lacks the type. Register a fake renderer in the test through `RENDERERS["fake"]` returning `Capability(honoured=set(), degraded={}, rejected={"*": "not drawn"})` and assert rule `C1`.
- `C2` also fires when a required role is missing (`bind` without value).
- C10: a pie spec on `cities(7)` gives `C10` with the hard rule's explanation mentioning `H5`.
- Rejected keys become violations with rule `renderer`; degraded keys become compromises.

- [ ] **Step 2: Write `check.py`**

Order: parse (issues → violations rule `syntax` with lines) and stop; entry = `CATALOGUE.get(spec.type)`; C1 through `capability_for` (a `rejected` entry keyed `"*"` means the type is not drawn); C2 (every bound column exists in `columns`, kind allowed by the role, every required role bound); C3 (every key present in the spec is a common key or in `entry.keys`; compute "present" as fields that differ from their defaults); then `shape = describe(columns, result)`, `binding` from `spec.bind` resolved to `ColumnShape`s; C10 = hard rules on this entry with this binding; then `check_rules` (C4 to C17); then the capability table: keys present and in `rejected` → violation rule `renderer`; in `degraded` → compromise. `direction` counts as present when the spec sets it or when language ar makes it rtl by default. `ok` is true when there are no violations; `canonical` then holds `to_text(spec)`.

- [ ] **Step 3: Write `base.py` and the registration hook**

`vis_agent/render/gptvis.py` does not exist until Task 6. For this task, create `base.py` with the registry, and in `check.py` import `vis_agent.render.base` only; `capability_for` raises `KeyError` with a clear message when the renderer is unknown. Register a temporary `gptvis` capability in `base.py` itself: `GPTVIS_HONOURED` (every key in `KEYS` and `STYLE_KEYS` plus `bind`), `GPTVIS_DEGRADED = {"direction": "the legend stays where the package puts it; the title and the category order follow the direction"}`, and for `table`: degraded `subtitle`, `labels`, `legend`, `axisXTitle`, `axisYTitle`, `direction`, `format` with the message "tables are drawn as the package draws them". Task 6 moves this table into `gptvis.py` unchanged.

- [ ] **Step 4: Run the tests and the whole suite until green**

---

### Task 5: Resolving a spec against a result

**Files:**
- Create: `vis_agent/designer/resolve.py`
- Test: `tests/designer/test_resolve.py`

**Interfaces:**
- `Resolved(config: dict, overrides: dict, number: NumberFormat, compromises: list[Compromise], drawn_rows: int, folded_rows: int, dropped_rows: int, width: int, height: int)`
- `ResolveError(Exception)`
- `resolve(spec, columns, result) -> Resolved`

`config` is the GPT-Vis options object the Node script hands to the package: `type` (the entry's `draw.type`), the `draw.options`, `data`, `title`, `theme`, `width`, `height`, `axisXTitle`, `axisYTitle`, `innerRadius`, `binNumber`, `style` with `palette`, `backgroundColor`, and `startAtZero`. `overrides` is a partial G2 options object merged by the script: `scale.y.domainMin/domainMax/nice/type`, `scale.x.domainMin/domainMax` (scatter) or `scale.x.domain` (category order for rtl), `title.align`, `title.subtitle`, `labels` (`[]` for off), `legend` (`false` for off). `number` is the `NumberFormat` (unit filled).

- [ ] **Step 1: Write the failing tests**

- Bind and shape: `cities()` with a column spec → `config["data"] == [{"category": "Riyadh", "value": 1240}, ...]`, `config["type"] == "column"`, `width == 800`, `height == 450`.
- Treemap renames: `config["data"][0]` has `name` and `value`.
- Grouped: `config["group"] is True` and records carry `group`.
- Histogram: `config["data"]` is a list of numbers.
- Dual axes: `config["categories"]` and two `series` with `axisYTitle` set to each column's unit.
- Table: `config["type"] == "spreadsheet"`, `config["columns"]` are the result's column names, `config["data"]` is a list of dicts.
- Text in a measure column raises `ResolveError` mentioning the column.
- Nulls: a null value drops the row (`dropped_rows == 1`, a compromise saying so); a null category becomes `unknown` or the language default (`غير معروف` for ar).
- Sort: default `value desc` for a category axis, `none` for time and ordinal; `category asc` sorts by label text.
- Limit: `cities(8)` with `limit 5` → 6 records, the last labelled `Other` (or `أخرى` for ar) with the sum of the folded three, `folded_rows == 3`; for `grouped(8)` the Other row exists per group.
- Percent: `grouped()` on stacked_column with `percent true` → each city's values sum to 100 (within 1e-9), `config["axisYTitle"] == "%"` unless the spec gives one, `number.unit == "%"`.
- Emphasis: `emphasis` [Jeddah] → `config["style"]["palette"]` has the accent `#1783FF` at Jeddah's position after sorting and `#C9CDD4` elsewhere (dark theme: `#4E5969`).
- Palette given: passed through unchanged.
- Direction: language ar without `direction` → `overrides["scale"]["x"]["domain"]` is the reversed category list and `overrides["title"]["align"] == "right"`; `direction ltr` on ar → no reversal; a line chart never reverses.
- Numbers: with no `format`, `number == NumberFormat(unit=<bound value column's unit>)`; `format 0.0%` → `number.unit == "%"`, decimals 1; `digits arabic` → `number.digits == "arabic"`; `format 0.0%` on a non-share value adds a compromise with key `format`.
- Ranges and scale: `axisYMin 80`, `axisYMax 300` → `overrides["scale"]["y"] == {"domainMin": 80, "domainMax": 300, "nice": False}`; `axisYScale log` → `overrides["scale"]["y"]["type"] == "log"`; `zero false` on line → `config["style"]["startAtZero"] is False`; default on line → True.
- Switches: `labels off` → `overrides["labels"] == []`; `legend off` → `overrides["legend"] is False`; `subtitle` → `overrides["title"]["subtitle"]`.
- Width default: `monthly(24)` on a line → `width == 1200`; `width 900` written → 900.

- [ ] **Step 2: Write `resolve.py`**

Follow section 9 of the design step by step. Details:

- `LANGUAGE_DEFAULTS = {"ar": {"other": "أخرى", "unknown": "غير معروف", "direction": "rtl"}, "en": {"other": "Other", "unknown": "Unknown", "direction": "ltr"}}`.
- Records are built from `spec.bind` through the entry's `fields` renaming. Measures: `int`/`float` and not `bool`; a `str` cell in a measure raises `ResolveError(f"column {name!r} holds text in row {i}; a measure must be numeric")`. A `None` in any bound value drops the row; a `None` in a bound label becomes the unknown label.
- Sorting acts on records before limit; `value desc` sorts by the `value` field; `category asc` by the label's text; for grouped entries the sort key is the category's total.
- Limit folds records beyond `limit` distinct categories (not rows) into one `other` category, summing values per group.
- Percent divides each record's value by its category's total and multiplies by 100; a zero total leaves the values at 0 with a compromise.
- Palette: `spec.palette` if given, else emphasis colors when `spec.emphasis`, else nothing (the package's default). Emphasis on grouped entries colors group values; on single-series entries it colors categories.
- Direction rtl reverses the category order through `overrides.scale.x.domain` (the category values after sorting and folding) for column, bar, grouped and stacked variants; sets `overrides.title.align = "right"`; adds `Compromise("direction", "the legend stays where the package puts it")`.
- `number`: `parse_format(spec.format)` when given, else `NumberFormat()`; when its `unit` is `None`, take the bound value column's `unit` (for `x`/`y` scatter use `y`); `digits` from the spec. A `%` unit from `format` on a value whose kind is not share adds `Compromise("format", "a percent sign on a value that is not a share")`.
- Width and height: the spec's, else 800 by 450, else 1200 by 450 for line, multi_line, area, stacked_area with more than 12 points.
- `startAtZero`: `spec.zero` if set, else True for line, multi_line, area, stacked_area, boxplot, dual_axes.
- `overrides.scale.y`: from `axis_y_min`/`axis_y_max` (with `nice: False` when either is set) and `type: "log"`; `overrides.scale.x` for scatter ranges.
- `labels off` → `overrides.labels = []`; `legend off` → `overrides.legend = False`; `subtitle` → `overrides.title.subtitle`.
- The table entry: `config = {"type": "spreadsheet", "data": [dict(zip(result.columns, row)) ...], "columns": result.columns, "width", "height"}`; no sort, limit, or percent.

- [ ] **Step 3: Run the tests and the whole suite until green**

---

### Task 6: The GPT-Vis renderer

**Files:**
- Create: `vis_agent/render/gptvis/render.mjs`, `vis_agent/render/gptvis/format.js`, `vis_agent/render/gptvis/page.html`, `vis_agent/render/gptvis/conformance.mjs`, `vis_agent/render/gptvis.py`
- Already present (installed by the controller, do not edit): `vis_agent/render/gptvis/package.json`, `package-lock.json`, `node_modules/`
- Modify: `vis_agent/render/base.py` (move the gptvis capability table out into `gptvis.py`; `base.py` keeps the registry and models), `.gitignore` if `node_modules/` is not already ignored (it is; verify)
- Test: `tests/render/__init__.py`, `tests/render/test_gptvis.py`, `tests/render/test_conformance.py`

**Interfaces:**
- `gptvis.py`: `SCRIPT`, `NODE_TIMEOUT_SECONDS = 20`, `available() -> str | None` (None when usable; otherwise the reason and the install command `npm ci --prefix vis_agent/render/gptvis`), `render(spec, columns, result, out_dir: Path, *, trace: bool = False) -> Rendered` (adds `texts: list[str]` to `Rendered` when `trace`; add the optional field to `Rendered` in `base.py`), `smoke_test() -> str | None`, `capability(chart_type) -> Capability` registered in `RENDERERS["gptvis"]` at import.
- The script's contract, stdin JSON: `{"config": {...}, "overrides": {...}, "format": {thousands, decimals, compact, unit, digits}, "output": "/abs/chart.png", "trace": false}`. Stdout JSON on success: `{"renderMs", "width", "height", "bytes", "nonBackgroundShare", "g2": <captured G2 options, JSON-safe>, "functionPaths": [...], "texts": [...]}`. Stderr JSON on failure `{"error": "..."}` and exit code 1.

- [ ] **Step 1: Write `format.js`**

One exported function usable from Node (ES module) and inlinable in the page:

```js
// Builds a formatter from a number description. Shared by render.mjs and page.html.
export function makeFormatter(desc) {
  const { thousands = true, decimals = null, compact = false, unit = null, digits = 'western' } = desc || {};
  const arabic = ['٠','١','٢','٣','٤','٥','٦','٧','٨','٩'];
  const toDigits = s => digits === 'arabic'
    ? s.replace(/[0-9]/g, d => arabic[+d]).replace(/,/g, '٬').replace(/\./g, '٫') : s;
  return value => {
    if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return String(value ?? '');
    let n = Number(value), suffix = '';
    if (compact && Math.abs(n) >= 1000) {
      const units = [['B', 1e9], ['M', 1e6], ['K', 1e3]];
      for (const [label, size] of units) if (Math.abs(n) >= size) { n = n / size; suffix = label; break; }
    }
    let text = decimals === null
      ? (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, ''))
      : n.toFixed(decimals);
    if (thousands) { const [i, f] = text.split('.'); text = i.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (f ? '.' + f : ''); }
    text += suffix;
    if (unit) text += unit === '%' ? '%' : ' ' + unit;
    return toDigits(text);
  };
}
```

The compact form uses one decimal at most when `decimals` is null (1234 → 1.23K is wrong; make it 1.2K: when `compact` applied and `decimals === null`, use `toFixed(1)` trimmed).

- [ ] **Step 2: Write `render.mjs`**

Under 120 lines. Behaviour:

1. Read all of stdin, parse JSON. Install `require.extensions['.css'] = () => {}` through `createRequire`. Require `@antv/g2-ssr` and `@antv/gpt-vis-ssr` (CJS entries) from the script's own folder.
2. Wrap `g2.createChart`: `const original = g2.createChart; g2.createChart = async (options) => { const merged = deepMerge(options, overrides); applyFormat(merged, config.type, formatter); captured = toJsonSafe(merged); return original(merged); }`. `deepMerge` merges plain objects recursively; arrays and scalars from `overrides` replace; `undefined` is skipped. `applyFormat` sets `merged.axis.y.labelFormatter = formatter` when `merged.axis?.y` exists (bar is transposed; its values are still on `y`), sets `formatter` on every entry of `merged.labels` whose `text` is `"value"`, and for pie (`merged.coordinate?.type === "theta"`) replaces `merged.labels[0].text` with `d => \`${d.category}: ${formatter(d.value)}\``; it records the paths it set in `formatPaths`. `toJsonSafe` walks the object and replaces functions with `{"$function": "<path>"}` markers, collecting `functionPaths`; our formatter functions are replaced with `{"$format": "value"}` and the pie label with `{"$label": "category_value"}` so the page can rebuild them (keep a `WeakSet` of the functions we made to tell ours from the package's).
3. When `trace`, patch `CanvasRenderingContext2D.prototype.fillText` from `canvas` to collect the strings drawn.
4. `const vis = await render(config); const buffer = vis.toBuffer(); vis.destroy();` then write `output`.
5. Non-background share: `loadImage(buffer)` from `canvas`, draw on a new canvas, `getImageData`, take the top-left pixel as background, count pixels (every fourth in each direction) whose RGB differs by more than 8 in any channel, divide.
6. Print the JSON line. Any thrown error: `console.error(JSON.stringify({error: String(e.message || e)}))`, exit 1.

- [ ] **Step 3: Write `page.html`**

A template with `{{...}}` placeholders replaced by the Python wrapper with `str.replace` (no template engine; escape `</script>` in JSON as `<\/script>`): `{{lang}}`, `{{dir}}`, `{{title}}`, `{{description}}`, `{{png}}` (base64), `{{width}}`, `{{height}}`, `{{g2}}` (the captured options JSON), `{{format}}` (the number description JSON), `{{format_js}}` (the contents of `format.js` with the `export ` keyword stripped), `{{interactive}}` (`true` when `functionPaths` is empty and the type is not spreadsheet), `{{table}}` (an HTML table for the table entry, empty otherwise). Structure: a heading with the title, the `<img>` with the description as `alt`, a `<div id="chart">` hidden until drawn, the table when given, and a script that runs only when interactive: loads `https://cdn.jsdelivr.net/npm/@antv/g2@5.4.8/dist/g2.min.js` by injecting a script tag; on load, revives `{"$format": ...}` markers with `makeFormatter(format)` and `{"$label": "category_value"}` with the pie label function, then `const chart = new G2.Chart({container: 'chart', autoFit: false, width, height}); chart.options(g2); chart.render().then(() => { img.hidden = true; div.hidden = false; })`. On any failure the image stays.

- [ ] **Step 4: Write `gptvis.py`**

- `available()`: `shutil.which("node")` else "Node is not installed; install Node 22 or later"; `SCRIPT.parent / "node_modules" / "@antv" / "gptvis-ssr"` missing → the reason plus `npm ci --prefix vis_agent/render/gptvis`.
- `render(...)`: `resolved = resolve(spec, columns, result)`; `out_dir.mkdir(parents=True, exist_ok=True)`; `subprocess.run(["node", str(SCRIPT)], input=json, capture_output=True, timeout=NODE_TIMEOUT_SECONDS)`; a timeout raises `RenderFailed("render timed out after 20 s")`; a non-zero exit raises `RenderFailed(stderr's error)`; parse stdout; write `config.json` with `{"gptvis": resolved.config, "overrides": resolved.overrides, "number": ..., "g2": stdout["g2"], "functionPaths": ...}`; write `chart.html` from the template; return `Rendered` with compromises = `resolved.compromises` plus one `Compromise("page", "the page shows the picture, not an interactive chart, because the package's configuration holds functions")` when `functionPaths` is non-empty.
- `smoke_test()`: renders a fixed Arabic column spec (the spike's `column-ar` data, five cities) into a temporary directory and returns `None` when `non_background_share >= 0.02` and, with `trace`, the text `الرياض` was drawn; otherwise the reason ("fonts: Arabic text did not render" or "renderer unavailable: ...").
- Move the capability table from `base.py` here; `base.py` keeps `RENDERERS` and `capability_for`; `check.py` imports `vis_agent.render.gptvis` for registration (a plain `import vis_agent.render.gptvis  # noqa: F401` at module top).

- [ ] **Step 5: Write `conformance.mjs`**

Reads spec text on stdin, imports `parse` from `./node_modules/@antv/gpt-vis/dist/esm/syntax/parser.js`, prints the parsed JSON. The dev dependency `@antv/gpt-vis@1.0.1` is in `package.json` already.

- [ ] **Step 6: Write the tests**

`tests/render/test_gptvis.py`, all under `pytestmark = pytest.mark.skipif(available() is not None, reason=available() or "")`:

- Every catalogue entry renders: parametrize over `CATALOGUE.entries` with a hand-written spec text per entry (a dict in the test module: entry name → spec text, plus which conftest shape it uses), write into `tmp_path`, assert `png.exists()`, `width == 3 * spec width` (for charts; the table's size is what the package makes it, assert > 0), `non_background_share >= 0.02`, `config.exists()`, `html.exists()` and contains the title. Also copy each PNG to `tests/render/images/<entry>.png` when the environment variable `VIS_KEEP_IMAGES` is set (for the humans; the folder is git-ignored except a `README.md` saying so).
- The Arabic column with `trace=True`: `"الرياض" in rendered.texts` and `"1,240" in rendered.texts`.
- Formats through the text list: `format 0.0%` on a share → `"61.6%"` drawn; `format 0,0 ريال` on `cities()` → `"1,240 ريال"`; `format 0k` on values above 1000 → `"1.2K"`; `digits arabic` → `"١٬٢٤٠"`.
- Overrides reach the library: `axisYMin 80` on the monthly line → `config.json`'s `g2.scale.y.domainMin == 80`; `labels off` → `g2.labels == []`; `legend off` → `g2.legend is False`; rtl → `g2.title.align == "right"` and `g2.scale.x.domain` reversed.
- A timeout: monkeypatch `NODE_TIMEOUT_SECONDS` to 0.001 and assert `RenderFailed` mentions "timed out".
- A missing package: monkeypatch `SCRIPT` to a path whose folder has no `node_modules` and assert `available()` names `npm ci`.
- `smoke_test()` returns `None`.

`tests/render/test_conformance.py`: for five base-vocabulary specs (column with title and axis titles, line with theme dark, donut with innerRadius, column with style backgroundColor and palette, bar with width and height), run `conformance.mjs` through `subprocess`, load the JSON, and assert it equals our parser's view mapped to the GPT-Vis JSON keys (`type`, `title`, `axisXTitle`, `axisYTitle`, `theme`, `width`, `height`, `innerRadius`, `style.backgroundColor`, `style.palette`). Values in these specs avoid text that looks like a number. Skip with the same reason as the renderer tests.

- [ ] **Step 7: Run the tests and the whole suite until green**

Run: `uv run pytest tests/render -q` then `uv run pytest -q`.

---

### Task 7: The terminal commands and the documents

**Files:**
- Modify: `vis_agent/cli.py`, `README.md`, `AGENTS.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- `vis recommend REPORT.json [--intent INTENT] [--suggested NAME]`: loads the report as `AnalysisReport`, needs `analysis.columns` and `result`; prints JSON of the `Recommendation`.
- `vis check SPEC [--report REPORT.json] [--renderer gptvis]`: prints JSON of the `SpecCheck`; without a report only the parse runs and every other rule is skipped (say so in a `note` field).
- `vis render SPEC --report REPORT.json [--out DIR] [--renderer gptvis]`: runs `check_spec` first and refuses with the violations as JSON and exit code 2 when not ok; otherwise renders and prints JSON with the three paths, the compromises, the size, and the seconds. The default `--out` is `<data directory>/renders/<12 hex chars of sha256(spec text + report bytes)>`, where the data directory is `resources()[2].directory`.
- `vis doctor`: prints Node's version, `available()`, and `smoke_test()`, one line each; exit code 1 when the renderer is unavailable or the smoke test fails.

- [ ] **Step 1: Tests**

Extend `tests/test_cli.py` in the style of the existing tests: `recommend` on a report file written from `gender_share()` (build an `AnalysisReport` with `Analysis(sql="x", columns=..., summary="s")` and the result) prints candidates; `check` on a bad spec exits 0 and prints violations; `render` refuses a failing spec with exit code 2; `render` with the renderer available writes the three files (skip otherwise); `doctor` runs (skip its exit code assertion when the renderer is unavailable).

- [ ] **Step 2: Implement**

Keep `cli.py` readable: one function per command, `build_parser` grows four subparsers, `main` dispatches. Load reports with `AnalysisReport.model_validate_json`. A report with a clarification and no analysis: print an error and exit 2.

- [ ] **Step 3: Documents**

`README.md`: a section "Render a chart" after "Ask a question" showing the three commands end to end with the donut spec from the design, the Node install (`npm ci --prefix vis_agent/render/gptvis`), the Debian packages (`libexpat1 fontconfig fonts-noto-core`), and `vis doctor`. A section "How charts are chosen and checked" after "How answering works": the catalogue, the rules with their IDs, the check, the compromises, the page. Add the new files to the code table. `AGENTS.md`: a Phase 3 line pointing at the design, the rule that `vis_agent/designer/` holds the designer's tools and `vis_agent/render/` the renderers, the Node requirement, "the renderer package is pinned; never edit node_modules", and add `evals/designer/run.py` to the evals-before-merge rule.

- [ ] **Step 4: Run the whole suite until green**

---

### Task 8: The recommendation evaluation set

**Files:**
- Create: `evals/designer/__init__.py`, `evals/designer/cases.json`, `evals/designer/decisions.json`, `evals/designer/run.py`
- Test: `tests/designer/test_eval.py`

**Interfaces:**
- A case: `{"name", "columns": [ResultColumn as JSON], "rows": [[...]], "intent": Intent | null, "suggested": str | null, "expected": [acceptable top names, the first is the expected one], "why": "..."}`. Rows may be generated: `"generate": {"categories": 25, "values": "descending"}` is not allowed; write the rows out, at most 60 per case, or use `"rows_from": {"repeat": [[...]], "times": 5}` for raw-value cases (histogram, boxplot need 30 rows).
- `run.py`: `uv run python -m evals.designer.run [--cases cases.json]` prints one line per failing case with the top three candidates and their breakdowns, then `score: passed/total` and exits 0.
- `evaluate(cases) -> (score: float, failures: list[dict])` importable by the test.

- [ ] **Step 1: Write at least thirty cases**

Every catalogue entry is the expected top at least once. Draw shapes from the analyst's expected tables in `evals/analyst/cases/expected.json` and `cases.json` (read them for real column names, cardinalities, and Arabic labels), assigning kinds by hand. Include the fallbacks: a one-number result (table), an empty result (no candidates; `expected: []`), fifty-one categories (table or bar after H11 rejects column? No: H11 rejects both; expected table), seven slices with intent share (bar; pie rejected), two time points with intent trend (bar or column), raw values (histogram), two units (dual_axes with `suggested: "dual axis"`; and without the suggestion expect multi_line? No: multi_line needs a group. Expect `["line", "dual_axes"]`), long Arabic labels (bar), a share table with intent share (pie first, donut acceptable), a grouped table with intent composition (stacked_column), with intent compare (grouped_column), twenty-five words with intent rank (word_cloud acceptable, bar expected), forty scatter points with intent relation (scatter), and monthly trends of 3, 12, and 24 points (line).

`decisions.json` records why each ambiguous case expects what it expects, in the style of the analyst's.

- [ ] **Step 2: Write `run.py` and the test**

`tests/designer/test_eval.py`: loads the cases, runs `evaluate`, asserts `score >= 0.9` and prints the failures on failure. The controller tunes rule scores against this set if needed; report any case you could not make pass and why, rather than changing the expected answer.

- [ ] **Step 3: Run the whole suite until green**

---

## Self-review notes

- Spec coverage: sections 5 (Task 1), 6 (Task 2), 7 and 8 (Tasks 3 and 4), 9 (Task 5), 10 (Task 6), 11 (Task 7), 12 (tests in every task), 13 (Task 8), 14 (file map), 15 (constraints). The lessons file (section 16) is written by the controller after the evaluation.
- The design's startup smoke test lives in `vis doctor` and `smoke_test()`; the app is not modified in this phase, so the check runs on demand until Phase 4 wires rendering into the lead.
- Type names are consistent: `Spec`, `NumberFormat`, `Compromise`, `Recommendation`, `SpecCheck`, `Resolved`, `Rendered`, `Capability`; functions `parse`, `to_text`, `parse_format`, `describe`, `default_binding`, `recommend_charts`, `check_spec`, `check_rules`, `resolve`, `render`, `available`, `smoke_test`, `capability_for`.
