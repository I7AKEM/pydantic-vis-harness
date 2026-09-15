# Phase 5a: The Rules Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the rules ledger of the Phase 5 design: every rule the evaluation run failed the agents for gets one home at one level, and the fixes code can make are made in code.

**Architecture:** Five independent tasks, one per agent plus the renderer. Each adds a normaliser or a check where the prose rulebook used to carry the rule, keeps the existing check contracts (`ProfileCheck` with `severity`, the designer's `Violation` and `Compromise`), trims the rulebook line to a pointer, and proves the fix with the evaluation run's own failing output as the test fixture. The lead's reply becomes a card built by code, with an output validator that refuses invented numbers once.

**Tech Stack:** Python 3.12, uv, Pydantic 2.13, Pydantic AI 2.38 (`agent.override`, `FunctionModel`, `TestModel`, `output_validator`), DuckDB, pytest. Rendering is not needed for any test in this plan.

**Spec:** `docs/superpowers/specs/2026-09-15-phase-5-reviewer-and-team-design.md` — sections 2 (evidence), 3.1 (assessment), 5 (the ledger, the table this plan implements row by row).

## Global Constraints

- Branch `feat/phase-5-reviewer`, worktree `.worktrees/phase-5-reviewer`, cut from `analyst-designer-repair`. Run every command from that directory. Never `git add -A` (a tracked `node_modules` symlink once clobbered the real folder); stage files by name.
- Commit messages: plain, written as the owner; no AI attribution, no `Co-Authored-By` trailer (the owner's standing rule in `~/.claude/CLAUDE.md`).
- Two rule levels only: `error` and `warning` (`ProfileCheck.severity`; the designer's `Violation` is the error, `Compromise` the warning). No new severity system.
- Tests drive agents through `agent.override(model=FunctionModel(...))` or `TestModel`, never a hand-built `RunContext`. `tests/conftest.py` turns `ALLOW_MODEL_REQUESTS` off for every test.
- Messages read as plain words, in the caller's language where the user sees them. No jargon, no rule-id decoding needed to understand a message (ids stay for tests and traces).
- No branch for one dataset, one column name, or one chart; every fix is general.
- Rulebooks are `.md` files next to the agent; a rule the code now enforces becomes a one-line pointer there.
- `uv run pytest -q` passes before every commit. The evaluation runners that need a model (`evals.designer.agent.run`, `evals.analyst.run`, `evals.lead.run`) are run by the controller after the merge, not inside a task.
- Sandbox: Codex tasks have no network; nothing in this plan needs one.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `vis_agent/language.py` (new) | One function that names a text's language by its script; the profiler and the analyst share it | 1 |
| `vis_agent/profiler/models.py` | `ColumnSemantics.unit` validator turning placeholder words into null | 1 |
| `vis_agent/profiler/agent.py` | `ProfilerInput.language`, chosen by code before the model runs | 1 |
| `vis_agent/profiler/review.py` | `language_matches` warning; `run_checks` takes the language | 1 |
| `vis_agent/profiler/rulebook.md` | Language and unit lines become pointers | 1 |
| `vis_agent/analyst/checks.py` | `normalise_units`, `named_period_check`, `restates`, `numbers_in`, `time_in_order` level, shared word lists | 2 |
| `vis_agent/analyst/agent.py` | Normaliser in `run_query`; period check and restated-question refusal; `detect_language` delegates | 2 |
| `vis_agent/analyst/rulebook.md` | Two-sentence rule dropped; unit, order, long-format, and asking lines updated | 2 |
| `vis_agent/designer/agent.py` | `title` compromise in `deliver_design` | 3 |
| `vis_agent/designer/check.py` | The direction compromise only when the spec sets `direction` | 3 |
| `vis_agent/designer/rulebook.md` | Preferences marked as preferences; unit and title lines updated | 3 |
| `vis_agent/designer/resolve.py` | One colour per single series, decimals for tiny values, axis titles by the column they name, count units dropped, table width and `headers` compromise, explicit-direction compromise | 4 |
| `vis_agent/card.py` (new) | The card: the user-facing record assembled by code, in both languages | 5 |
| `vis_agent/requests/models.py`, `vis_agent/requests/runner.py`, `vis_agent/analyst/agent.py` | `card` on `RequestOutcome` and `LeadAnswer`; `LeadArtifact.review` | 5 |
| `vis_agent/lead.py` | The card paragraph in the instructions; the number validator | 5 |

Tasks 1–5 touch disjoint files except `vis_agent/analyst/agent.py` (Tasks 2 and 5, different functions) and can be executed in any order.

---

### Task 1: Profiler — placeholder units become null, and code chooses the profile's language

**Files:**
- Create: `vis_agent/language.py`
- Modify: `vis_agent/profiler/models.py` (class `ColumnSemantics`)
- Modify: `vis_agent/profiler/agent.py` (`ProfilerInput`, `review_profile`, `_profile_dataset`)
- Modify: `vis_agent/profiler/review.py` (`run_checks`)
- Modify: `vis_agent/profiler/rulebook.md`
- Modify: `vis_agent/analyst/agent.py` (`ARABIC`, `detect_language`)
- Test: `tests/profiler/test_units_and_language.py` (new)

**Interfaces:**
- Produces: `vis_agent.language.language_of(*texts: str | None) -> str` returning `"Arabic"` or `"English"`; `vis_agent.language.ARABIC` (compiled regex). `run_checks(statistics, semantic, brief=None, language: str | None = None)`. `ProfilerInput.language: str` (default `"English"`), included in `prompt_json()`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/profiler/test_units_and_language.py
import asyncio

from pydantic_ai.models.test import TestModel

from vis_agent.language import language_of
from vis_agent.profiler.agent import ProfilerInput, create_profiler
from vis_agent.profiler.models import ColumnSemantics
from vis_agent.profiler.review import failed_checks, run_checks
from tests.conftest import semantic_profile


def column(role, unit):
    return ColumnSemantics(name="c", meaning=None, role=role, unit=unit, confidence="low", evidence="e")


def test_placeholder_units_become_null():
    for word in ("null", "None", " n/a ", "-", "count", "unitless", "عدد", ""):
        assert column("category", word).unit is None, word
    assert column("measure", "SAR").unit == "SAR"
    assert column("measure", None).unit is None


def test_language_of_reads_the_script():
    assert language_of("ما عدد السكان؟") == "Arabic"
    assert language_of("", None, "region gender") == "English"
    assert language_of(None) == "English"


def test_the_agent_output_carries_no_placeholder_unit_and_the_prompt_names_the_language(people):
    _dataset_id, profile = people
    columns = [{"name": c.name, "meaning": "m", "role": "measure" if c.name == "amount" else "category",
                "unit": "null", "confidence": "low", "evidence": "e"} for c in profile.deterministic.columns]
    output = {"description": "People.", "row_meaning": None, "questions": [], "columns": columns}
    profiler = create_profiler("test")
    prompt = ProfilerInput(statistics=profile.deterministic, language="English")
    assert '"language":"English"' in prompt.prompt_json()
    with profiler.override(model=TestModel(call_tools=[], custom_output_args=output)):
        result = asyncio.run(profiler.run(prompt.prompt_json(), deps=prompt))
    assert all(c.unit is None for c in result.output.columns)


def test_a_meaning_in_the_wrong_language_is_a_warning(people):
    _dataset_id, profile = people
    semantic = semantic_profile([c.name for c in profile.deterministic.columns])
    semantic.columns[0].meaning = "المنطقة الإدارية"
    failed = [c for c in failed_checks(run_checks(profile.deterministic, semantic, None, language="English"))
              if c.check == "language_matches"]
    assert len(failed) == 1 and failed[0].severity == "warning" and "region" in failed[0].message
    assert not [c for c in run_checks(profile.deterministic, semantic, None) if c.check == "language_matches"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/profiler/test_units_and_language.py -q`
Expected: FAIL — `ModuleNotFoundError: vis_agent.language`, and `ColumnSemantics(... unit="null").unit` is `"null"`.

- [ ] **Step 3: Create `vis_agent/language.py`**

```python
"""The language of a text, read from its script. The profiler and the analyst share one answer."""

import re

ARABIC = re.compile(r"[\u0600-\u06FF]")


def language_of(*texts: str | None) -> str:
    """The language of the first text that holds anything: "Arabic" when it holds Arabic script, else "English"."""
    for text in texts:
        if text and text.strip():
            return "Arabic" if ARABIC.search(text) else "English"
    return "English"
```

- [ ] **Step 4: Add the unit validator to `ColumnSemantics`**

In `vis_agent/profiler/models.py`, import `field_validator` from pydantic, add the word list above the class, and the validator inside it:

```python
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

UNIT_PLACEHOLDERS = frozenset({
    "", "null", "none", "nil", "n/a", "na", "nan", "-", "unknown", "unitless", "no unit", "not applicable",
    "count", "counts", "number", "n", "عدد", "لا يوجد", "بدون", "غير محدد",
})
```

```python
class ColumnSemantics(BaseModel):
    ...  # fields unchanged

    @field_validator("unit", mode="before")
    @classmethod
    def drop_placeholder_units(cls, value):
        """A model that writes the word null, or count, means no unit: counts have none, only measures carry one."""
        if isinstance(value, str) and value.strip().casefold() in UNIT_PLACEHOLDERS:
            return None
        return value
```

- [ ] **Step 5: Choose the language in code and pass it to the prompt and the checks**

In `vis_agent/profiler/agent.py`:

```python
from vis_agent.language import language_of


class ProfilerInput(BaseModel):
    statistics: DeterministicProfile
    brief: DataBrief | None = None
    language: str = "English"
    """The language of descriptions and meanings: the brief's question, else the column names; chosen by code."""
    review_attempts: int = 0  # counts send-backs within one run; never part of the prompt
```

In `review_profile`, pass the language to the checks:

```python
    errors = failed_checks(run_checks(ctx.deps.statistics, draft, ctx.deps.brief, ctx.deps.language), "error")
```

In `_profile_dataset`, build the prompt with the language and use it for the saved review:

```python
    language = language_of(brief.raw_question if brief else None,
                           " ".join(column.original_name for column in statistics.columns))
    prompt = ProfilerInput(statistics=statistics, brief=brief, language=language)
    try:
        result = await _run_with_one_retry(profiler, prompt, usage, dataset_id)
        semantic = result.output
        semantic_model = result.response.model_name
        review = run_checks(statistics, semantic, brief, language)
```

- [ ] **Step 6: Add the `language_matches` warning to `run_checks`**

In `vis_agent/profiler/review.py`:

```python
from vis_agent.language import language_of


def run_checks(statistics: DeterministicProfile, semantic: SemanticProfile,
               brief: DataBrief | None = None, language: str | None = None) -> list[ProfileCheck]:
    checks: list[ProfileCheck] = []
    ...  # existing column and brief checks unchanged
    if language is not None:
        texts = [("description", semantic.description), ("row_meaning", semantic.row_meaning),
                 *((f"meaning of {column.name}", column.meaning) for column in semantic.columns)]
        wrong = [name for name, text in texts if text and text.strip() and language_of(text) != language]
        if wrong:
            checks.append(_check(None, "language_matches", "warning", False,
                                 f"Written in the wrong language: {', '.join(wrong[:5])} should be in {language}."))
    return checks
```

- [ ] **Step 7: Make the analyst share the language function**

In `vis_agent/analyst/agent.py`, replace the regex and the function body (the designer imports `ARABIC` from here, so keep the name):

```python
from vis_agent.language import ARABIC, language_of  # noqa: F401  (ARABIC is re-exported for the designer)


def detect_language(question: str, brief: DataBrief | None, column_names: list[str]) -> str:
    """Once, from the question's script; then the brief's raw question; then the column names."""
    return language_of(question, brief.raw_question if brief else None, " ".join(column_names))
```

Delete the old `ARABIC = re.compile(r"[؀-ۿ]")` line.

- [ ] **Step 8: Update the profiler rulebook**

In `vis_agent/profiler/rulebook.md` replace

```
Write description and row_meaning in the language of the brief's raw_question when there is one,
otherwise in the language of the column names.
```

with

```
Write description, row_meaning, and every meaning in the language named by `language` in your input; the
code chose it from the brief's question, otherwise from the column names, and checks your output against it.
A unit is a real unit of a measure (SAR, %, km, kg), in that language. Leave unit null for counts and for
every column that is not a measure. Never write a placeholder word such as null, none, or count: the code
turns those into null.
```

- [ ] **Step 9: Run the tests and the suite**

Run: `uv run pytest tests/profiler/test_units_and_language.py -q` — Expected: 4 passed.
Run: `uv run pytest -q` — Expected: all pass (the analyst's `detect_language` behaviour is unchanged).

- [ ] **Step 10: Commit**

```bash
git add vis_agent/language.py vis_agent/profiler/models.py vis_agent/profiler/agent.py vis_agent/profiler/review.py vis_agent/profiler/rulebook.md vis_agent/analyst/agent.py tests/profiler/test_units_and_language.py
git commit -m "Turn placeholder units into null and let code choose the profile's language"
```

---

### Task 2: Analyst — units by convention, a reversed trend is an error, named periods, restated questions

**Files:**
- Modify: `vis_agent/analyst/checks.py`
- Modify: `vis_agent/analyst/agent.py` (`run_query`, `deliver_analysis`, `ask_clarification`)
- Modify: `vis_agent/analyst/rulebook.md`
- Test: `tests/analyst/test_units_and_periods.py` (new)

**Interfaces:**
- Produces, in `vis_agent/analyst/checks.py`: `COUNT_UNITS: frozenset[str]`, `SHARE_UNITS: frozenset[str]`, `normalise_units(column: ResultColumn) -> ResultColumn`, `years_named(text: str) -> set[str]`, `named_period_check(question: str, sql: str, assumptions: list[str]) -> ProfileCheck`, `restates(clarification: str, question: str) -> bool`, `numbers_in(text: str) -> set[str]` (tokens with thousands separators removed, Arabic-Indic digits translated). Tasks 4 and 5 import `COUNT_UNITS` and `numbers_in`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/analyst/test_units_and_periods.py
import asyncio

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.analyst.agent import analyze_dataset, create_analyst
from vis_agent.analyst.checks import check_result, named_period_check, normalise_units, numbers_in, restates
from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.profiler.agent import create_profiler
from tests.requests.conftest import prompt_of, tool_returns


def col(name, kind, unit=None, aggregate="none", source=None):
    return ResultColumn(name=name, meaning=name, kind=kind, unit=unit, aggregate=aggregate, source=source)


def test_shares_carry_percent_and_counts_carry_nothing():
    assert normalise_units(col("share", "share")).unit == "%"
    assert normalise_units(col("share", "share", unit="percentage")).unit == "%"
    assert normalise_units(col("n", "measure", unit="person", aggregate="count")).unit is None
    assert normalise_units(col("total", "measure", unit="شخص", aggregate="sum")).unit is None
    assert normalise_units(col("fine", "measure", unit="SAR", aggregate="sum")).unit == "SAR"


def test_a_year_the_question_names_must_reach_the_sql_or_the_assumptions():
    assert named_period_check("Violations in 2024 by city", "SELECT city FROM t WHERE year = 2024", []).passed
    assert not named_period_check("Violations in 2024 by city", "SELECT city FROM t", []).passed
    assert named_period_check("المخالفات في ١٤٤٧", "SELECT city FROM t", ["البيانات كلها لسنة 1447"]).passed
    assert named_period_check("Violations by city", "SELECT city FROM t", []).passed


def test_numbers_in_reads_both_digit_systems():
    assert numbers_in("١٢٬٣٤٥ people and 33.3%") == {"12345", "33.3"}


def test_a_clarification_that_repeats_the_question_is_restated():
    assert restates("هل تقصد نسبة الشباب؟", "ما نسبة الشباب بين السكان؟")
    assert not restates("هل تقصد الفئة 15-24 أم 15-29؟", "ما نسبة الشباب بين السكان؟")
    assert not restates("Which amount column: paid or unpaid?", "Total amount by region")


def test_a_trend_ordered_descending_is_an_error(store, people):
    _dataset_id, profile = people
    columns = [col("day", "time", source="day"), col("total", "measure", aggregate="sum", source="amount")]
    rows = [["2026-03-01", 5], ["2026-02-01", 60], ["2026-01-01", 40]]

    def result(sql):
        return QueryResult(sql=sql, columns=["day", "total"], types=["DATE", "BIGINT"], rows=rows, row_count=3, seconds=0)

    def level(sql):
        return {c.severity for c in check_result(store, profile, columns, result(sql)) if c.check == "time_in_order"}

    assert level('SELECT day, sum(amount) AS total FROM t GROUP BY 1 ORDER BY "day" DESC') == {"error"}
    assert level("SELECT day, sum(amount) AS total FROM t GROUP BY 1 ORDER BY total DESC") == {"warning"}


def test_run_query_normalises_units_and_the_period_check_records_a_warning(store, people):
    dataset_id, _profile = people

    def drive(messages, info):
        if not tool_returns(messages):
            prompt = prompt_of(messages)
            return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={
                "sql": f'SELECT region, count(*) AS n FROM {prompt["table"]} GROUP BY 1 ORDER BY 2 DESC',
                "columns": [{"name": "region", "meaning": "Region", "kind": "category", "source": "region"},
                            {"name": "n", "meaning": "People", "kind": "measure", "aggregate": "count", "unit": "person"}]})])
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_analysis", args={"summary": "West has 3 people."})])

    analyst = create_analyst("test")
    with analyst.override(model=FunctionModel(drive)):
        report = asyncio.run(analyze_dataset(store, create_profiler("test"), analyst, dataset_id, "People by region in 2026"))
    assert report.analysis is not None and report.analysis.columns[1].unit is None
    assert "named_period_missing" in [c.check for c in report.checks if not c.passed]


def test_a_restated_clarification_is_sent_back_once(store, people):
    dataset_id, _profile = people
    calls = {"n": 0}

    def drive(messages, info):
        calls["n"] += 1
        question = "هل تقصد نسبة الشباب؟" if calls["n"] == 1 else "ما الفئة العمرية التي تعدّها شبابًا: 15-24 أم 15-29؟"
        return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification",
                                                 args={"question": question, "reason": "undefined term"})])

    analyst = create_analyst("test")
    with analyst.override(model=FunctionModel(drive)):
        report = asyncio.run(analyze_dataset(store, create_profiler("test"), analyst, dataset_id, "ما نسبة الشباب بين السكان؟"))
    assert calls["n"] == 2 and report.clarification is not None and "15-24" in report.clarification.question
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/analyst/test_units_and_periods.py -q`
Expected: FAIL — `ImportError: cannot import name 'named_period_check'`.

- [ ] **Step 3: Add the helpers to `vis_agent/analyst/checks.py`**

Below the existing constants:

```python
SHARE_UNITS = frozenset({"%", "٪", "percent", "percentage", "pct", "نسبة", "نسبة مئوية", "بالمئة"})
COUNT_UNITS = frozenset({"count", "counts", "number", "n", "record", "records", "row", "rows", "person", "persons",
                         "people", "عدد", "رقم", "شخص", "أشخاص", "نسمة", "فرد", "أفراد", "سجل", "سجلات"})
YEAR = re.compile(r"(?<!\d)(1[3-4]\d{2}|19\d{2}|20\d{2})(?!\d)")
ORDER_BY = re.compile(r"\border\s+by\s+(.+?)(?:\s+limit\b|\s*;?\s*$)", re.IGNORECASE | re.DOTALL)
WORD = re.compile(r"[\w\u0600-\u06FF]+")
STOP_WORDS = frozenset("""a an the of in on for by to and or is are was were do does did you mean want which what
how many much please هل تقصد ما ماذا هو هي في من على عن أم أو و ب ل كم تريد المقصود""".split())


def numbers_in(text: str) -> set[str]:
    """Every number written in the text, Western or Arabic-Indic digits, thousands separators removed."""
    return {token.replace(",", "") for token in NUMBER.findall(text.translate(ARABIC_DIGITS))}


def normalise_units(column: ResultColumn) -> ResultColumn:
    """One convention for the checks and the designer: a share carries %, a count carries no unit."""
    unit = column.unit.strip() if column.unit and column.unit.strip() else None
    if column.kind == "share":
        unit = "%" if unit is None or unit.casefold() in SHARE_UNITS else unit
    elif column.aggregate == "count" or (unit is not None and unit.casefold() in COUNT_UNITS):
        unit = None
    return column if unit == column.unit else column.model_copy(update={"unit": unit})


def years_named(text: str) -> set[str]:
    """Four-digit years in the text, Gregorian or Hijri, in either digit system."""
    return set(YEAR.findall(text.translate(ARABIC_DIGITS)))


def named_period_check(question: str, sql: str, assumptions: list[str]) -> ProfileCheck:
    """A year the question names must appear in the SQL, or an assumption must say why it does not."""
    missing = sorted(years_named(question) - years_named(sql) - years_named(" ".join(assumptions)))
    if missing:
        return _check(None, "named_period_missing", "warning", False,
                      f"The question names {', '.join(missing)}; the SQL does not filter on it and no assumption "
                      "says why. Filter on the period, or record the assumption.")
    return _check(None, "named_period_missing", "warning", True, "ok")


def restates(clarification: str, question: str) -> bool:
    """True when the clarification adds no word the question did not already hold: it repeats, it does not ask."""
    asked = {word.casefold() for word in WORD.findall(clarification)} - STOP_WORDS
    known = {word.casefold() for word in WORD.findall(question)}
    return bool(asked) and asked <= known


def _orders_descending(sql: str, column: ResultColumn) -> bool:
    """True when the statement's first sort key is this column, descending: a reversed time axis is a choice."""
    match = ORDER_BY.search(sql)
    if not match:
        return False
    parts = match.group(1).split(",")[0].strip().split()
    if len(parts) < 2 or parts[-1].casefold() != "desc":
        return False
    key = " ".join(parts[:-1]).strip('"').split(".")[-1].strip('"').casefold()
    return key in {column.name.casefold(), (column.source or "").casefold()}
```

- [ ] **Step 4: Raise `time_in_order` to an error when the SQL reverses the time**

In `check_result`, replace the `if column.kind == "time":` block:

```python
            if column.kind == "time":
                present = [v for v in values if v is not None]
                # Fixed-width YYYY and YYYY-MM text sorts chronologically, including Hijri 13xx/14xx.
                # Keep these buckets as text instead of interpreting them as Gregorian dates.
                if present != sorted(present, key=lambda v: (isinstance(v, str), v)):
                    reversed_on_purpose = _orders_descending(result.sql, column)
                    checks.append(_check(column.name, "time_in_order", "error" if reversed_on_purpose else "warning", False,
                                         f"{column.name}: time is not in chronological order."
                                         + (f" Order it ascending: ORDER BY {quote_identifier(column.name)} ASC."
                                            if reversed_on_purpose else "")))
```

- [ ] **Step 5: Wire the normaliser, the period check, and the refusal into the agent**

In `vis_agent/analyst/agent.py`:

```python
from vis_agent.analyst.checks import check_result, named_period_check, normalise_units, restates, summary_numbers_exist
```

In `run_query`, right after the quoted-alias fix and before `result.checks = ...`:

```python
    columns = [normalise_units(column) for column in columns]
```

In `deliver_analysis`, after the summary number check and before the `return`:

```python
    period = named_period_check(deps.prompt.question, deps.passed.sql, assumptions or [])
    if not period.passed and deps.delivery_attempts == 0:
        deps.delivery_attempts += 1
        raise ModelRetry(period.message)
    if not period.passed:
        deps.passed.result.checks.append(period)
```

Change the docstring's "a two-sentence summary" to "a one- or two-sentence summary".

In `ask_clarification`, after the empty check:

```python
    if restates(question, ctx.deps.prompt.question):
        raise ModelRetry("That question only repeats the caller's words. Answer with SQL, or ask for the one fact or "
                         "definition that is missing, in words the caller did not already use.")
```

- [ ] **Step 6: Update the analyst rulebook**

In `vis_agent/analyst/rulebook.md`:

- Step 5: `a two-sentence summary` → `a one- or two-sentence summary`.
- Step 6, append: `Never ask a question that only repeats the caller's words; name the missing fact or definition.`
- Trend shape: `in chronological order.` → `in chronological order, ORDER BY the bucket ascending; descending is an error.`
- Long-format shape, append: `(either shape draws: the designer folds side-by-side measures of one unit itself).`
- Replace `- unit is null for counts and numbers of things; write a unit only for money, percent, and physical measures, in the caller's language.` with `- unit: write a real unit for money and physical measures, in the caller's language. The code sets % on shares and removes units from counts.`

- [ ] **Step 7: Run the tests and the suite**

Run: `uv run pytest tests/analyst/test_units_and_periods.py -q` — Expected: 7 passed.
Run: `uv run pytest -q` — Expected: all pass. If an existing test asserts a `count` unit survives `run_query`, update its expectation: counts carry no unit now.

- [ ] **Step 8: Commit**

```bash
git add vis_agent/analyst/checks.py vis_agent/analyst/agent.py vis_agent/analyst/rulebook.md tests/analyst/test_units_and_periods.py
git commit -m "Set % on shares and drop count units in code; make a reversed trend an error; catch named periods and restated questions"
```

---

### Task 3: Designer — the title compromise, the direction compromise, preferences named as such

**Files:**
- Modify: `vis_agent/designer/agent.py` (`deliver_design`)
- Modify: `vis_agent/designer/check.py` (`_present_keys`)
- Modify: `vis_agent/designer/rulebook.md`
- Test: `tests/designer/test_ledger.py` (new)

**Interfaces:**
- Consumes: `numbers_in` from Task 2 (`vis_agent.analyst.checks`).
- Produces: a `Compromise(key="title", ...)` on `Design.compromises` when the title carries a number the question did not; `check_spec` no longer records a `direction` compromise for an Arabic spec that sets no direction.

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_ledger.py
import asyncio
from datetime import datetime, timezone

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.analyst.models import Analysis, AnalysisReport
from vis_agent.designer.agent import create_designer, design_chart
from vis_agent.designer.check import check_spec
from tests.designer.conftest import cities
from tests.requests.conftest import tool_returns


def report(question, language="English"):
    columns, result = cities()
    return AnalysisReport(dataset_id="ds", question=question, language=language,
                          analysis=Analysis(sql="x", columns=columns, summary="City0 leads."), result=result,
                          seconds=0, created_at=datetime.now(timezone.utc))


def delivering(spec):
    def drive(messages, info):
        if not tool_returns(messages):
            return ModelResponse(parts=[ToolCallPart(tool_name="check_spec", args={"spec": spec})])
        checked = tool_returns(messages)[-1].model_response_object()
        assert checked["ok"], checked
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_design", args={
            "spec": checked["canonical"], "explanation": "City0 leads. A bar ranks the cities."})])
    return drive


SPEC = "vis bar\ntitle Top 5 cities by violations\ndescription Cities ranked by violations\nbind\n  category city\n  value violations\nsort value desc\n"


def test_a_number_in_the_title_the_question_did_not_name_is_a_compromise():
    designer = create_designer("test")
    with designer.override(model=FunctionModel(delivering(SPEC))):
        designed = asyncio.run(design_chart(report("Top five cities"), designer))
        named = asyncio.run(design_chart(report("Top 5 cities"), designer))
    assert [c.key for c in designed.design.compromises] == ["title"] and "5" in designed.design.compromises[0].message
    assert "title" not in [c.key for c in named.design.compromises]


def test_an_arabic_spec_without_a_direction_records_no_direction_compromise():
    columns, result = cities()
    plain = "vis bar\ntitle عدد المخالفات حسب المدينة\ndescription وصف\nlanguage ar\nbind\n  category city\n  value violations\n"
    explicit = plain + "direction rtl\n"
    assert "direction" not in [c.key for c in check_spec(plain, columns, result).compromises]
    assert "direction" in [c.key for c in check_spec(explicit, columns, result).compromises]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/designer/test_ledger.py -q`
Expected: FAIL — no `title` compromise; the plain Arabic spec carries a `direction` compromise.

- [ ] **Step 3: Add the title compromise in `deliver_design`**

In `vis_agent/designer/agent.py` import `numbers_in` beside `summary_numbers_exist`, and replace the end of `deliver_design` (from `deps.last_check = check`):

```python
    deps.last_check = check
    compromises = list(check.compromises)
    title_numbers = sorted(numbers_in(parsed.title or "") - numbers_in(wording_context(deps)))
    if title_numbers:
        compromises.append(Compromise(key="title", message=f"The title carries {', '.join(title_numbers)}; "
                                                          "a title says what is shown, not how much."))
    return Design(spec=check.canonical, chart=parsed.type, intent=deps.intent,
                  explanation=explanation, considered=list(deps.considered), compromises=compromises)
```

Import `Compromise` from `.models` (add it to the existing `from .models import ...` line).

- [ ] **Step 4: Record the direction compromise only for an explicit direction**

In `vis_agent/designer/check.py`, delete these two lines from `_present_keys`:

```python
    if spec.language == "ar" and "direction" not in keys:
        keys.append("direction")
```

- [ ] **Step 5: Update the designer rulebook**

In `vis_agent/designer/rulebook.md`:

- `Choosing when the rules cannot:` → `Preferences, when the rules leave a choice (the reviewer weighs them; they are not requirements):`
- `- title: in the caller's language; say what is shown, where, and when; no numbers.` → `- title: in the caller's language; say what is shown, where, and when; no numbers, except a year or a number the question itself names.`
- After `- Bracket only real units (SAR, %, km, kg); a count has no unit, so write no brackets for it.` add ` The code removes count units and adds % to shares before you see the columns.`

- [ ] **Step 6: Run the tests and the suite**

Run: `uv run pytest tests/designer/test_ledger.py -q` — Expected: 2 passed.
Run: `uv run pytest -q` — Expected: all pass. A test in `tests/designer/test_check.py` that expected a `direction` compromise on a bare Arabic spec must now expect none.

- [ ] **Step 7: Commit**

```bash
git add vis_agent/designer/agent.py vis_agent/designer/check.py vis_agent/designer/rulebook.md tests/designer/test_ledger.py
git commit -m "Name the designer's preferences as preferences; a title number the question did not name is a compromise"
```

---

### Task 4: Resolver and renderer — one colour per series, decimals, axis titles, count units, table headers

**Files:**
- Modify: `vis_agent/designer/resolve.py`
- Test: `tests/designer/test_resolve.py` (append)

**Interfaces:**
- Consumes: `COUNT_UNITS` from Task 2.
- Produces: `resolve()` output changes only — `style.palette == [ACCENT]` for a single series without a palette or emphasis; `number.decimals` set when the smallest non-zero value is below 0.01; axis titles follow the column they name; `Compromise(key="headers")` and a computed width for wide tables; the `direction` compromise only for `spec.direction == "rtl"`.

- [ ] **Step 1: Write the failing tests** (append to `tests/designer/test_resolve.py`)

```python
from vis_agent.analyst.models import ResultColumn
from vis_agent.designer.rules import ACCENT


def test_a_single_series_gets_one_colour():
    columns, result = cities()
    assert resolve(city_spec(), columns, result).config["style"]["palette"] == [ACCENT]
    columns, result = grouped()
    assert "palette" not in resolve(group_spec(), columns, result).config.get("style", {})


def test_count_units_never_reach_the_axis():
    columns, result = cities()
    columns[1] = column("violations", "measure", aggregate="count", unit="person")
    assert resolve(city_spec(), columns, result).number.unit is None
    columns[1] = column("violations", "measure", aggregate="sum", unit="شخص")
    assert resolve(city_spec(), columns, result).number.unit is None
    columns[1] = column("violations", "measure", aggregate="sum", unit="SAR")
    assert resolve(city_spec(), columns, result).number.unit == "SAR"


def test_tiny_values_get_enough_decimals():
    columns, _ = cities(3)
    tiny = table(columns, [["A", 0.0004], ["B", 0.0002], ["C", 0.0001]], types=["VARCHAR", "DOUBLE"])
    assert resolve(city_spec(), columns, tiny).number.decimals == 5
    assert resolve(city_spec(), *cities()).number.decimals is None


def test_axis_titles_follow_the_column_they_name():
    columns, result = cities()
    right = resolve(city_spec("bar", axis_x_title="number of violations", axis_y_title="city"), columns, result).config
    swapped = resolve(city_spec("bar", axis_x_title="city", axis_y_title="number of violations"), columns, result).config
    assert (right["axisXTitle"], right["axisYTitle"]) == ("city", "number of violations")
    assert (swapped["axisXTitle"], swapped["axisYTitle"]) == ("city", "number of violations")
    plain = resolve(city_spec("column", axis_x_title="city", axis_y_title="number of violations"), columns, result).config
    assert (plain["axisXTitle"], plain["axisYTitle"]) == ("city", "number of violations")


def test_a_wide_table_widens_and_records_its_long_headers():
    columns, result = cities(2)
    columns[1] = ResultColumn(name="violations", meaning="عدد السكان من الفئة العمرية 15 إلى 24 سنة", kind="measure",
                              aggregate="count")
    resolved = resolve(Spec(type="table"), columns, result)
    assert resolved.width > 800 and [c.key for c in resolved.compromises] == ["headers"]
    assert resolve(Spec(type="table"), *cities(2)).width == 800


def test_the_direction_compromise_needs_an_explicit_direction():
    columns, result = cities()
    by_default = resolve(city_spec(language="ar"), columns, result)
    explicit = resolve(city_spec(language="ar", direction="rtl"), columns, result)
    assert "direction" not in [c.key for c in by_default.compromises]
    assert "direction" in [c.key for c in explicit.compromises]
    assert by_default.overrides["title"]["align"] == "right"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/designer/test_resolve.py -q -k "colour or count_units or tiny or axis_titles or wide_table or direction_compromise"`
Expected: 6 FAIL.

- [ ] **Step 3: Count units and the shared list**

In `vis_agent/designer/resolve.py` replace the local `COUNT_UNITS` line with an import and rewrite `_column_unit`:

```python
from vis_agent.analyst.checks import COUNT_UNITS


def _column_unit(column: ResultColumn | None) -> str | None:
    """A count has no unit, whatever word the analyst wrote; other units pass through."""
    if column is None or column.unit is None or not column.unit.strip():
        return None
    if column.aggregate == "count" or column.unit.strip().lower() in COUNT_UNITS:
        return None
    return column.unit.strip()
```

- [ ] **Step 4: The table's width and its long headers**

In `resolve`, inside `if spec.type == "table":`, replace the `width = ...` line and the `compromises = [...]` statement:

```python
        table_columns = [by_name[name] for name in result.columns]
        headers = _table_headers(table_columns)
        # Sixteen pixels a character, sixty characters at most: a long Arabic header widens the table instead of
        # being cut by the package; two short headers stay at the old 800.
        width = spec.width if spec.width is not None else max(
            800, 40 + sum(max(140, 16 * min(len(header), 60)) for header in headers))
        ...
        compromises = [Compromise(key=key, message="tables are drawn as the package draws them")
                       for key in ("labels", "legend") if getattr(spec, key) == "on"]
        long_headers = [header for header in headers if len(header) > 24]
        if long_headers:
            compromises.append(Compromise(key="headers", message=f"{len(long_headers)} long table headers may be "
                                                                  "shortened by the package: " + "; ".join(long_headers[:3])))
```

(Keep the order: `table_columns` and `headers` are computed before `width` now.)

- [ ] **Step 5: Axis titles by the column they name**

Add the helper above `resolve`:

```python
def _names(title: str | None, column: ResultColumn | None) -> bool:
    """True when the title carries the column's name or meaning."""
    if not title or column is None:
        return False
    text = title.casefold()
    meaning = column.meaning.strip().casefold()
    return column.name.casefold() in text or (bool(meaning) and meaning in text)
```

Replace, inside `if spec.type not in WITHOUT_AXES:`, the lines

```python
        x_title, y_title = spec.axis_x_title, spec.axis_y_title
        if spec.type in BARS:
            x_title, y_title = y_title, x_title
```

with

```python
        category_title, value_title = spec.axis_x_title, spec.axis_y_title
        if spec.type in BARS:
            # The spec's axisXTitle names the horizontal axis; on horizontal bars that axis holds the values.
            category_title, value_title = value_title, category_title
        if (_names(category_title, y_column) and not _names(category_title, x_column)
                and _names(value_title, x_column) and not _names(value_title, y_column)):
            # Written for the other axis: a title follows the column it names.
            category_title, value_title = value_title, category_title
        x_title, y_title = category_title, value_title
```

- [ ] **Step 6: One colour per single series**

After the `elif spec.emphasis:` palette block add:

```python
    elif spec.type in SINGLE_SERIES and "group" not in binding:
        # One series, one colour: the package would colour each bar by category, which reads as meaning.
        style["palette"] = [ACCENT]
```

- [ ] **Step 7: The direction compromise only when the spec sets it**

In the `if (spec.direction or defaults["direction"]) == "rtl":` block, guard the compromise:

```python
        if spec.direction == "rtl":
            compromises.append(Compromise(key="direction", message="the legend stays where the package puts it"))
```

- [ ] **Step 8: Decimals for tiny values**

After `if number.unit is None: number.unit = ...` and before `number2 = None`:

```python
    if number.decimals is None and spec.type != "histogram":
        smallest = min((abs(record[role]) for record in records for role in MEASURES
                        if role in record and record[role]), default=None)
        if smallest is not None and smallest < 0.01:
            # Two significant digits of the smallest value, so 0.0001 prints as 0.00010, never as 0.
            number.decimals = min(6, 1 - Decimal(str(smallest)).adjusted())
```

- [ ] **Step 9: Run the tests and the suite**

Run: `uv run pytest tests/designer/test_resolve.py -q` — Expected: all pass, the six new ones included.
Run: `uv run pytest -q` — Expected: all pass. `tests/render/test_gptvis.py` and `tests/designer/test_eval.py` compare resolved configs; where a single-series expectation lacked `style.palette`, add `[ACCENT]`.

- [ ] **Step 10: Commit**

```bash
git add vis_agent/designer/resolve.py tests/designer/test_resolve.py
git commit -m "Draw a single series in one colour, keep tiny values visible, put axis titles on the axis they name, widen tables"
```

---

### Task 5: The card, and a lead that cannot invent a number

**Files:**
- Create: `vis_agent/card.py`
- Modify: `vis_agent/requests/models.py` (`LeadArtifact`, `RequestOutcome`)
- Modify: `vis_agent/requests/runner.py` (`outcome_for`)
- Modify: `vis_agent/analyst/agent.py` (`LeadAnswer`)
- Modify: `vis_agent/lead.py` (`LEAD_INSTRUCTIONS`, `create_lead`)
- Test: `tests/test_card.py` (new), `tests/test_lead_validator.py` (new), `tests/requests/test_runner.py` (append one test)

**Interfaces:**
- Consumes: `numbers_in` from Task 2.
- Produces: `vis_agent.card.card(*, language, png_url=None, no_chart_reason=None, summary=None, explanation=None, columns=(), rows=(), row_count=0, assumptions=(), compromises=(), warnings=(), review=None, artifact_id=None, request_id=None) -> str`; `RequestOutcome.card: str | None`; `LeadAnswer.card: str | None`; `LeadArtifact.review: dict | None` (from `Artifact.review`); `vis_agent.lead.invented_numbers(reply: str, known: set[str]) -> list[str]`. Plan 5b's Task 7 fills `review` with `{"status": "reviewed", "verdict": ..., "review": {"findings": [...]}}` and the card shows it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_card.py
from vis_agent.analyst.models import ResultColumn
from vis_agent.card import card
from vis_agent.designer.models import Compromise

COLUMNS = [ResultColumn(name="region", meaning="Region", kind="category"),
           ResultColumn(name="total", meaning="Total", kind="measure")]


def test_the_card_holds_everything_the_user_must_see():
    text = card(language="English", png_url="/renders/abc/chart.png", summary="West leads.",
                explanation="A bar compares the regions.", columns=COLUMNS, rows=[["West", 20], ["East", 10]],
                row_count=2, assumptions=["Nulls dropped"], compromises=[Compromise(key="zero", message="The axis starts at 5.")],
                warnings=["w1"], artifact_id="art_1", request_id="rq_1")
    for piece in ("![chart](/renders/abc/chart.png)", "West leads.", "A bar compares the regions.", "| Region | Total |",
                  "| West | 20 |", "2 of 2 rows", "**Assumptions**", "- Nulls dropped", "**Compromises**",
                  "- The axis starts at 5.", "**Warnings**", "- w1", "Artifact art_1 · Request rq_1"):
        assert piece in text, piece
    assert "**Review**" not in text


def test_the_card_speaks_arabic_and_says_why_there_is_no_chart():
    text = card(language="Arabic", no_chart_reason="النتيجة رقم واحد.", columns=COLUMNS, rows=[["غرب", 20]], row_count=1,
                artifact_id="art_1", request_id="rq_1")
    assert "**بلا رسم**: النتيجة رقم واحد." in text and "1 من 1 صفًا" in text and "المخرج art_1 · الطلب rq_1" in text


def test_the_card_shows_twenty_rows_and_the_review():
    rows = [[f"r{i}", i] for i in range(25)]
    review = {"status": "reviewed", "verdict": "revise",
              "review": {"findings": [{"rule": "R-1", "level": "error", "owner": "designer", "message": "Bar 3 is unlabelled."},
                                      {"rule": "S5", "level": "warning", "owner": "designer", "message": "Long labels."}]}}
    text = card(language="English", columns=COLUMNS, rows=rows, row_count=25, review=review, artifact_id="a", request_id="r")
    assert text.count("\n| r") == 20 and "20 of 25 rows" in text
    assert "**Review**: revise" in text and "- Bar 3 is unlabelled." in text and "Long labels." not in text
    assert "**Review**" not in card(language="English", review={"status": "not_reviewed"}, artifact_id="a", request_id="r")
```

```python
# tests/test_lead_validator.py
import asyncio

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.analyst.agent import create_analyst
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import create_designer
from vis_agent.lead import create_lead, invented_numbers
from vis_agent.profiler.agent import create_profiler


def test_invented_numbers_ignore_list_markers_ids_and_known_values():
    known = {"20", "33.333", "2026"}
    assert invented_numbers("1. West 20\n2. East 33.3 (art_ab12, rq_9f, 2026)", known) == []
    assert invented_numbers("The total is 999 and 20.", known) == ["999"]


def test_the_lead_is_sent_back_once_for_a_number_no_tool_returned(store):
    replies = iter(["The total is 999.", "The total is 12."])

    def drive(messages, info):
        return ModelResponse(parts=[TextPart(next(replies))])

    lead = create_lead("test")
    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"), designer=create_designer("test"))
    with lead.override(model=FunctionModel(drive)):
        result = asyncio.run(lead.run("What is 12 plus nothing?", deps=deps))
    assert result.output == "The total is 12."
```

Append to `tests/requests/test_runner.py`:

```python
def test_the_outcome_carries_a_card(deps, dataset_id, fake_models, fake_render):
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    outcome = run(run_request(deps, request.request_id))
    assert outcome.card and "![chart](/renders/" in outcome.card and outcome.artifact.artifact_id in outcome.card
    assert "| West | 20 |" in outcome.card and "2 of 2 rows" in outcome.card
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_card.py tests/test_lead_validator.py tests/requests/test_runner.py::test_the_outcome_carries_a_card -q`
Expected: FAIL — `ModuleNotFoundError: vis_agent.card`; `ImportError: invented_numbers`; `outcome.card` missing.

- [ ] **Step 3: Create `vis_agent/card.py`**

```python
"""The card: what the user sees of a result, assembled by code so nothing is dropped and nothing is invented."""

from collections.abc import Sequence

from vis_agent.analyst.models import ResultColumn
from vis_agent.designer.models import Compromise

CARD_ROWS = 20
LABELS = {
    "English": {"rows": "{shown} of {total} rows", "assumptions": "Assumptions", "compromises": "Compromises",
                "warnings": "Warnings", "review": "Review", "findings": "Open findings", "no_chart": "No chart",
                "ids": "Artifact {artifact} · Request {request}"},
    "Arabic": {"rows": "{shown} من {total} صفًا", "assumptions": "الافتراضات", "compromises": "التنازلات",
               "warnings": "تنبيهات", "review": "المراجعة", "findings": "ملاحظات مفتوحة", "no_chart": "بلا رسم",
               "ids": "المخرج {artifact} · الطلب {request}"},
}


def _cell(value) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


def _table(columns: Sequence[ResultColumn], rows: Sequence[Sequence], total: int, labels: dict) -> str:
    headers = [column.meaning.strip() or column.name for column in columns]
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in list(rows)[:CARD_ROWS]]
    return "\n".join(lines) + "\n\n" + labels["rows"].format(shown=min(len(rows), CARD_ROWS), total=total)


def _section(title: str, items: Sequence[str]) -> str:
    return f"**{title}**\n" + "\n".join(f"- {item}" for item in items) if items else ""


def _review(review: dict | None, labels: dict) -> str:
    """The reviewer's verdict and the findings still open; nothing until a reviewer has run."""
    if not review or review.get("status") != "reviewed":
        return ""
    findings = review.get("review", {}).get("findings", [])
    open_findings = [f["message"] for f in findings if f.get("level") == "error"]
    return "\n".join(part for part in (f"**{labels['review']}**: {review.get('verdict', '')}",
                                       _section(labels["findings"], open_findings)) if part)


def card(*, language: str, png_url: str | None = None, no_chart_reason: str | None = None, summary: str | None = None,
         explanation: str | None = None, columns: Sequence[ResultColumn] = (), rows: Sequence[Sequence] = (),
         row_count: int = 0, assumptions: Sequence[str] = (), compromises: Sequence[Compromise] = (),
         warnings: Sequence[str] = (), review: dict | None = None, artifact_id: str | None = None,
         request_id: str | None = None) -> str:
    """Markdown in the caller's language: picture, summary, explanation, table with its count, assumptions,
    compromises, warnings, review, and the IDs. Every part the lead's instructions once asked the model to assemble."""
    labels = LABELS.get(language, LABELS["English"])
    parts = [
        f"![chart]({png_url})" if png_url else f"**{labels['no_chart']}**: {no_chart_reason}" if no_chart_reason else "",
        summary or "",
        explanation or "",
        _table(columns, rows, row_count, labels) if columns else "",
        _section(labels["assumptions"], list(assumptions)),
        _section(labels["compromises"], [c.message for c in compromises]),
        _section(labels["warnings"], list(warnings)),
        _review(review, labels),
        labels["ids"].format(artifact=artifact_id, request=request_id) if artifact_id and request_id else "",
    ]
    return "\n\n".join(part for part in parts if part)
```

- [ ] **Step 4: Put the card on the outcomes**

In `vis_agent/requests/models.py`:

```python
class LeadArtifact(BaseModel):
    ...
    warnings: list[str] = []
    review: dict[str, Any] | None = None
```

and in `from_artifact` add `review=artifact.review,`. In `RequestOutcome` add `card: str | None = None` after `warnings`.

In `vis_agent/requests/runner.py`, `outcome_for`:

```python
from vis_agent.card import card as build_card


async def outcome_for(deps: AppDeps, request: Request, warnings: list[str] | None = None) -> RequestOutcome:
    pending = request.pending()
    artifact = None
    shown = None
    if request.artifact_id:
        artifact = LeadArtifact.from_artifact(await asyncio.to_thread(requests_of(deps).get_artifact, request.artifact_id))
        shown = build_card(language=request.language or "English", png_url=artifact.png_url,
                           no_chart_reason=artifact.no_chart_reason, summary=artifact.summary,
                           explanation=artifact.explanation, columns=artifact.columns, rows=artifact.rows,
                           row_count=artifact.row_count, assumptions=artifact.assumptions,
                           compromises=artifact.compromises, warnings=[*artifact.warnings, *(warnings or [])],
                           review=artifact.review, artifact_id=artifact.artifact_id, request_id=artifact.request_id)
    return RequestOutcome(
        request_id=request.request_id, status=request.status, artifact=artifact, card=shown,
        clarification=Clarification(question=pending.question, reason=pending.reason) if pending else None,
        overdue=pending.overdue(now()) if pending else False, error=request.error, warnings=list(warnings or []),
    )
```

In `vis_agent/analyst/agent.py`, `LeadAnswer` gains `card: str | None = None` after `warnings`, and `from_report` becomes:

```python
from vis_agent.card import card as build_card


    @classmethod
    def from_report(cls, report: AnalysisReport) -> "LeadAnswer":
        analysis, table = report.analysis, report.result
        rows = table.rows[:LEAD_ROWS] if table else []
        row_count = table.row_count if table else 0
        shown = build_card(language=report.language, summary=analysis.summary, columns=analysis.columns, rows=rows,
                           row_count=row_count, assumptions=analysis.assumptions, warnings=report.warnings) \
            if analysis is not None else None
        return cls(
            dataset_id=report.dataset_id, question=report.question,
            summary=analysis.summary if analysis else None,
            assumptions=analysis.assumptions if analysis else [],
            clarification=report.clarification,
            columns=analysis.columns if analysis else [],
            rows=rows, row_count=row_count,
            sql=analysis.sql if analysis else None,
            warnings=report.warnings, card=shown,
        )
```

- [ ] **Step 5: The lead's instructions and the validator**

In `vis_agent/lead.py` replace the "Showing a result." paragraph of `LEAD_INSTRUCTIONS` with:

```
Showing a result. draw, revise, resume, and answer_question return a card: the picture, the summary, the table
with its row count, the assumptions, the compromises, the warnings, the review, and the IDs, already in the
user's language. Put the card in your reply exactly as returned, whole, then add your own words around it. Never
restate a number that is not in the card or in the user's message, never describe a chart that is not in the
card, and never drop the table on a picture-only revision: the card has it. When the outcome has no artifact,
say why in one sentence. Offer the spec and the SQL when asked.
```

Add the validator helpers at module level and register the validator in `create_lead`:

```python
import re

from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart

from vis_agent.analyst.checks import numbers_in

LIST_MARKER = re.compile(r"(?m)^\s*\d{1,2}[.)]\s")
IDENTIFIER = re.compile(r"\b(?:art|rq|ds)_[0-9a-f]+\b")


def numbers_from_the_run(messages) -> set[str]:
    """Every number this run has seen: the user's words and the tools' returns, cards included."""
    seen: set[str] = set()
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                content = part.content if isinstance(part.content, str) else " ".join(str(c) for c in part.content)
                seen |= numbers_in(content)
            elif isinstance(part, ToolReturnPart):
                seen |= numbers_in(part.model_response_str())
    return seen


def _same_value(number: str, known: set[str]) -> bool:
    decimals = len(number.split(".")[1]) if "." in number else 0
    value = float(number)
    for candidate in known:
        try:
            if abs(round(float(candidate), decimals) - value) < 1e-9:
                return True
        except ValueError:
            continue
    return False


def invented_numbers(reply: str, known: set[str]) -> list[str]:
    """Numbers in the reply that no result and no user message hold; list markers and IDs are not numbers."""
    text = IDENTIFIER.sub(" ", LIST_MARKER.sub(" ", reply))
    return sorted(n for n in numbers_in(text) if n not in known and not _same_value(n, known))
```

```python
def create_lead(model: str | Model, advisor_model: str | None = None) -> Agent[AppDeps, str]:
    ...  # unchanged construction and tool registration

    @agent.output_validator
    def numbers_come_from_the_run(ctx: RunContext[AppDeps], reply: str) -> str:
        """A figure the user did not write and no tool returned is invented: one retry, then the reply goes out and
        the slip is logged, because a stuck lead is worse than one wrong figure."""
        invented = invented_numbers(reply, numbers_from_the_run(ctx.messages))
        if invented and ctx.retry == 0:
            raise ModelRetry("These numbers are in no result and not in the user's message: " + ", ".join(invented)
                             + ". Use only the card's numbers, or leave the number out.")
        if invented:
            log.warning("The lead's reply keeps numbers no result returned: %s", invented)
        return reply

    return agent
```

Make sure `log = logging.getLogger("lead")` exists in the module (add it if absent) and that `ModelRetry` and `RunContext` are already imported (they are, for the tools).

- [ ] **Step 6: Run the tests and the suite**

Run: `uv run pytest tests/test_card.py tests/test_lead_validator.py tests/requests/test_runner.py -q` — Expected: all pass.
Run: `uv run pytest -q` — Expected: all pass. `tests/test_lead_eval.py` and `tests/test_agents.py` drive the lead with fake replies; a fake reply that quotes a number absent from its fake tool return now gets one retry — adjust such a fixture to return the same reply twice or to quote a returned number.

- [ ] **Step 7: Commit**

```bash
git add vis_agent/card.py vis_agent/requests/models.py vis_agent/requests/runner.py vis_agent/analyst/agent.py vis_agent/lead.py tests/test_card.py tests/test_lead_validator.py tests/requests/test_runner.py
git commit -m "Build the reply card in code and send the lead back once for a number no result returned"
```

---

## After the tasks (controller)

- `uv run pytest -q`; `uv run python -m evals.designer.run` (model-free, 37 cases).
- With `OPENROUTER_API_KEY`: `uv run python -m evals.designer.agent.run` (31 cases, all delivered, `Passed` 1.0), `uv run python -m evals.analyst.run` (70 cases; expect the count-unit and `%` conventions to change no table), `uv run python -m evals.lead.run --corpus` (tool choice unchanged; every reply now carries the card).
- Browser check on an isolated instance (own `DATA_DIRECTORY` and `DUCKDB_PATH`): one chart in Arabic with a single series (one colour), one table with long Arabic headers, one numbers-only answer; the reply shows the card whole, with IDs and row count.
- Ask the evaluation team to rerun their 283 cases against this branch; the profiler's unit failures and the designer's single-colour failures should be gone (spec, section 9, exit test 5).
- Ledger row P-geo (judgment, no code change): add the profiler cases both judges failed on roles to `evals/profiler` with `uv run python -m evals.profiler.make_cases` from their CSVs (the `Dev CSV` folder on the Desktop holds the files), so the next profiler round measures them.
