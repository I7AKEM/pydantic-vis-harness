# Fold, clearer diagnostics, and one analyst revision: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A result with two or more measures of one unit side by side draws as one series per measure without any model call; validation messages say what is missing in plain words; a spent budget is a technical failure, never a question to the caller; and the designer can ask the analyst once, inside one request, for a different result table.

**Architecture:** Three small changes to the existing agents, in this order. (1) A `fold` key in the spec grammar, applied in code by the recommender, the checker, and the resolver (the Vega-Lite fold transform, Tableau's Measure Names). (2) Rule messages that name the expected roles, the actual columns, and only verified alternatives; the two dead-end paths raise `UnexpectedModelBehavior` with the diagnostics instead of returning a `Clarification`. (3) A third designer output, `request_analysis_revision`, which the request runner turns into one extra analyst run with the designer's feedback, then one more designer run with the analyst's reply; the runner enforces the single revision and saves the decision before the analyst runs.

**Tech Stack:** Python 3.12, Pydantic 2.13, Pydantic AI 2.38 (`Agent`, `ToolOutput`, `ModelRetry`, `UnexpectedModelBehavior`, `FunctionModel` in tests), DuckDB, the GPT-Vis Node renderer.

**Spec:** `docs/superpowers/plans/2026-09-09-analyst-designer-repair.md` (the analysis of the incident and the communication contract; this plan implements it with the fold added and the persistence kept to one field and one saved step).

## Global Constraints

- Keep code small, explicit, and readable; no new abstraction beyond what a task names. No workflow engine, no planner, no new agent.
- Every budget is enforced by the framework or by the runner's code, never by a message the model may ignore.
- Tests use fake models through `agent.override` (`FunctionModel`, `TestModel`) and never hand-build `RunContext`.
- No branch for one dataset, one column name, or one chart pair. The incident becomes an evaluation case, not code.
- The analyst's and designer's rulebooks stay short: add at most the lines each task names.
- Commit messages describe the change in the imperative, as the repository owner writes them. Never mention Claude, Codex, or any AI tool in a commit message, and never add a `Co-Authored-By` trailer.
- Run `uv run --no-sync pytest -q` and `uv run --no-sync python -m evals.designer.run` before every commit; both must pass. Model-backed evals need the network and are run by the controller in Task 4.
- Stage files by name (`git add path ...`); never `git add -A` or `git add .` in this worktree (it holds symlinks that must not be tracked).

---

### Task 1: Fold measure columns into series, in code

**Files:**
- Create: `vis_agent/designer/fold.py`
- Modify: `vis_agent/designer/catalogue.json` (keys and category kinds), `vis_agent/designer/models.py` (`Spec.fold`, `Candidate.fold`), `vis_agent/designer/syntax.py` (`KEYS`, `parse`), `vis_agent/designer/recommend.py` (`default_binding`, `recommend_charts`), `vis_agent/designer/check.py` (`check_spec`), `vis_agent/designer/resolve.py` (`resolve`), `vis_agent/designer/agent.py` (`grammar`), `vis_agent/designer/rulebook.md`
- Create: `tests/designer/test_fold.py`, `evals/designer/agent/reports/jeddah_monthly_injuries_and_deaths.json`
- Modify: `tests/designer/conftest.py`, `tests/designer/test_recommend.py`, `tests/designer/test_check.py`, `tests/designer/test_resolve.py`, `tests/designer/test_syntax.py`, `tests/designer/test_catalogue.py` (if it asserts the changed kinds), `tests/render/test_gptvis.py`, `evals/designer/cases.json`, `evals/designer/agent/cases.json`

**Interfaces:**
- Produces: `vis_agent.designer.fold.fold(columns, result, names, language="en") -> Folded` with `Folded(columns, result, series, value)`; `foldable(columns) -> list[str]`; `FoldError(ValueError)`. `Spec.fold: list[str]`. `Candidate.fold: list[str]`. `default_binding(entry, shape, folded=None)`.
- Later tasks rely on: the spec key `fold`, the candidate field `fold`, and the fact that `check_spec` and `resolve` apply the fold themselves.

- [ ] **Step 1: Write the failing fold tests** in `tests/designer/test_fold.py`:

```python
import pytest

from vis_agent.designer.fold import FoldError, fold, foldable
from tests.designer.conftest import column, table


def injuries_and_deaths():
    columns = [column("month", "time"),
               column("injuries", "measure", "injury_count", aggregate="sum", unit="person"),
               column("deaths", "measure", "death_count", aggregate="sum", unit="person")]
    columns[1].meaning, columns[2].meaning = "Total injuries", "Total deaths"
    rows = [["2025-01-01", 15, 2], ["2025-02-01", 17, 3], ["2025-03-01", 19, 4]]
    return columns, table(columns, rows, types=["DATE", "HUGEINT", "HUGEINT"])


def test_fold_makes_one_row_per_source_row_and_measure():
    columns, result = injuries_and_deaths()
    folded = fold(columns, result, ["injuries", "deaths"])
    assert [c.name for c in folded.columns] == ["month", "Series", "Value"]
    assert folded.series == "Series" and folded.value == "Value"
    series, value = folded.columns[1], folded.columns[2]
    assert series.kind == "category" and series.unit is None and series.aggregate == "none"
    assert value.kind == "measure" and value.unit == "person" and value.aggregate == "sum"
    assert folded.result.rows[:2] == [["2025-01-01", "Total injuries", 15], ["2025-01-01", "Total deaths", 2]]
    assert folded.result.row_count == 6 and folded.result.types == ["DATE", "VARCHAR", "HUGEINT"]
    assert folded.result.columns == ["month", "Series", "Value"]


def test_fold_labels_fall_back_to_names_when_meanings_repeat_and_arabic_names_the_pseudo_columns():
    columns, result = injuries_and_deaths()
    columns[1].meaning = columns[2].meaning = "Total"
    folded = fold(columns, result, ["injuries", "deaths"], language="ar")
    assert folded.series == "السلسلة" and folded.value == "القيمة"
    assert [row[1] for row in folded.result.rows[:2]] == ["injuries", "deaths"]


def test_fold_avoids_a_name_the_result_already_uses():
    columns, result = injuries_and_deaths()
    columns[0].name = "Series"
    result.columns[0] = "Series"
    folded = fold(columns, result, ["injuries", "deaths"])
    assert folded.series == "Series 2" and folded.result.columns == ["Series", "Series 2", "Value"]


def test_fold_keeps_shares_as_shares_with_their_denominator():
    columns = [column("region", "category"),
               column("share_a", "share", aggregate="share", unit="%", denominator="all"),
               column("share_b", "share", aggregate="share", unit="%", denominator="all")]
    folded = fold(columns, table(columns, [["R1", 40.0, 60.0]]), ["share_a", "share_b"])
    assert folded.columns[-1].kind == "share" and folded.columns[-1].aggregate == "share"
    assert folded.columns[-1].denominator == "all"


def test_fold_refuses_a_count_beside_an_average():
    columns = [column("status", "category"), column("orders", "measure", aggregate="count"),
               column("avg_price", "measure", aggregate="avg")]
    with pytest.raises(FoldError, match="aggregated the same way"):
        fold(columns, table(columns, [["new", 12, 250.0]]), ["orders", "avg_price"])


@pytest.mark.parametrize("names, fragment", [
    (["injuries"], "two or more"),
    (["injuries", "nowhere"], "not in the result: nowhere"),
    (["injuries", "injuries"], "twice"),
    (["month", "injuries"], "measures or shares only; month"),
])
def test_fold_refuses_bad_lists(names, fragment):
    columns, result = injuries_and_deaths()
    with pytest.raises(FoldError, match=fragment):
        fold(columns, result, names)


def test_fold_refuses_two_units_and_points_at_dual_axes():
    columns, result = injuries_and_deaths()
    columns[2].unit = "SAR"
    with pytest.raises(FoldError, match="one kind and one unit.*dual_axes"):
        fold(columns, result, ["injuries", "deaths"])


def test_foldable_picks_the_largest_same_unit_set_or_nothing():
    columns, _ = injuries_and_deaths()
    assert foldable(columns) == ["injuries", "deaths"]
    columns[2].unit = "SAR"
    assert foldable(columns) == []
    columns.append(column("cost", "measure", aggregate="sum", unit="SAR"))
    assert foldable(columns) == ["deaths", "cost"]
```

- [ ] **Step 2: Run them to see them fail**: `uv run --no-sync pytest tests/designer/test_fold.py -q` fails with `ModuleNotFoundError`.

- [ ] **Step 3: Write `vis_agent/designer/fold.py`**:

```python
"""Fold measure columns of one unit into a series column and a value column, in code, never in SQL."""

from dataclasses import dataclass

from vis_agent.analyst.models import QueryResult, ResultColumn

PSEUDO_NAMES = {"ar": ("السلسلة", "القيمة"), "en": ("Series", "Value")}


class FoldError(ValueError):
    """The named columns cannot be folded; the message says why in plain words."""


@dataclass
class Folded:
    columns: list[ResultColumn]
    result: QueryResult
    series: str
    value: str


def foldable(columns: list[ResultColumn]) -> list[str]:
    """The largest set of measures or shares sharing one kind, one unit, and one aggregate, when it has two or more;
    the first on a tie. A count beside an average never folds: they are not one scale, whatever their units say."""
    groups: dict[tuple[str, str | None, str], list[str]] = {}
    for column in columns:
        if column.kind in ("measure", "share"):
            groups.setdefault((column.kind, column.unit, column.aggregate), []).append(column.name)
    best = max(groups.values(), key=len, default=[])
    return best if len(best) >= 2 else []


def _unique(name: str, taken: set[str]) -> str:
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{name} {n}", n + 1
    return candidate


def fold(columns: list[ResultColumn], result: QueryResult, names: list[str], language: str = "en") -> Folded:
    """One row per source row and folded column: the series column holds the folded column's meaning, the value column its cell."""
    by_name = {column.name: column for column in columns}
    if len(names) < 2:
        raise FoldError("fold needs two or more columns.")
    if len(set(names)) != len(names):
        raise FoldError("fold names a column twice.")
    missing = [name for name in names if name not in by_name]
    if missing:
        raise FoldError(f"fold names columns that are not in the result: {', '.join(missing)}.")
    chosen = [by_name[name] for name in names]
    wrong = [c.name for c in chosen if c.kind not in ("measure", "share")]
    if wrong:
        raise FoldError(f"fold takes measures or shares only; {', '.join(wrong)} are not.")
    if len({(c.kind, c.unit) for c in chosen}) > 1:
        described = ", ".join(f"{c.name} ({c.kind}{', ' + c.unit if c.unit else ''})" for c in chosen)
        raise FoldError(f"fold needs columns of one kind and one unit; these differ: {described}. "
                        "Measures of different units go on a dual_axes.")
    if len({c.aggregate for c in chosen}) > 1:
        described = ", ".join(f"{c.name} ({c.aggregate})" for c in chosen)
        raise FoldError(f"fold needs columns aggregated the same way; these differ: {described}.")
    series_meaning, value_meaning = PSEUDO_NAMES.get(language, PSEUDO_NAMES["en"])
    series_name = _unique(series_meaning, set(result.columns))
    value_name = _unique(value_meaning, set(result.columns) | {series_name})
    labels = [c.meaning.strip() or c.name for c in chosen]
    if len(set(labels)) != len(labels):
        labels = [c.name for c in chosen]
    first = chosen[0]
    kept = [c for c in columns if c.name not in names]
    folded_columns = [*kept,
                      ResultColumn(name=series_name, meaning=series_meaning, kind="category", aggregate="none"),
                      ResultColumn(name=value_name, meaning=", ".join(labels), kind=first.kind, unit=first.unit,
                                   aggregate=first.aggregate, denominator=first.denominator)]
    kept_index = [result.columns.index(c.name) for c in kept]
    fold_index = [result.columns.index(name) for name in names]
    rows = []
    for row in result.rows:
        base = [row[i] for i in kept_index]
        for label, index in zip(labels, fold_index):
            rows.append([*base, label, row[index]])
    types = [result.types[i] for i in kept_index] + ["VARCHAR", result.types[fold_index[0]]]
    folded_result = QueryResult(sql=result.sql, columns=[c.name for c in folded_columns], types=types, rows=rows,
                                row_count=result.row_count * len(names), seconds=result.seconds)
    return Folded(folded_columns, folded_result, series_name, value_name)
```

- [ ] **Step 4: Run the fold tests**: `uv run --no-sync pytest tests/designer/test_fold.py -q` passes.

- [ ] **Step 5: The grammar and the models.** In `vis_agent/designer/models.py` add `fold: list[str] = Field(default_factory=list)` to `Spec` (after `bind`) and `fold: list[str] = Field(default_factory=list)` to `Candidate` (after `binding`). In `vis_agent/designer/syntax.py` insert `"fold": ("fold", "section:list")` into `KEYS` immediately after the `"bind"` entry, and change the list-item branch of `parse` to `elif indent == 2 and parent in ("emphasis", "palette", "fold"):`. In `vis_agent/designer/agent.py` `grammar()`, add before the `section:list` branch:

```python
        elif key == "fold":
            description = ('section; lines "- <column name>"; two or more measure columns of one unit, drawn as one '
                           'series each on a chart with a group role; leave group and value unbound, the code binds them')
```

Add to `tests/designer/test_syntax.py` a round trip: parse `"vis multi_line\ntitle T\ndescription D\nbind\n  time month\nfold\n  - injuries\n  - deaths\n"`, assert `spec.fold == ["injuries", "deaths"]`, and assert `to_text(spec)` writes the `fold` section right after `bind` with the same two items.

- [ ] **Step 6: The catalogue.** In `vis_agent/designer/catalogue.json`: add `"time"` to `roles.category.kinds` of `grouped_column` and `stacked_column` (the plain `column` already has it); add `"fold"` to `keys` of `grouped_column`, `stacked_column`, `grouped_bar`, `stacked_bar`, `multi_line`, and `stacked_area`; change the two summaries to say "labels or time periods" like `column` does. Fix any assertion in `tests/designer/test_catalogue.py` that spells the old kinds.

- [ ] **Step 7: Recommend with a fold when nothing else binds the series.** In `vis_agent/designer/recommend.py`:

```python
from .fold import Folded, fold, foldable


def default_binding(entry: CatalogueEntry, shape: ResultShape, folded: Folded | None = None) -> dict[str, ColumnShape] | None:
    binding: dict[str, ColumnShape] = {}
    labels = sorted(shape.labels, key=lambda c: -c.distinct)
    # Bind in dependency order: group excludes category; value2 follows value.
    for role in ("category", "time", "x", "y", "value", "value2", "group"):
        if role not in entry.roles:
            continue
        if role == "category":
            choices = [c for c in labels if folded is None or c.name != folded.series]
            if not choices and entry.name in ("column", "bar", "dual_axes", "grouped_column", "stacked_column"):
                choices = shape.times
        elif role == "time":
            choices = shape.times or [c for c in shape.labels if c.kind == "ordinal"]
        elif role == "group":
            if folded is not None:
                choices = [shape.column(folded.series)]
            else:
                choices = sorted(shape.labels, key=lambda c: c.distinct)
                if "category" in binding:
                    choices = [c for c in choices if not shape.is_alias(c.name, binding["category"].name)]
        else:
            choices = shape.measures
            if folded is not None and role == "value":
                choices = [shape.column(folded.value)]
            if role == "value" and entry.name in ("pie", "donut", "treemap"):
                ...  # unchanged
        ...  # the rest of the loop is unchanged
```

and in `recommend_charts`, after the empty-result check:

```python
    names = foldable(columns)
    folded = fold(columns, result, names) if names else None
    folded_shape = describe(folded.columns, folded.result) if folded else None
    context = Context(intent=intent, suggested=suggested)
    candidates, rejected = [], []
    for entry in CATALOGUE.entries:
        used_shape, used_fold = shape, []
        binding = default_binding(entry, shape)
        # A chart that needs a series column gets one folded from the same-unit measures, when nothing else binds it.
        if binding is None and folded is not None and "group" in entry.roles and entry.roles["group"].required:
            binding = default_binding(entry, folded_shape, folded)
            used_shape, used_fold = folded_shape, names
        if binding is None:
            rejected.append(Rejection(name=entry.name, rule="H1",
                                      explanation="Required roles need columns of allowed kinds. Choose a chart that fits the columns."))
            continue
        failure = next((r for rule in HARD_RULES
                        if (r := rule(entry, used_shape, binding, context)) is not None), None)
        ...  # soft rules run with used_shape too
        candidates.append(Candidate(
            name=entry.name, score=sum(r.score for r in breakdown),
            binding={role: c.name for role, c in binding.items() if not used_fold or role not in ("group", "value")},
            fold=used_fold, breakdown=breakdown))
```

Add `two_same_unit_measures()` to `tests/designer/conftest.py`: columns `month` (time), `injuries` (measure, sum, unit "person"), `deaths` (measure, sum, unit "person"), twelve rows `["2025-01", 15, 2] ... ["2025-12", 19, 1]` (any twelve monthly rows with both values positive). Add `two_same_unit_measures_by_city()`: `city` (category), `revenue` and `cost` (measure, sum, unit "SAR"), five rows. Tests in `tests/designer/test_recommend.py`:
  - trend on the monthly pair: the top candidate is `multi_line` with `binding == {"time": "month"}` and `fold == ["injuries", "deaths"]`; `line` is still a candidate with the S9 penalty naming `deaths`; `dual_axes` is rejected under H10.
  - compare on the city pair: the top candidate is `grouped_column` or `grouped_bar`, with `binding == {"category": "city"}` and the fold; `stacked_column` is a candidate too (sums are additive).
  - `two_units()` still ranks `dual_axes` first for compare and offers no fold on any candidate.
  - `grouped()` (a real group column) offers no fold on `grouped_column`.

- [ ] **Step 8: Check a spec with a fold.** In `vis_agent/designer/check.py` import `FoldError, fold`, and restructure the middle of `check_spec` so the fold is applied before the binding checks:

```python
    bind = dict(spec.bind)
    if spec.fold and "fold" in entry.keys:
        for role in ("group", "value"):
            if role in bind:
                fail("C20", f"fold provides the '{role}' role; remove the '{role}' binding.", f"Remove the '{role}' line under bind")
        try:
            folded = fold(columns, result, spec.fold, spec.language)
        except FoldError as error:
            fail("C20", f"fold: {error}", "Fold two or more measure columns of one unit, or drop fold")
        else:
            columns, result = folded.columns, folded.result
            bind.update(group=folded.series, value=folded.value)
    by_name = {column.name: column for column in columns}
    for role, name in bind.items():
        ...  # the C2 loop, now over bind
    for role, requirement in entry.roles.items():
        if requirement.required and role not in bind:
            ...  # unchanged C2
    ...
    shape = describe(columns, result)
    binding = {role: shape.column(name) for role, name in bind.items() if name in by_name}
```

A `fold` on an entry without the key is reported by the existing C3 loop ("does not accept key 'fold'") and is not applied. Tests in `tests/designer/test_check.py`:
  - a `multi_line` spec on the monthly pair with `bind time month` and the fold passes; `canonical` contains the `fold` section; the compromises are unchanged.
  - the same spec with `group injuries` under bind fails with C20 only for the group line.
  - `vis line` with a fold fails with C3 and C2 (`line` has no group role).
  - a fold naming `month` fails with C20 and the message names `month`.
  - a fold of `visits` and `revenue` from `two_units()` fails with C20 and the message mentions `dual_axes`.
  - `emphasis` naming a folded column's meaning passes C9 on a `grouped_column` with the fold.

- [ ] **Step 9: Resolve a spec with a fold.** In `vis_agent/designer/resolve.py` import `fold` and add, at the top of `resolve` right after `entry = CATALOGUE.get(spec.type)`:

```python
    if spec.fold:
        folded = fold(columns, result, spec.fold, spec.language)
        columns, result = folded.columns, folded.result
        spec = spec.model_copy(update={"bind": {**spec.bind, "group": folded.series, "value": folded.value}})
```

Tests in `tests/designer/test_resolve.py`: the monthly pair resolved as `multi_line` with the fold gives `config["data"]` of 24 records with `group` values `injuries` and `deaths` (the conftest meanings equal the names) in month order, `config["type"] == "line"`, and `drawn_rows == 24`; the city pair as `grouped_column` sorts by the category totals with the fold intact. In `tests/render/test_gptvis.py` add one rendered case (inside the existing skip when Node is missing): the monthly pair as `multi_line` with the fold renders a PNG with `non_background_share > 0.02` and two series in the config.

- [ ] **Step 10: The rulebook.** In `vis_agent/designer/rulebook.md`, append to step 2: "A candidate may carry fold, a list of measure columns of one unit that the code turns into one series each; copy both its binding and its fold into the spec." Add under "Filling the spec", after the code-column bullet: "- fold: when the result holds two or more measures of one unit side by side (injuries and deaths per month, males and females per region) and no label column names the series, list those columns under fold and leave group and value unbound; measures of different units go on a dual_axes instead." Nothing else changes in the rulebook.

- [ ] **Step 11: Evaluation cases.** Append to `evals/designer/cases.json` (same shape as the existing entries):
  - `jeddah_monthly_injuries_and_deaths`: columns `الشهر` (time, meaning `الشهر`), `إجمالي المصابين` (measure, meaning `إجمالي عدد المصابين`, unit `شخص`, aggregate sum), `إجمالي الوفيات` (measure, meaning `إجمالي عدد الوفيات`, unit `شخص`, aggregate sum); rows `["2025-01-01",15,2],["2025-02-01",17,3],["2025-03-01",19,4],["2025-04-01",21,1],["2025-05-01",23,2],["2025-06-01",16,3],["2025-07-01",18,4],["2025-08-01",20,1],["2025-09-01",22,2],["2025-10-01",15,3],["2025-11-01",17,4],["2025-12-01",19,1]`; intent `trend`; suggested null; expected `["multi_line"]`; why: "The request that started this plan: two measures of one unit per month, wide. The fold draws them as two lines."
  - `revenue_and_cost_by_city`: five cities with `revenue` and `cost` in SAR (sums); intent `compare`; expected `["grouped_column", "grouped_bar"]`.
  Add the live case to `evals/designer/agent/cases.json` with a report file `evals/designer/agent/reports/jeddah_monthly_injuries_and_deaths.json` built like the existing reports (copy the structure of `deaths_by_year.json`): question `ارسم التغير الشهري لعدد المصابين والوفيات في جدة`, language `Arabic`, the SQL `SELECT "الشهر", SUM("عدد_المصابين") AS "إجمالي المصابين", SUM("عدد_الوفيات") AS "إجمالي الوفيات" FROM "ds_8ede547a29b04849a141d05c2b3e80ba" WHERE "المدينة" = 'جدة' GROUP BY "الشهر" ORDER BY "الشهر"`, the three columns above (sources `الشهر`, `عدد_المصابين`, `عدد_الوفيات`), summary `يوضح التغير الشهري في مدينة جدة تذبذباً في عدد المصابين بين 15 و 23 شخصاً، بينما تراوح عدد الوفيات شهرياً بين شخص واحد و 4 أشخاص.`, assumptions `["تم تجميع البيانات على أساس الشهر كما وردت في العمود \"الشهر\""]`, result types `["DATE", "HUGEINT", "HUGEINT"]`, the twelve rows, `row_count` 12; case fields: expect `design`, charts `["multi_line", "grouped_column"]`, language `ar`, why "The incident of 2026-09-09: wide same-unit measures over months." Keep `tests/designer/test_eval.py` and `tests/designer/test_eval_agent.py` passing (they validate the case files).

- [ ] **Step 12: Run everything and commit**: `uv run --no-sync pytest -q` and `uv run --no-sync python -m evals.designer.run` (39/39 expected). Commit with a message such as `Fold same-unit measures into one series each, in code`. Stage by name.

---

### Task 2: Messages that say what is missing, and no fake questions

**Files:**
- Modify: `vis_agent/designer/rules.py` (new helpers `offered`, `missing_roles`; H10 and H6 texts; `check_rules`), `vis_agent/designer/recommend.py` (the H1 explanation), `vis_agent/designer/check.py` (C2 messages), `vis_agent/designer/agent.py` (`check_spec` retry texts, `deliver_design`, remove `DEAD_END`), `vis_agent/designer/rulebook.md` (step 6), `vis_agent/analyst/agent.py` (`deliver_analysis`, remove `DEAD_END`), `AGENTS.md`
- Modify tests: `tests/designer/test_recommend.py`, `tests/designer/test_check.py`, `tests/designer/test_rules.py`, `tests/designer/test_agent.py`, `tests/analyst/test_agent.py`

**Interfaces:**
- Consumes: Task 1's fold (the H10 advice now points at it).
- Produces: `rules.offered(shape) -> str`, `rules.missing_roles(entry, shape) -> str`; the designer and analyst runs end with `UnexpectedModelBehavior` carrying the diagnostics when a budget is spent with nothing passing.

- [ ] **Step 1: Failing tests for the messages.** In `tests/designer/test_recommend.py`: on `two_units()` with intent `trend`, the rejection of `stacked_area` (which has no fold because the units differ) has rule `H1` and an explanation that contains `needs`, `group (category/ordinal/geography)`, `month (time)`, `visits (measure, visits)`, and `revenue (measure, SAR)`. In `tests/designer/test_check.py`: a `multi_line` spec on `two_units()` that binds only `time` and `value` fails with exactly one C2 whose message contains `Required role 'group' is missing`, `category, ordinal, geography`, and `the result offers`, and no `C10: H1` violation; a spec binding a measure as `group` fails with one C2 and no C10. In `tests/designer/test_rules.py`: `h10_units` on the `two_same_unit_measures()` binding of `dual_axes` returns a fix that contains `fold` and not `grouped column`.

- [ ] **Step 2: Implement the messages.** In `rules.py`:

```python
def offered(shape) -> str:
    """The result's columns with their kinds and units, for a message that says what is actually there."""
    return ", ".join(f"{c.name} ({c.kind}{', ' + c.unit if c.unit else ''})" for c in shape.columns)


def missing_roles(entry, shape) -> str:
    needs = ", ".join(f"{name} ({'/'.join(role.kinds)})" for name, role in entry.roles.items() if role.required)
    return f"{entry.name} needs {needs}; the result offers {offered(shape)}. Choose a chart that fits these columns."
```

Use `missing_roles(entry, shape)` as the H1 explanation in `recommend_charts`. Change H10 to `RuleResult("H10", 0, "The two measures have the same unit.", "Fold them into one series: a multi_line or grouped_column with fold", True)`. Change H6's fix to `"Keep the top groups"`. In `check_rules`, skip `h1_shape` in the hard-rule loop (C2 already reports every missing role and wrong kind with the exact names). In `check.py`, compute `shape = describe(columns, result)` before the C2 loop and make the missing-role message `f"Required role '{role}' is missing; it takes {', '.join(requirement.kinds)}. The result offers {offered(shape)}."` with fix `f"Bind the '{role}' role, or use fold for measures of one unit"` when the entry has the `fold` key, else `f"Bind the '{role}' role"`. Leave every other fix text alone.

- [ ] **Step 3: Failing tests for the dead ends.** Rename `tests/designer/test_agent.py::test_a_spent_check_budget_with_no_pass_ends_in_a_clarification` to `test_a_spent_check_budget_with_no_pass_ends_the_run_with_the_diagnostics`: same drive; assert `result.design is None and result.clarification is None`, `result.check_calls == 3`, `"C6" in result.warnings[0]` and `result.warnings[0].startswith("The designer could not finish")`. Rename `tests/analyst/test_agent.py::test_a_spent_query_budget_with_no_pass_ends_in_a_clarification` to `..._ends_the_run_with_the_check_messages`: run through `analyze_dataset` with the same drive (use `run(store, profiler, analyst, dataset, "إجمالي المبلغ حسب المنطقة")` inside the override) and assert `report.clarification is None`, `report.analysis is None`, and `"Describe exactly the result columns" in report.warnings[0]` and `report.warnings[0].startswith("The analyst could not answer")`.

- [ ] **Step 4: Implement the dead ends.** In the designer's `deliver_design`, replace the `Clarification(...)` return with `raise UnexpectedModelBehavior("No spec passed the three checks; the last failed on: " + reasons)` (keep `reasons` as computed), and delete `DEAD_END`. Change the two `check_spec` retry texts so neither promises a question: "You have used the three check calls of this run and none passed. Call deliver_design with your best spec; a spec that still fails ends the run." and "You have used the three check calls of this run. Deliver the spec that passed." In the analyst's `deliver_analysis`, replace the `Clarification(...)` return with `raise UnexpectedModelBehavior(f"No query passed its checks in {MAX_QUERY_CALLS} tries: " + (" ".join(deps.last_errors) or "no query ran"))`, delete `DEAD_END`, and change the `run_query` over-budget retry text to end with "Deliver the last result that passed its checks, or ask the caller a question only when the columns cannot answer it." Import `UnexpectedModelBehavior` where missing.

- [ ] **Step 5: The rulebook and the guide.** Replace step 6 of `vis_agent/designer/rulebook.md` with: "6. Call ask_clarification only for a decision the caller can make (which of two amount columns, which colours when the brief's cannot meet the contrast rule), with one question in the caller's language. Never ask about a failure of your own checks." In `AGENTS.md`, after the tool-budget bullet, add: "- A spent budget with nothing passing is a technical failure that carries its diagnostics (`UnexpectedModelBehavior`, reported as a warning and then as the request's error or no-chart reason); it is never turned into a question to the caller. A question is only for a decision the caller can make."

- [ ] **Step 6: Run everything and commit**: `uv run --no-sync pytest -q`, `uv run --no-sync python -m evals.designer.run`. Commit, for example `Say what a chart needs and what the result offers; end a spent budget as a failure, not a question`.

---

### Task 3: One analyst revision per request, asked by the designer

**Files:**
- Modify: `vis_agent/analyst/models.py` (`AnalysisRevision`, `RevisionRound`, `PreviousAnalysis.feedback`), `vis_agent/analyst/agent.py` (`revise_rules`), `vis_agent/analyst/rulebook-repair.md` (create), `vis_agent/designer/models.py` (`DesignReport.revision`), `vis_agent/designer/agent.py` (`DesignerPrompt.revision`, `DesignerDeps.last_rejected`, `request_analysis_revision`, `create_designer`, `design_chart`, `prompt_json`, `revise_rules`), `vis_agent/designer/rulebook.md` (new step 6, renumber), `vis_agent/designer/rulebook-revise.md`, `vis_agent/requests/models.py` (`Request.revision`), `vis_agent/requests/runner.py` (`design`, new `run_designer`, `revise_analysis`), `vis_agent/deps.py` and `vis_agent/providers.py` (the designer's output type annotation, where spelled), `AGENTS.md`, `docs/superpowers/specs/2026-09-08-phase-6-lead-and-conversation-design.md` (the steps table)
- Modify tests: `tests/designer/test_agent.py`, `tests/analyst/test_agent.py`, `tests/requests/test_runner.py`, `tests/requests/test_store.py`

**Interfaces:**
- Produces:

```python
class AnalysisRevision(BaseModel):
    """The designer's request for a different result table: an internal handoff, never a question to the caller."""
    model_config = ConfigDict(extra="forbid")
    problem: str
    requested_change: str
    preserve: str
    evidence: list[str] = Field(default_factory=list)


class RevisionRound(BaseModel):
    """What the designer sees after the analyst revised the table: its own request and the analyst's reply."""
    model_config = ConfigDict(extra="forbid")
    request: AnalysisRevision
    reply: str
```

  `PreviousAnalysis.feedback: AnalysisRevision | None = None`. `DesignReport.revision: AnalysisRevision | None = None`. `DesignerPrompt.revision: RevisionRound | None = None`. `design_chart(..., revision: RevisionRound | None = None)`. `Request.revision: AnalysisRevision | None = None`; the earlier analysis is kept under `request.steps["analyze_before_revision"]`.

- [ ] **Step 1: Failing designer tests** in `tests/designer/test_agent.py`:
  - `test_request_analysis_revision_carries_the_runs_diagnostics`: on `two_units()` the drive calls `recommend_charts(intent="trend")`, then `check_spec` with a `multi_line` spec binding only time and value (fails C2), then `request_analysis_revision(problem="No series column", requested_change="One row per month and measure", preserve="Both measures, the monthly grain")`. Assert `result.revision.problem == "No series column"`, `result.design is None and result.clarification is None`, `any("Required role 'group'" in line for line in result.revision.evidence)`, and `any(line.startswith("stacked_area rejected") for line in result.revision.evidence)`; `result.requests == 3`.
  - `test_a_revision_request_in_a_revised_run_gets_one_retry_then_the_run_ends`: call `design_chart(..., revision=RevisionRound(request=AnalysisRevision(problem="p", requested_change="c", preserve="k"), reply="Nothing changed"))` with a drive that always calls `request_analysis_revision`; assert `result.revision is None`, `result.design is None`, `result.warnings[0].startswith("The designer could not finish")`, and `result.requests <= 4`; assert the retry prompt the model saw says the analyst already revised the table once.
  - `test_the_revision_round_reaches_the_prompt_and_loads_the_revise_rules`: `build_prompt(..., revision=round)` puts `revision.reply` in `prompt_json`; without it the key `"revision"` is absent; with it the instructions contain "Answers and revisions".

- [ ] **Step 2: Failing analyst test** in `tests/analyst/test_agent.py`, `test_designer_feedback_reaches_the_analyst_and_loads_the_repair_rules`: `build_prompt(..., previous=PreviousAnalysis(sql=..., columns=..., change="One row per month and measure", feedback=AnalysisRevision(...)))`; `prompt_json` contains `"feedback"` and the problem text; drive `analyst.run` once with a fake that records `messages[0].instructions` and asks a clarification; the instructions contain "A revision the chart designer asked for" and not "Answers and revisions".

- [ ] **Step 3: Failing runner tests** in `tests/requests/test_runner.py` (use the fixtures in `tests/requests/conftest.py`; the analyst drive reads the table name from the prompt):
  - `test_the_designer_can_ask_the_analyst_for_a_revised_table_once`: analyst drive: first run as `analyst_drive`; second run asserts `prompt_of(messages)["previous"]["feedback"]["problem"] == "Need one row per region and day"` and returns `SELECT region, date AS day, sum(amount) AS total FROM {table} GROUP BY 1, 2 ORDER BY 1, 2` with columns region (category), day (time), total (measure, sum), then delivers `summary="Two regions on two days."`, `assumptions=["Kept the total."]`. Designer drive: first run calls `request_analysis_revision(problem="Need one row per region and day", requested_change="Add the day", preserve="The total by region")`; second run asserts `prompt_of(messages)["revision"]["reply"] == "Two regions on two days. Kept the total."` and `["revision"]["request"]["problem"]` matches, then follows `designer_drive` (recommend, check `CHART_SPEC`, deliver). Assert: `outcome.status == "done"`, `outcome.artifact.chart == "bar"`, `outcome.artifact.rows == [["East", "2026-01-01", 10], ["West", "2026-01-02", 20]]`, `outcome.artifact.warnings[0]` contains "asked the analyst to revise the table", `saved.revision.problem == "Need one row per region and day"`, `saved.steps["analyze_before_revision"]["analysis"]["sql"]` is the first SQL and `saved.steps["analyze"]["analysis"]["sql"]` the second, analyst runs == 2, designer runs == 2.
  - `test_a_second_revision_request_is_refused_and_the_fallback_delivers`: the primary designer always requests a revision; the analyst's second run delivers the same table; the fallback designer (`replace(deps, designer_fallback=...)`, as in the existing fallback tests) follows `designer_drive`. Assert `outcome.status == "done"`, chart `bar`, analyst runs == 2 (one revision only), a warning that says the designer asked for a second table revision, and a warning that names the fallback model.
  - `test_a_revision_the_analyst_cannot_make_keeps_the_first_table`: the analyst's second run calls `ask_clarification`; the designer's second run asserts `prompt_of(messages)["revision"]["reply"].startswith("The analyst did not revise the table")` and delivers. Assert `outcome.status == "done"` (no pause), `outcome.artifact.rows == [["West", 20], ["East", 10]]`, `"analyze_before_revision" not in saved.steps`, `saved.revision is not None`.
  - `test_a_crash_after_the_revision_decision_never_revises_again`: monkeypatch `runner.analyze_dataset` to raise `RuntimeError` on its second call; the primary designer requests a revision on its first run and delivers on later runs. The first `run_request` raises; `saved.revision` is set and `saved.steps["analyze"]` is unchanged; the second `run_request` finishes with a chart and the analyst was not called again (the patched function's call count stays 2).
  - `test_an_ordinary_request_adds_no_calls`: keep `test_a_new_request_runs_every_step_and_delivers` passing unchanged; add an assertion there that `saved.revision is None` and `"analyze_before_revision" not in saved.steps`.
  In `tests/requests/test_store.py`: a request with `revision` set round-trips; a stored JSON without the field loads with `revision is None`.

- [ ] **Step 4: Models.** Add `AnalysisRevision` and `RevisionRound` to `vis_agent/analyst/models.py` as spelled above (next to `PreviousAnalysis`), and `feedback: AnalysisRevision | None = None` to `PreviousAnalysis` with the docstring line "feedback is set when the change came from the chart designer, not the caller". Add `revision: AnalysisRevision | None = None` to `DesignReport` and to `Request`.

- [ ] **Step 5: The designer.** In `vis_agent/designer/agent.py`:
  - `DesignerPrompt.revision: RevisionRound | None = None`; `build_prompt(..., revision: RevisionRound | None = None)` passes it through; `prompt_json` excludes it when None (`("clarifications", "previous", "revision")`).
  - `DesignerDeps.last_rejected: list[Rejection] = field(default_factory=list)`; `recommend_charts` sets `deps.last_rejected = ranked.rejected`.
  - The output function:

```python
def request_analysis_revision(ctx: RunContext[DesignerDeps], problem: str, requested_change: str, preserve: str) -> AnalysisRevision:
    """Ask the analyst for a different result table when this one cannot support the chart the question asks for:
    a missing series or grouping column, the wrong time grain, or too many categories to draw. Not for a spec
    mistake you can fix, and never a question to the caller. problem: why this table cannot serve the chart.
    requested_change: what the analyst should make possible; the SQL is the analyst's. preserve: what must not
    change (the measures, filters, time grain, and units the question names)."""
    deps = ctx.deps
    if deps.prompt.revision is not None:
        raise ModelRetry("The analyst already revised the table once for this request. Design from the table you "
                         "have, or deliver a table type.")
    evidence = [*deps.last_violations, *(f"{r.name} rejected: {r.explanation}" for r in deps.last_rejected)][:10]
    return AnalysisRevision(problem=problem, requested_change=requested_change, preserve=preserve, evidence=evidence)
```

  - `create_designer` adds `ToolOutput(request_analysis_revision, name="request_analysis_revision")` to `output_type`; the agent type becomes `Agent[DesignerDeps, Design | Clarification | AnalysisRevision]` (update the annotations in `deps.py`, `providers.py`, and `app.py` where the type is spelled). `revise_rules` returns `REVISE_INSTRUCTIONS` also when `ctx.deps.prompt.revision is not None`.
  - `design_chart(..., revision=None)` passes it to `build_prompt` and sets `revision=output if isinstance(output, AnalysisRevision) else None` on the `DesignReport`.
  - `vis_agent/designer/rulebook.md`: insert a new step 6 before the clarification step (which becomes 7): "6. When the result cannot support the chart the question asks for and no spec change or fold fixes it (a series or grouping column is missing, the time grain is wrong, there are too many categories to draw), call request_analysis_revision once: problem says why this table cannot serve the chart, requested_change what the analyst should make possible, preserve what must not change (the measures, filters, time grain, and units the question names). The analyst's reply comes back to you as revision with the revised columns and preview; design from them and never repeat the first assumption. When the reply says the change was not made, deliver the best chart the table allows, a table type if nothing else."
  - `vis_agent/designer/rulebook-revise.md`: append the paragraph "When the prompt carries `revision`, you asked the analyst for a different table and `revision.reply` says what changed, or why it could not change: the columns and the preview are the revised table. Design from them. Do not request another revision."

- [ ] **Step 6: The analyst.** Create `vis_agent/analyst/rulebook-repair.md`:

```
## A revision the chart designer asked for

When the prompt carries `previous` with `feedback`, the change did not come from the caller: the chart designer could
not draw the chart the caller asked for from your last result, and `feedback` says why (`problem`), what to make
possible (`requested_change`), what must stay (`preserve`), and the checks that failed (`evidence`). The caller's
question stays the authority. Start from `previous.sql`, change only the shape the designer needs (one row per axis
value and measure with a series column, a coarser time bucket, fewer categories with an Other row), keep every
filter, measure, and unit, and say in the summary what changed. When the change would alter the meaning of the
answer, or the columns cannot support it, run the previous query again unchanged and say in the summary and the
assumptions why the change was not made. Never ask the caller a question about the designer's feedback.
```

  In `vis_agent/analyst/agent.py` load it as `REPAIR_INSTRUCTIONS` next to `REVISE_INSTRUCTIONS`, and change `revise_rules` to return `REPAIR_INSTRUCTIONS` when `ctx.deps.prompt.previous is not None and ctx.deps.prompt.previous.feedback is not None`, else the existing behaviour.

- [ ] **Step 7: The runner.** In `vis_agent/requests/runner.py` import `AnalysisRevision, RevisionRound` and replace the body of `design` with a helper that runs one designer, revising the table once when asked:

```python
async def revise_analysis(deps: AppDeps, request: Request, report: AnalysisReport, revision: AnalysisRevision,
                          usage: RunUsage, budget: int | None) -> tuple[AnalysisReport, RevisionRound, str]:
    """One revised analysis for the designer's request. The decision is saved first, so a crash after it never revises again."""
    store = requests_of(deps)
    request.revision = revision
    await asyncio.to_thread(store.save_request, request)
    log.info("The designer asked the analyst to revise the table of %s: %s", request.request_id, revision.problem)
    _check_budget(request, budget)
    feedback = PreviousAnalysis(sql=report.analysis.sql, columns=report.analysis.columns,
                                change=revision.requested_change, feedback=revision)
    revised = await analyze_dataset(deps.store, deps.profiler, deps.analyst, request.dataset_id, report.question,
                                    usage=usage, clarifications=pairs(request), previous=feedback,
                                    language=request.language)
    if revised.analysis is not None and revised.result is not None:
        request.steps["analyze_before_revision"] = request.steps["analyze"]
        request.steps["analyze"] = revised.model_dump(mode="json")
        await asyncio.to_thread(store.save_request, request)
        reply = " ".join([revised.analysis.summary, *revised.analysis.assumptions])
        note = f"The designer asked the analyst to revise the table ({revision.problem}); the chart comes from the revised table."
        return revised, RevisionRound(request=revision, reply=reply), note
    reason = revised.clarification.question if revised.clarification else "; ".join(revised.warnings) or "no result"
    reply = f"The analyst did not revise the table: {reason}"
    return report, RevisionRound(request=revision, reply=reply), \
        f"The designer asked the analyst to revise the table ({revision.problem}) and the analyst could not: {reason}"


async def run_designer(deps: AppDeps, request: Request, designer, brief, previous, usage: RunUsage,
                       budget: int | None) -> DesignReport:
    """One designer run on the request's current table; when it asks for a revision and none was made yet, one more
    run on the revised table. A further request is refused as a failure the fallback or the table answers."""
    report = AnalysisReport.model_validate(request.steps["analyze"])
    _check_budget(request, budget)
    designed = await design_chart(report, designer, brief, usage=usage, clarifications=pairs(request),
                                  previous=previous)
    if designed.revision is not None and request.revision is None:
        report, round_, note = await revise_analysis(deps, request, report, designed.revision, usage, budget)
        _check_budget(request, budget)
        designed = await design_chart(report, designer, brief, usage=usage, clarifications=pairs(request),
                                      previous=previous, revision=round_)
        designed.warnings.insert(0, note)
    if designed.revision is not None:
        designed.warnings.append("The designer asked for a second table revision, which is not allowed: "
                                 f"{designed.revision.problem}")
        designed.revision = None
    return designed
```

  `design` keeps its single-number check, `previous`, and `brief`, then calls `run_designer(deps, request, deps.designer, ...)`; the fallback branch calls `run_designer(deps, request, deps.designer_fallback, ...)` with the same `first`/warning logic as today. `render` and `deliver` read `request.steps["analyze"]` and need no change. The ordinary path makes exactly the same calls as before.

- [ ] **Step 8: Docs.** `AGENTS.md`, after the fallback-designer bullet: "- The design step may ask the analyst for a revised table once per request: the designer's `request_analysis_revision` output becomes an `AnalysisRevision`, the runner saves it on the request as `revision` before the analyst runs, runs the analyst with it as `previous.feedback` (loading `vis_agent/analyst/rulebook-repair.md`), keeps the earlier analysis under `steps.analyze_before_revision`, and runs the designer again with the request and the analyst's reply as `revision`. A second request, including from the fallback designer, is a failure, and a crash after the saved decision never revises again." In the Phase 6 design's steps table, extend the `design` row's third column with "; the designer may ask the analyst once for a revised table, and the step then runs again on it (see AGENTS.md)".

- [ ] **Step 9: Run everything and commit**: `uv run --no-sync pytest -q`, `uv run --no-sync python -m evals.designer.run`. Commit, for example `Let the designer ask the analyst once for a revised table`.

---

### Task 4: Live evaluations, browser check, lessons (controller)

- [ ] Run `uv run python -m evals.designer.agent.run` (31 cases plus the incident) with the Gemma designer; compare with the last run.
- [ ] Run `uv run python -m evals.analyst.run --mismatches` and `uv run python -m evals.lead.run --corpus`; compare with the last runs.
- [ ] In the browser on an isolated instance: the incident question on its dataset draws two lines; an ordinary chart request draws as before; a real clarification still pauses and resumes.
- [ ] Count in Logfire, over the following days, how often the designer asks for a revision and how often it helps.
- [ ] Write the lessons in `docs/phase-6-lessons.md`: the incident, the three changes, the numbers, and what to watch.
