# Program Caller and Query Result Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the specialists behave as a visualization agent downstream of a data agent: they know who is asking and that the table is a finished query result, they decide presentation themselves, and they never echo or repeat a question.

**Architecture:** The runner already builds both specialist prompts and knows the caller and the brief, so a `caller` field and two per-run instruction blocks travel through the existing `@agent.instructions` mechanism; the ask tools get a code guard raising `ModelRetry`; the CSV import drops BOOLEAN from its type candidates; a program-caller evaluation set measures the change before and after. No new agent, package, or workflow engine.

**Tech Stack:** Python 3.12, uv, Pydantic AI (`Agent`, `RunContext`, `ModelRetry`, `FunctionModel`, `TestModel`), DuckDB, pydantic-evals, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-program-caller-design.md`

## Global Constraints

- Python 3.12, uv, Pydantic AI; application code in `vis_agent`, one subpackage per agent; tests and evals mirror it.
- No workflow engine, no external A2A package, no new agents, no planner.
- Each agent's rulebook is `vis_agent/<agent>/rulebook.md`; per-run rules live in sibling `rulebook-*.md` files and reach the model per run only.
- Tests use fake models through `agent.override` and never hand-build `RunContext`.
- Fixable mistakes are `ModelRetry`, once; failures the model cannot fix are `ToolFailed` or a run failure.
- The test for every budget drives a model that ignores the message and asserts the run ends within a fixed number of requests.
- Ordinary runs stay unchanged: a person's prompt JSON and instructions must be byte-identical to today.
- Every confirmed mistake becomes an eval case plus a check or a rulebook line.
- Run `uv run pytest -q` before every commit; run `uv run python -m evals.analyst.run` and `uv run python -m evals.lead.run` before the merge.
- Commit messages describe the change in the owner's voice, with no tool attribution.
- Baseline commit: 8f5fd20. The owner's in-flight edits to `vis_agent/providers.py`, `tests/test_providers.py`, `README.md`, `AGENTS.md`, and `.env.example` are not part of this plan; do not revert them.

---

## File structure

| File | Responsibility |
|---|---|
| `vis_agent/models.py` | shared contracts; gains `CallerRole` |
| `vis_agent/requests/models.py` | request contracts; `Caller.role`, `Lineage` provenance fields |
| `vis_agent/analyst/agent.py` | prompt, tools, per-run instruction blocks, ask guard, `normalized_question` |
| `vis_agent/analyst/rulebook-program.md` | rules for a program caller (new) |
| `vis_agent/analyst/rulebook-query-result.md` | rules when the brief carries the producing query (new) |
| `vis_agent/analyst/checks.py` | result checks; gains `unit_kept_checks` |
| `vis_agent/designer/agent.py` | prompt, per-run block, ask guard |
| `vis_agent/designer/rulebook-program.md` | rules for a program caller (new) |
| `vis_agent/designer/rulebook.md` | title and subtitle rules |
| `vis_agent/profiler/rulebook.md` | query, unit language, code meanings |
| `vis_agent/profiler/models.py` | `PROFILE_VERSION` |
| `vis_agent/store.py` | CSV import types |
| `vis_agent/requests/runner.py` | passes the caller role; lineage provenance |
| `vis_agent/requests/store.py` | `list_requests(identity=...)` |
| `vis_agent/requests/api.py` | the ask route's `requests` field |
| `vis_agent/lead.py` | thinking off |
| `evals/analyst/run.py` | `--caller`, `--model litellm`, the `answer` expectation |
| `evals/analyst/program/make_cases.py`, `cases.json` | the program-caller set (new) |
| `docs/phase-7-lessons.md` | baseline and exit numbers (new) |

---

### Task 1: The program-caller evaluation set and its baseline

**Files:**
- Create: `evals/analyst/program/__init__.py`, `evals/analyst/program/make_cases.py`, `evals/analyst/program/cases.json`
- Modify: `evals/analyst/run.py:93-100` (scoring), `evals/analyst/run.py:109-122` (loader), `evals/analyst/run.py:165-200` (options and task)
- Test: `tests/analyst/test_eval.py`

**Interfaces:**
- Produces: `evals.analyst.run.score(expected: dict, output: AnalysisReport) -> float`; case field `"expect": "answer"`; case field `"caller": "person" | "program"` (read in Task 2); `--model litellm` and `--profiler-model litellm` sentinels.

- [ ] **Step 1: Write the failing tests**

Append to `tests/analyst/test_eval.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from vis_agent.analyst.models import Analysis, AnalysisReport, Clarification, QueryResult, ResultColumn


def _report(analysis=None, clarification=None, result=None):
    return AnalysisReport(dataset_id="ds_1", question="q", language="English", analysis=analysis,
                          clarification=clarification, result=result, seconds=0.0,
                          created_at=datetime(2026, 9, 15, tzinfo=timezone.utc))


def test_an_answer_expectation_scores_an_analysis_without_a_question():
    from evals.analyst.run import score
    columns = [ResultColumn(name="total", meaning="Total", kind="measure", source="amount", aggregate="sum")]
    answered = _report(analysis=Analysis(sql="SELECT 1", columns=columns, summary="s"),
                       result=QueryResult(sql="SELECT 1", columns=["total"], types=["BIGINT"], rows=[[1]], row_count=1, seconds=0.0))
    asked = _report(clarification=Clarification(question="Which?", reason="r"))
    assert score({"expect": "answer", "columns": [], "rows": []}, answered) == 1.0
    assert score({"expect": "answer", "columns": [], "rows": []}, asked) == 0.0
    assert score({"expect": "clarification", "columns": [], "rows": []}, asked) == 1.0


def test_the_program_set_asks_every_corpus_brief_with_a_query_as_a_program():
    from evals.analyst.run import load_cases
    cases = load_cases(Path("evals/analyst/program"))
    assert len(cases) >= 40
    for case in cases:
        assert case.inputs["caller"] == "program" and case.expected_output["expect"] == "answer"
        assert case.inputs["brief"]["query"] and case.inputs["question"] == case.inputs["brief"]["raw_question"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/analyst/test_eval.py -q`
Expected: FAIL with `ImportError: cannot import name 'score'` and a missing `evals/analyst/program` directory.

- [ ] **Step 3: Write the case generator**

Create `evals/analyst/program/__init__.py` (empty) and `evals/analyst/program/make_cases.py`:

```python
"""Writes cases.json beside this file: every profiler corpus brief that carries the producing query and the user's
question, asked the way a program asks, expecting an answer with no question back. Deterministic."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent.parent / "profiler" / "corpus_cases"


def main() -> None:
    cases = []
    for brief_path in sorted(CORPUS.glob("*.brief.json")):
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        if not brief.get("query") or not brief.get("raw_question"):
            continue
        name = brief_path.name.removesuffix(".brief.json")
        cases.append({
            "name": name, "csv": f"../../profiler/corpus_cases/{name}.csv", "question": brief["raw_question"],
            "brief": brief, "caller": "program", "expect": "answer",
        })
    (HERE / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(cases)} program cases")


if __name__ == "__main__":
    main()
```

Run: `uv run python -m evals.analyst.program.make_cases`
Expected: `49 program cases` or close to it (50 corpus briefs carry a query; one may lack a question).

- [ ] **Step 4: Teach the runner the answer expectation, the caller field, and the proxy model**

In `evals/analyst/run.py`, replace the `TableMatches` class with a scoring function and a thin evaluator:

```python
def score(expected: dict, output: AnalysisReport) -> float:
    """1.0 for the outcome the case expects: a matching table, a question back, or, for a program's case, an
    analysis delivered without any question."""
    if expected["expect"] == "answer":
        return 1.0 if output.analysis is not None and output.clarification is None else 0.0
    if expected["expect"] != "table":
        return 1.0 if output.clarification is not None else 0.0
    if output.result is None:
        return 0.0
    return tables_match(expected, {"columns": output.result.columns, "rows": output.result.rows})


@dataclass
class TableMatches(Evaluator[dict, AnalysisReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, AnalysisReport, dict]) -> float:
        return score(ctx.expected_output, ctx.output)
```

In `load_cases`, add the caller to the inputs (keep every other key as it is):

```python
        inputs={"csv": str((cases_dir / spec["csv"]).resolve()), "question": spec["question"], "brief": spec.get("brief"),
                "caller": spec.get("caller", "person")},
```

In `main`, add the options and the model sentinel:

```python
    parser.add_argument("--caller", choices=["person", "program"], default=None,
                        help="run every case as this caller instead of the case's own")
```

and, where the agents are created:

```python
    from vis_agent.providers import litellm_model

    def model_for(name: str):
        return litellm_model() if name == "litellm" else name

    profiler = create_profiler(model_for(profiler_model))
    analyst = create_analyst(model_for(model))
```

In `print_mismatch`, before the `table` branch, add:

```python
    if case.expected_output["expect"] == "answer":
        if output.clarification is not None:
            print(f"{case.name}: asked instead of answering: {output.clarification.question}")
        elif output.analysis is None:
            print(f"{case.name}: no analysis: {output.warnings}")
        return
```

The `task` function does not pass the caller yet; Task 2 adds `caller=args.caller or inputs["caller"]` once `analyze_dataset` accepts it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/analyst/test_eval.py -q`
Expected: PASS.

- [ ] **Step 6: Record the baseline on both models**

Run, with `OPENROUTER_API_KEY` and the LiteLLM variables set in `.env`:

```bash
uv run python -m evals.analyst.run --cases program --mismatches --out outputs/program/baseline-openrouter
```

```bash
uv run python -m evals.analyst.run --cases program --model litellm --profiler-model litellm --mismatches --out outputs/program/baseline-litellm
```

Create `docs/phase-7-lessons.md` with the two "answered without a question" counts and the list of questions asked, under a heading `## Baseline (before Task 2)`. `outputs/` is ignored by git; the lessons file is the record.

- [ ] **Step 7: Commit**

```bash
git add evals/analyst/program evals/analyst/run.py tests/analyst/test_eval.py docs/phase-7-lessons.md
git commit -m "Add the program-caller analyst evaluation set and its baseline"
```

---

### Task 2: The analyst is told who is asking

**Files:**
- Modify: `vis_agent/models.py:9` (after `Intent`), `vis_agent/requests/models.py:22-36` (`Caller`), `vis_agent/analyst/agent.py:25,36-38,72-81,150-156,226-235,266-290`, `vis_agent/requests/runner.py:218-226`, `evals/analyst/run.py` (the `task` function)
- Create: `vis_agent/analyst/rulebook-program.md`
- Test: `tests/analyst/test_agent.py`, `tests/requests/test_runner.py`, `tests/requests/test_store.py`

**Interfaces:**
- Produces: `vis_agent.models.CallerRole = Literal["person", "program"]`; `Caller.role` property; `AnalystPrompt.caller: CallerRole`; `build_prompt(..., caller="person")`; `analyze_dataset(..., caller="person")`; `PROGRAM_INSTRUCTIONS` in `vis_agent/analyst/agent.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/requests/test_store.py`:

```python
def test_a_caller_role_is_program_only_on_the_agent_channel():
    from vis_agent.requests.models import Caller
    assert Caller(kind="agent", identity="reporter").role == "program"
    assert Caller(kind="chat", conversation_id="c1").role == "person"
    assert Caller(kind="terminal").role == "person"
```

Append to `tests/analyst/test_agent.py`:

```python
def test_program_rules_reach_the_model_only_for_a_program_caller(store, people, agents):
    dataset, profile = people
    _profiler, analyst = agents
    seen = {}

    def drive(messages, info):
        seen["instructions"] = info.instructions
        return tool_call("ask_clarification", question="Which amount?", reason="Checking the instructions.")

    for caller, expected in ("person", False), ("program", True):
        prompt = build_prompt(store, profile, "Total amount by region", "English", caller=caller)
        assert ('"caller"' in prompt_json(prompt)) is expected
        with analyst.override(model=FunctionModel(drive)):
            asyncio.run(analyst.run(prompt_json(prompt), deps=AnalystDeps(store=store, profile=profile, prompt=prompt)))
        assert ("The caller is a program" in seen["instructions"]) is expected
```

Append to `tests/requests/test_runner.py`:

```python
PROGRAM = Caller(kind="agent", identity="report-agent")


def test_a_program_caller_is_named_to_the_analyst(deps, dataset_id, fake_models, fake_render, agents):
    _profiler, analyst, _designer, _lead = agents
    from tests.requests.conftest import analyst_drive
    seen = {}

    def analyst_sees(messages, info):
        seen["caller"] = prompt_of(messages).get("caller")
        return analyst_drive(messages, info)

    with analyst.override(model=FunctionModel(analyst_sees)):
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=PROGRAM)
        assert run(run_request(deps, request.request_id)).status == "done"
        assert seen["caller"] == "program"
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
        assert run(run_request(deps, request.request_id)).status == "done"
        assert seen["caller"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/requests/test_store.py tests/analyst/test_agent.py tests/requests/test_runner.py -q -k "program or caller_role"`
Expected: FAIL with `AttributeError: 'Caller' object has no attribute 'role'` and `TypeError: build_prompt() got an unexpected keyword argument 'caller'`.

- [ ] **Step 3: Add the shared role and the caller's property**

In `vis_agent/models.py`, after the `Intent` line:

```python
CallerRole = Literal["person", "program"]
"""Who a specialist works for in a run: a person in the chat or terminal, or a program on the agent channel."""
```

In `vis_agent/requests/models.py`, import it and add the property to `Caller`:

```python
from vis_agent.models import CallerRole
```

```python
    @property
    def role(self) -> CallerRole:
        """What the specialists are told: a program cannot choose a presentation or confirm a fact; a person can."""
        return "program" if self.kind == "agent" else "person"
```

- [ ] **Step 4: Write the program rules**

Create `vis_agent/analyst/rulebook-program.md`:

```markdown
## The caller is a program

The caller is another program, not a person. It sent the question and the brief, and it cannot answer a
question about presentation or preference, and it cannot confirm what the brief says. So:
- When two readings are both defensible, decide: use the measure the table already holds, keep codes as
  they are, keep every measure the question names, and record each choice under assumptions in one
  sentence.
- Never ask whether to show a chart or a table, whether to relabel codes, how many rows to show, whether
  to show counts beside a percentage, or which of two presentations the caller prefers. Those are the
  designer's decisions, and the designer sees your assumptions.
- Never ask the caller to confirm the brief. What the brief's query and caveats state is the definition of
  the table; use it, and cite it in the summary.
- Ask only when a column the question needs is absent from the table, or when a term in the question has
  no definition anywhere: not in the question, not in the brief, not in the column meanings.
```

- [ ] **Step 5: Carry the role through the analyst**

In `vis_agent/analyst/agent.py`, change the import and add the block:

```python
from vis_agent.models import CallerRole, DataBrief, QuestionAnswer
```

```python
PROGRAM_INSTRUCTIONS = Path(__file__).with_name("rulebook-program.md").read_text(encoding="utf-8")
"""Rules for a program caller, added per run only: a program cannot choose a presentation or confirm a fact."""
```

Add the field to `AnalystPrompt` after `previous`:

```python
    caller: CallerRole = "person"
```

Change `build_prompt`'s signature and its return:

```python
def build_prompt(
    store: DatasetStore, profile: DatasetProfile, question: str, language: str,
    clarifications: list[QuestionAnswer] | None = None, previous: PreviousAnalysis | None = None,
    caller: CallerRole = "person",
) -> AnalystPrompt:
```

```python
    return AnalystPrompt(table=table, row_count=profile.deterministic.row_count, columns=columns,
                         question=question, language=language, brief=profile.source.brief,
                         clarifications=list(clarifications or []), previous=previous, caller=caller)
```

Replace `prompt_json`:

```python
def prompt_json(prompt: AnalystPrompt) -> str:
    """The prompt as the model sees it. Empty answers, an absent previous analysis, and a person as the caller are
    left out, so ordinary runs are unchanged."""
    exclude = {name for name in ("clarifications", "previous") if not getattr(prompt, name)}
    if prompt.caller == "person":
        exclude.add("caller")
    return prompt.model_dump_json(exclude=exclude or None)
```

In `create_analyst`, after `revise_rules`:

```python
    @agent.instructions
    def program_rules(ctx: RunContext[AnalystDeps]) -> str | None:
        return PROGRAM_INSTRUCTIONS if ctx.deps.prompt.caller == "program" else None
```

In `analyze_dataset`, add the parameter after `language` and pass it on:

```python
    language: str | None = None,
    caller: CallerRole = "person",
) -> AnalysisReport:
```

```python
    prompt = await asyncio.to_thread(build_prompt, store, profile, question, language,
                                     clarifications=clarifications, previous=previous, caller=caller)
```

- [ ] **Step 6: Pass the role from the runner and the evaluation**

In `vis_agent/requests/runner.py`, in `analyze`:

```python
    report = await analyze_dataset(deps.store, deps.profiler, deps.analyst, request.dataset_id, question,
                                   usage=usage, clarifications=pairs(request), previous=previous,
                                   language=request.language, caller=request.caller.role)
```

In `evals/analyst/run.py`, in `task`:

```python
            report = await analyze_dataset(store, profiler, analyst, source.dataset_id, inputs["question"],
                                           caller=args.caller or inputs["caller"])
```

- [ ] **Step 7: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/requests/test_store.py tests/analyst/test_agent.py tests/requests/test_runner.py -q -k "program or caller_role"`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS; a person's prompt JSON has no `caller` key, so no existing assertion changes.

- [ ] **Step 8: Commit**

```bash
git add vis_agent/models.py vis_agent/requests/models.py vis_agent/analyst/agent.py vis_agent/analyst/rulebook-program.md vis_agent/requests/runner.py evals/analyst/run.py tests/requests/test_store.py tests/analyst/test_agent.py tests/requests/test_runner.py
git commit -m "Tell the analyst who is asking: a program caller gets its own rules"
```

---

### Task 3: The designer is told who is asking

**Files:**
- Modify: `vis_agent/designer/agent.py:23,38-40,71-87,112-147,265-268,318-340`, `vis_agent/requests/runner.py:240-251`
- Create: `vis_agent/designer/rulebook-program.md`
- Test: `tests/designer/test_agent.py`, `tests/requests/test_runner.py`

**Interfaces:**
- Consumes: `CallerRole`, `Caller.role` from Task 2.
- Produces: `DesignerPrompt.caller`; `build_prompt(report, brief, clarifications=None, previous=None, caller="person")`; `design_chart(..., caller="person")`; `PROGRAM_INSTRUCTIONS` in `vis_agent/designer/agent.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/designer/test_agent.py` (add `prompt_json` to the existing import from `vis_agent.designer.agent`):

```python
def test_program_rules_reach_the_designer_only_for_a_program_caller():
    seen = {}

    def drive(messages, info):
        seen["instructions"] = info.instructions
        return tool_call("ask_clarification", question="Which colors can I use?", reason="The colors lack contrast.")

    for caller, expected in ("person", False), ("program", True):
        result = run(report(*gender_share()), FunctionModel(drive), caller=caller)
        assert result.clarification is not None
        assert ("The caller is a program" in seen["instructions"]) is expected
    assert '"caller"' not in prompt_json(build_prompt(report(*gender_share()), None))
    assert '"caller":"program"' in prompt_json(build_prompt(report(*gender_share()), None, caller="program"))
```

Extend `test_a_program_caller_is_named_to_the_analyst` in `tests/requests/test_runner.py` into both specialists (rename it `test_a_program_caller_is_named_to_the_specialists`):

```python
def test_a_program_caller_is_named_to_the_specialists(deps, dataset_id, fake_models, fake_render, agents):
    _profiler, analyst, designer, _lead = agents
    from tests.requests.conftest import analyst_drive, designer_drive
    seen = {}

    def analyst_sees(messages, info):
        seen["analyst"] = prompt_of(messages).get("caller")
        return analyst_drive(messages, info)

    def designer_sees(messages, info):
        seen["designer"] = prompt_of(messages).get("caller")
        return designer_drive(messages, info)

    with analyst.override(model=FunctionModel(analyst_sees)), designer.override(model=FunctionModel(designer_sees)):
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=PROGRAM)
        assert run(run_request(deps, request.request_id)).status == "done"
        assert seen == {"analyst": "program", "designer": "program"}
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
        assert run(run_request(deps, request.request_id)).status == "done"
        assert seen == {"analyst": None, "designer": None}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/designer/test_agent.py tests/requests/test_runner.py -q -k program`
Expected: FAIL with `TypeError: design_chart() got an unexpected keyword argument 'caller'`.

- [ ] **Step 3: Write the designer's program rules**

Create `vis_agent/designer/rulebook-program.md`:

```markdown
## The caller is a program

The caller is another program. It cannot answer a question about colours, chart type, or layout, and it
cannot supply data the result lacks. Deliver the best chart the catalogue allows for this result and say in
the explanation what you decided and why. This overrides the rule to ask when the result lacks a requested
group or period: deliver what the result supports and name the missing detail in the explanation instead.
Ask only when the requested colours cannot meet the contrast rule.
```

- [ ] **Step 4: Carry the role through the designer**

In `vis_agent/designer/agent.py`:

```python
from vis_agent.models import CallerRole, DataBrief, Intent, QuestionAnswer
```

```python
PROGRAM_INSTRUCTIONS = Path(__file__).with_name("rulebook-program.md").read_text(encoding="utf-8")
"""Rules for a program caller, added per run only."""
```

Add to `DesignerPrompt` after `previous`:

```python
    caller: CallerRole = "person"
```

Change `build_prompt`'s signature and its return:

```python
def build_prompt(
    report: AnalysisReport, brief: DataBrief | None,
    clarifications: list[QuestionAnswer] | None = None, previous: PreviousDesign | None = None,
    caller: CallerRole = "person",
) -> DesignerPrompt:
```

```python
        clarifications=list(clarifications or []), previous=previous, caller=caller,
    )
```

Replace `prompt_json`:

```python
def prompt_json(prompt: DesignerPrompt) -> str:
    """The prompt as the model sees it. Empty answers, an absent previous design, and a person as the caller are
    left out, so ordinary runs are unchanged."""
    exclude = {name for name in ("clarifications", "previous") if not getattr(prompt, name)}
    if prompt.caller == "person":
        exclude.add("caller")
    return prompt.model_dump_json(exclude=exclude or None)
```

In `create_designer`, after `revise_rules`:

```python
    @agent.instructions
    def program_rules(ctx: RunContext[DesignerDeps]) -> str | None:
        return PROGRAM_INSTRUCTIONS if ctx.deps.prompt.caller == "program" else None
```

In `design_chart`, add the parameter after `previous` and pass it on:

```python
    previous: PreviousDesign | None = None,
    caller: CallerRole = "person",
) -> DesignReport:
```

```python
    prompt = build_prompt(report, brief, clarifications=clarifications, previous=previous, caller=caller)
```

- [ ] **Step 5: Pass the role from the runner**

In `vis_agent/requests/runner.py`, in `design`, both calls:

```python
    designed = await design_chart(report, deps.designer, brief, usage=usage, clarifications=pairs(request),
                                  previous=previous, caller=request.caller.role)
```

```python
        designed = await design_chart(report, deps.designer_fallback, brief, usage=usage,
                                      clarifications=pairs(request), previous=previous, caller=request.caller.role)
```

- [ ] **Step 6: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/designer/test_agent.py tests/requests/test_runner.py -q -k program`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add vis_agent/designer/agent.py vis_agent/designer/rulebook-program.md vis_agent/requests/runner.py tests/designer/test_agent.py tests/requests/test_runner.py
git commit -m "Tell the designer who is asking: a program caller gets no presentation questions"
```

---

### Task 4: The table is a query result

**Files:**
- Create: `vis_agent/analyst/rulebook-query-result.md`
- Modify: `vis_agent/analyst/agent.py` (constant and instructions function), `vis_agent/profiler/rulebook.md:54-57`, `vis_agent/designer/rulebook.md` (the "Filling the spec" list)
- Test: `tests/analyst/test_agent.py`

**Interfaces:**
- Produces: `QUERY_RESULT_INSTRUCTIONS` in `vis_agent/analyst/agent.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/analyst/test_agent.py`:

```python
def test_query_result_rules_reach_the_model_only_when_the_brief_carries_the_query(store, people, agents):
    dataset, profile = people
    _profiler, analyst = agents
    seen = {}

    def drive(messages, info):
        seen["instructions"] = info.instructions
        return tool_call("ask_clarification", question="Which amount?", reason="Checking the instructions.")

    briefs = [(None, False), (DataBrief(raw_question="Totals"), False),
              (DataBrief(query="SELECT region, sum(amount) FROM t GROUP BY 1", producer_agent="insightor"), True)]
    for brief, expected in briefs:
        with_brief = profile.model_copy(update={"source": profile.source.model_copy(update={"brief": brief})})
        prompt = build_prompt(store, with_brief, "Total amount by region", "English")
        with analyst.override(model=FunctionModel(drive)):
            asyncio.run(analyst.run(prompt_json(prompt), deps=AnalystDeps(store=store, profile=with_brief, prompt=prompt)))
        assert ("The table is a query result" in seen["instructions"]) is expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/analyst/test_agent.py -q -k query_result`
Expected: FAIL on the third brief: the instructions never contain the heading.

- [ ] **Step 3: Write the query-result rules**

Create `vis_agent/analyst/rulebook-query-result.md`:

```markdown
## The table is a query result

The brief carries the query that produced this table (brief.query), run by brief.producer_agent. Every
row is one group of that query and every number was computed there. Read each column's definition from
its alias and expression in that SQL. Read the filters, the period, and any LIMIT from its WHERE and LIMIT
clauses: they are the table's scope. State that scope in the summary when it narrows the question.
Never ask the caller to confirm what the query states, and never re-derive a number the table already
holds: a percentage column and its numerator and denominator columns are all final. When the question
names a filter the query already applied, the whole table is the filtered set; select from it without
adding the filter again.
```

- [ ] **Step 4: Add the block to the analyst**

In `vis_agent/analyst/agent.py`, after `PROGRAM_INSTRUCTIONS`:

```python
QUERY_RESULT_INSTRUCTIONS = Path(__file__).with_name("rulebook-query-result.md").read_text(encoding="utf-8")
"""Rules for a table that a data agent's query produced, added per run only when the brief carries that query."""
```

In `create_analyst`, after `program_rules`:

```python
    @agent.instructions
    def query_result_rules(ctx: RunContext[AnalystDeps]) -> str | None:
        brief = ctx.deps.prompt.brief
        return QUERY_RESULT_INSTRUCTIONS if brief is not None and brief.query else None
```

- [ ] **Step 5: Teach the profiler and the designer the same fact**

In `vis_agent/profiler/rulebook.md`, after the paragraph that starts "The brief is context, never fact.", add:

```markdown
When the brief carries query, the table is that query's result: read each column's meaning from its alias
and expression in the SQL, take the unit the expression implies (a COUNT is a count of the thing counted,
a ROUND(... * 100.0 / ...) is a percentage), and give code_meanings for codes the query names, such as F
and M under gender. The query's WHERE and LIMIT clauses are the table's scope; say so in description.
```

In `vis_agent/designer/rulebook.md`, add as the first bullet of "Filling the spec:":

```markdown
- Titles, subtitles, and descriptions say what the analyst's column meanings and assumptions say the
  numbers are, in the caller's language. When an assumption says the data meets a different condition
  than the question's wording (three or more exits in any one year, not every year), the title follows the
  assumption, never the question.
```

- [ ] **Step 6: Run the test to verify it passes, then the whole suite**

Run: `uv run pytest tests/analyst/test_agent.py -q -k query_result`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS (`tests/designer/test_agent.py::test_grammar_and_instructions` reads the rulebook text; it must still pass).

- [ ] **Step 7: Commit**

```bash
git add vis_agent/analyst/agent.py vis_agent/analyst/rulebook-query-result.md vis_agent/profiler/rulebook.md vis_agent/designer/rulebook.md tests/analyst/test_agent.py
git commit -m "Treat a table with its producing query as a finished result, not data to re-derive"
```

---

### Task 5: The ask tools refuse an echo and a repeat

**Files:**
- Modify: `vis_agent/analyst/agent.py:226-235` (`ask_clarification`), `vis_agent/designer/agent.py:314-317` (`ask_clarification`)
- Test: `tests/analyst/test_agent.py`, `tests/designer/test_agent.py`, `tests/requests/test_runner.py`

**Interfaces:**
- Produces: `vis_agent.analyst.agent.normalized_question(text: str) -> str`, used by both guards.

- [ ] **Step 1: Write the failing tests**

Append to `tests/analyst/test_agent.py`:

```python
GOOD_COLUMNS = [{"name": "region", "meaning": "Region", "kind": "geography", "source": "region"},
                {"name": "total", "meaning": "Sum of amount", "kind": "measure", "source": "amount", "aggregate": "sum",
                 "unit": "SAR"}]


def _retries(messages):
    return [p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]


def _returns(messages):
    return [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]


def test_an_echo_of_the_question_is_sent_back_once_then_the_run_proceeds(store, people, agents):
    dataset, profile = people
    _profiler, analyst = agents
    question = "Total amount by region"
    prompt = build_prompt(store, profile, question, "English")
    deps = AnalystDeps(store=store, profile=profile, prompt=prompt)
    sql = f'SELECT region, sum(amount) AS total FROM "{dataset}" GROUP BY 1 ORDER BY 2 DESC'

    def drive(messages, info):
        if not _retries(messages):
            return tool_call("ask_clarification", question=f"  {question}? ", reason="This is exactly what the table provides.")
        if not _returns(messages):
            return tool_call("run_query", sql=sql, columns=GOOD_COLUMNS)
        return tool_call("deliver_analysis", summary="West leads with 65.")

    with analyst.override(model=FunctionModel(drive)):
        result = asyncio.run(analyst.run(prompt_json(prompt), deps=deps))
    assert isinstance(result.output, Analysis)
    assert "caller's own question" in str(_retries(result.all_messages())[0].content)


def test_a_question_the_caller_answered_is_not_asked_again(store, people, agents):
    from vis_agent.models import QuestionAnswer
    dataset, profile = people
    _profiler, analyst = agents
    prompt = build_prompt(store, profile, "Total amount by region", "English",
                          clarifications=[QuestionAnswer(question="Which amount?", answer="The amount column")])
    deps = AnalystDeps(store=store, profile=profile, prompt=prompt)
    sql = f'SELECT region, sum(amount) AS total FROM "{dataset}" GROUP BY 1 ORDER BY 2 DESC'

    def drive(messages, info):
        if not _retries(messages):
            return tool_call("ask_clarification", question="which amount", reason="Still unsure.")
        if not _returns(messages):
            return tool_call("run_query", sql=sql, columns=GOOD_COLUMNS)
        return tool_call("deliver_analysis", summary="West leads with 65.")

    with analyst.override(model=FunctionModel(drive)):
        result = asyncio.run(analyst.run(prompt_json(prompt), deps=deps))
    assert isinstance(result.output, Analysis)
    assert "already answered" in str(_retries(result.all_messages())[0].content)


def test_a_model_that_only_echoes_ends_within_the_output_retries(store, people, agents):
    dataset, _profile = people
    profiler, analyst = agents
    question = "Total amount by region"
    usage = RunUsage()

    def echo(messages, info):
        return tool_call("ask_clarification", question=question, reason="Exactly what the table provides.")

    with analyst.override(model=FunctionModel(echo)):
        report = asyncio.run(analyze_dataset(store, profiler, analyst, dataset, question, usage=usage))
    assert report.analysis is None and report.clarification is None
    assert report.warnings and "could not answer" in report.warnings[0]
    assert usage.requests == 3
```

Append to `tests/designer/test_agent.py`:

```python
def test_an_echo_of_the_question_is_sent_back_before_a_design_is_accepted():
    source = report(*gender_share(), question="Share by gender?")

    def drive(messages, info):
        if not retries(messages):
            return tool_call("ask_clarification", question="share by gender", reason="I will draw it now.")
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return tool_call("recommend_charts", intent="share")
        if len(returns) == 1:
            return tool_call("check_spec", spec=DONUT)
        return tool_call("deliver_design", spec=returns[-1].model_response_object()["canonical"], explanation=EXPLANATION)

    result = run(source, FunctionModel(drive))
    assert result.design is not None and result.design.chart == "donut"
```

Append to `tests/requests/test_runner.py`:

```python
def test_a_request_whose_analyst_only_echoes_fails_instead_of_waiting(deps, dataset_id, fake_models, agents):
    _profiler, analyst, _designer, _lead = agents

    def echo(messages, info):
        return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification",
                                                 args={"question": "Total by region", "reason": "I will now summarize."})])

    with analyst.override(model=FunctionModel(echo)):
        request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=PROGRAM)
        outcome = run(run_request(deps, request.request_id))
    assert outcome.status == "failed" and outcome.clarification is None
    assert "could not answer" in outcome.error
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/analyst/test_agent.py tests/designer/test_agent.py tests/requests/test_runner.py -q -k "echo or answered"`
Expected: FAIL: the echo is accepted as a `Clarification`, so the analyst tests see no `RetryPromptPart` and the runner test sees `waiting`.

- [ ] **Step 3: Guard the analyst's ask tool**

In `vis_agent/analyst/agent.py`, replace `ask_clarification` and add the helper above it:

```python
def normalized_question(text: str) -> str:
    """Whitespace, case, and end punctuation do not make a different question."""
    return " ".join(text.split()).casefold().strip(" ?؟.!")


def ask_clarification(ctx: RunContext[AnalystDeps], question: str, reason: str) -> Clarification:
    """Ask the caller one question, in the caller's language, when the columns cannot answer the question or a
    term in it has no definition. Say in reason what is missing.
    """
    if not question.strip():
        raise ModelRetry("The question is empty. Ask one question the caller can answer, or answer with SQL.")
    prompt = ctx.deps.prompt
    asked = normalized_question(question)
    if asked == normalized_question(prompt.question):
        raise ModelRetry("That is the caller's own question, not a clarification. If the columns answer it, call "
                         "run_query and deliver; if a column or a definition is missing, ask for that one thing.")
    if any(asked == normalized_question(pair.question) for pair in prompt.clarifications):
        raise ModelRetry("The caller already answered that question; the answer is in clarifications. Use it and "
                         "deliver, or ask about something else that is missing.")
    return Clarification(question=question, reason=reason)
```

- [ ] **Step 4: Guard the designer's ask tool**

In `vis_agent/designer/agent.py`, change the import from the analyst and replace `ask_clarification`:

```python
from vis_agent.analyst.agent import ARABIC, normalized_question
```

```python
def ask_clarification(ctx: RunContext[DesignerDeps], question: str, reason: str) -> Clarification:
    """Ask one question in the caller's language when the result or requested colors cannot support the chart."""
    if not question.strip():
        raise ModelRetry("The question is empty. Ask one question the caller can answer, or deliver a design.")
    asked = normalized_question(question)
    if asked == normalized_question(ctx.deps.report.question):
        raise ModelRetry("That is the caller's own question, not a clarification. Deliver the best chart the "
                         "catalogue allows, or ask about the one detail the result lacks.")
    if any(asked == normalized_question(pair.question) for pair in ctx.deps.prompt.clarifications):
        raise ModelRetry("The caller already answered that question; the answer is in clarifications. Use it and "
                         "deliver, or ask about something else.")
    return Clarification(question=question, reason=reason)
```

- [ ] **Step 5: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/analyst/test_agent.py tests/designer/test_agent.py tests/requests/test_runner.py -q -k "echo or answered"`
Expected: PASS. The echo-only run makes exactly 3 model requests: two output retries, then `UnexpectedModelBehavior`, which `analyze_dataset` records as a warning and the runner turns into `failed`.

Run: `uv run pytest -q`
Expected: PASS. The existing tests ask "Which amount?" or "Which region should I count?" against a different question, which the guard accepts unchanged.

- [ ] **Step 6: Commit**

```bash
git add vis_agent/analyst/agent.py vis_agent/designer/agent.py tests/analyst/test_agent.py tests/designer/test_agent.py tests/requests/test_runner.py
git commit -m "Refuse a clarification that echoes the question or repeats an answered one"
```

---

### Task 6: Single-letter codes stay text at import

**Files:**
- Modify: `vis_agent/store.py:142-147`, `vis_agent/profiler/models.py:10`, `tests/test_models.py:16`, `tests/profiler/test_profiling.py:112,240`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_single_letter_codes_and_yes_no_text_stay_text_at_import(store):
    from vis_agent.profiler.measurements import compute_statistics
    from vis_agent.store import quote_identifier
    content = (b"id,gender,flag,amount,day,empty\n"
               b"1,F,Y,10.5,2026-01-01,\n"
               b"2,F,N,3,2026-02-01,\n")
    source = store.save_upload("codes.csv", content)
    store.import_csv(source.dataset_id)
    with store.connect() as connection:
        types = {name: kind for name, kind, *_ in
                 connection.execute(f"DESCRIBE {quote_identifier(store.table_name(source.dataset_id))}").fetchall()}
    assert types["gender"] == "VARCHAR" and types["flag"] == "VARCHAR"
    assert types["id"] == "BIGINT" and types["amount"] == "DOUBLE" and types["day"] == "DATE"
    statistics = compute_statistics(store, source)
    by_name = {column.name: column for column in statistics.columns}
    assert by_name["gender"].codes == ["F"]
    assert by_name["empty"].null_count == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_store.py -q -k single_letter`
Expected: FAIL: `types["gender"] == "BOOLEAN"`.

- [ ] **Step 3: Drop BOOLEAN from the import's type candidates**

In `vis_agent/store.py`, `import_csv`:

```python
            # BOOLEAN is not a candidate: a column of single-letter codes such as F must stay text. Yes/no text is
            # still recognised by the measurements' boolean vocabulary.
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {table} AS "
                "SELECT * FROM read_csv(?, header=true, delim=',', sample_size=-1, "
                "strict_mode=true, null_padding=false, parallel=false, "
                "auto_type_candidates=['BIGINT', 'DOUBLE', 'TIME', 'DATE', 'TIMESTAMP', 'VARCHAR'])",
                [str(path)],
            )
```

- [ ] **Step 4: Raise the profile version so cached profiles rebuild**

In `vis_agent/profiler/models.py`:

```python
PROFILE_VERSION = "2.1"
```

Update the three assertions that pin it: `tests/test_models.py:16` to `assert PROFILE_VERSION == "2.1"`, and `tests/profiler/test_profiling.py:112` and `:240` to `"2.1"`. Tables imported before this change keep their types: `CREATE TABLE IF NOT EXISTS` never re-imports.

- [ ] **Step 5: Run the test to verify it passes, then the whole suite**

Run: `uv run pytest tests/test_store.py -q -k single_letter`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS. If a profiler test expected a BOOLEAN physical type for a true/false column, change its expectation to VARCHAR with `boolean_vocabulary == ["false", "true"]`.

- [ ] **Step 6: Commit**

```bash
git add vis_agent/store.py vis_agent/profiler/models.py tests/test_store.py tests/test_models.py tests/profiler/test_profiling.py
git commit -m "Import single-letter codes as text: BOOLEAN is no longer inferred from a CSV"
```

---

### Task 7: Units and code meanings in the caller's language, and a declared unit is kept

**Files:**
- Modify: `vis_agent/profiler/rulebook.md:56-57`, `vis_agent/analyst/checks.py` (new helper, called before the final `return checks` of `check_result`)
- Test: `tests/analyst/test_checks.py`

**Interfaces:**
- Produces: `vis_agent.analyst.checks.unit_kept_checks(profile: DatasetProfile, columns: list[ResultColumn]) -> list[ProfileCheck]`; check name `unit_kept_from_brief`, severity `error`.

- [ ] **Step 1: Write the failing test**

Append to `tests/analyst/test_checks.py`:

```python
def test_a_unit_the_brief_declared_must_be_kept_on_a_measure_taken_from_that_column(store, people):
    from vis_agent.analyst.checks import unit_kept_checks
    from vis_agent.analyst.models import ResultColumn
    from vis_agent.models import DataBrief
    _dataset, profile = people
    declared = profile.model_copy(update={"source": profile.source.model_copy(update={"brief": DataBrief(units={"amount": "SAR"})})})
    dropped = ResultColumn(name="total", meaning="Total", kind="measure", source="amount", aggregate="sum")
    kept = dropped.model_copy(update={"unit": "SAR"})
    counted = ResultColumn(name="n", meaning="Rows", kind="measure", source="amount", aggregate="count")
    computed = ResultColumn(name="ratio", meaning="Ratio", kind="measure", source=None)
    failed = unit_kept_checks(declared, [dropped])
    assert [c.check for c in failed] == ["unit_kept_from_brief"] and failed[0].severity == "error"
    assert "'SAR'" in failed[0].message
    assert unit_kept_checks(declared, [kept, counted, computed]) == []
    assert unit_kept_checks(profile, [dropped]) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/analyst/test_checks.py -q -k unit_kept`
Expected: FAIL with `ImportError: cannot import name 'unit_kept_checks'`.

- [ ] **Step 3: Add the check**

In `vis_agent/analyst/checks.py`, before `check_result`:

```python
KEEPS_UNIT = ("none", "sum", "min", "max", "avg")


def unit_kept_checks(profile: DatasetProfile, columns: list[ResultColumn]) -> list[ProfileCheck]:
    """A unit the data agent declared in the brief stays on a measure taken from that column: a null unit drops it
    from every label on the picture. A count of rows and a calculation over several columns have their own unit."""
    brief = profile.source.brief
    if brief is None or not brief.units:
        return []
    checks: list[ProfileCheck] = []
    for column in columns:
        declared = brief.units.get(column.source) if column.source else None
        if column.kind == "measure" and column.unit is None and declared and column.aggregate in KEEPS_UNIT:
            checks.append(_check(column.name, "unit_kept_from_brief", "error", False,
                                 f"{column.name}: the brief declares unit {declared!r} for its source column "
                                 f"{column.source}; carry it, or state the unit the calculation produces."))
    return checks
```

In `check_result`, immediately before its final `return checks` (the one after the ordinal and time checks, not the two early returns):

```python
    checks.extend(unit_kept_checks(profile, columns))
    return checks
```

- [ ] **Step 4: Teach the profiler the language of units and evident codes**

In `vis_agent/profiler/rulebook.md`, replace the two lines

```
Write description and row_meaning in the language of the brief's raw_question when there is one,
otherwise in the language of the column names.
```

with

```
Write meaning, description, row_meaning, and every count-noun unit (person, order, job, and their Arabic
forms) in the language of the brief's raw_question when there is one, otherwise in the language of the
column names; symbols such as % and currency codes stay as they are. Give code_meanings for codes whose
meaning is plain from the header or the brief, such as F and M under gender, and leave code_meanings null
when it is not.
```

- [ ] **Step 5: Run the test to verify it passes, then the whole suite**

Run: `uv run pytest tests/analyst/test_checks.py -q -k unit_kept`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS: no fixture declares brief units, so no existing drive trips the new check.

- [ ] **Step 6: Commit**

```bash
git add vis_agent/analyst/checks.py vis_agent/profiler/rulebook.md tests/analyst/test_checks.py
git commit -m "Keep a unit the brief declared, and write units and code meanings in the caller's language"
```

---

### Task 8: The subtitle carries the scope, and the lineage carries the provenance

**Files:**
- Modify: `vis_agent/designer/rulebook.md` (the "Filling the spec" list), `vis_agent/requests/models.py:114-123` (`Lineage`), `vis_agent/requests/runner.py` (`deliver`)
- Test: `tests/requests/test_runner.py`

**Interfaces:**
- Produces: `Lineage.source`, `Lineage.query`, `Lineage.pulled_at`, `Lineage.producer_agent`, all optional.

- [ ] **Step 1: Write the failing test**

Append to `tests/requests/test_runner.py` (add `from datetime import datetime, timezone` and `from tests.requests.conftest import SALES` to the imports):

```python
def test_the_lineage_carries_the_briefs_provenance(deps, store, fake_models, fake_render):
    from vis_agent.models import DataBrief
    brief = DataBrief(source="insightor", query="SELECT region, sum(amount) FROM t GROUP BY 1",
                      producer_agent="insightor", pulled_at=datetime(2026, 9, 15, tzinfo=timezone.utc))
    dataset_id = store.save_upload("sales.csv", SALES, brief).dataset_id
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CHAT)
    outcome = run(run_request(deps, request.request_id))
    lineage = deps.requests.get_artifact(outcome.artifact.artifact_id).lineage
    assert lineage.query == brief.query and lineage.producer_agent == "insightor" and lineage.source == "insightor"
    assert lineage.pulled_at == brief.pulled_at
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/requests/test_runner.py -q -k provenance`
Expected: FAIL with `AttributeError: 'Lineage' object has no attribute 'query'`.

- [ ] **Step 3: Add the fields and fill them at delivery**

In `vis_agent/requests/models.py`, `Lineage`, after `designer_model`:

```python
    source: str | None = None
    query: str | None = None
    pulled_at: datetime | None = None
    producer_agent: str | None = None
    """Where the data came from, copied from the brief the data agent sent with the upload."""
```

In `vis_agent/requests/runner.py`, in `deliver`, before `artifact = Artifact(`:

```python
    brief = (await asyncio.to_thread(deps.store.get_upload, request.dataset_id)).brief
```

and in the `Lineage(...)` call, after `designer_model=...`:

```python
                        source=brief.source if brief else None, query=brief.query if brief else None,
                        pulled_at=brief.pulled_at if brief else None,
                        producer_agent=brief.producer_agent if brief else None),
```

- [ ] **Step 4: Give the designer the subtitle rule**

In `vis_agent/designer/rulebook.md`, add to "Filling the spec:" after the title bullet from Task 4:

```markdown
- The subtitle carries the scope when it narrows the question: the period, the filter, a LIMIT, or a
  definition that differs from the question's wording, taken from the analyst's assumptions or the
  brief's caveats, in one clause. Leave the subtitle out when nothing narrows the question. Indicators put
  the same clause in description, which the card prints as its footnote.
```

- [ ] **Step 5: Run the test to verify it passes, then the whole suite**

Run: `uv run pytest tests/requests/test_runner.py -q -k provenance`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add vis_agent/requests/models.py vis_agent/requests/runner.py vis_agent/designer/rulebook.md tests/requests/test_runner.py
git commit -m "Carry the brief's provenance in the lineage and the scope in the subtitle"
```

---

### Task 9: The lead runs with thinking off, and the ask route returns what it made

**Files:**
- Modify: `vis_agent/lead.py:246-265` (`create_lead`), `vis_agent/requests/store.py:96-113` (`list_requests`), `vis_agent/requests/api.py:196-211` (`post_ask`)
- Test: `tests/test_agents.py`, `tests/requests/test_store.py`, `tests/requests/test_api.py`

**Interfaces:**
- Produces: `RequestStore.list_requests(..., identity: str | None = None)`; the ask route's JSON gains `"requests": [RequestSummary...]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agents.py`:

```python
def test_the_lead_runs_with_thinking_off(store):
    lead = create_lead("test")
    seen = {}

    def drive(messages, info):
        seen["settings"] = info.model_settings
        return ModelResponse(parts=[TextPart(content="ok")])

    with lead.override(model=FunctionModel(drive)):
        lead.run_sync("hello", deps=AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"), designer=create_designer("test")))
    assert seen["settings"]["thinking"] is False
```

Append to `tests/requests/test_store.py`:

```python
def test_requests_can_be_listed_by_the_callers_identity(deps, dataset_id):
    from vis_agent.requests.models import Caller
    from vis_agent.requests.runner import create_request
    create_request(deps, type="new", dataset_id=dataset_id, question="A", caller=Caller(kind="agent", identity="reporter"))
    create_request(deps, type="new", dataset_id=dataset_id, question="B", caller=Caller(kind="agent", identity="other"))
    assert [s.question for s in deps.requests.list_requests(identity="reporter")] == ["A"]
    assert len(deps.requests.list_requests()) == 2
```

In `tests/requests/test_api.py`, extend the two existing ask tests: after `assert answer.status_code == 200 and answer.json()["answer"] == "I draw charts."` add `assert answer.json()["requests"] == []`; after `assert answer.status_code == 200 and answer.json()["answer"] == "Drawn."` add:

```python
        made = answer.json()["requests"]
        assert len(made) == 1 and made[0]["status"] == "done" and made[0]["artifact_id"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agents.py tests/requests/test_store.py tests/requests/test_api.py -q -k "thinking or identity or ask"`
Expected: FAIL: `KeyError: 'thinking'`, `TypeError: list_requests() got an unexpected keyword argument 'identity'`, `KeyError: 'requests'`.

- [ ] **Step 3: Thinking off for the lead**

In `vis_agent/lead.py`, `create_lead`, add the setting to the `Agent(...)` call after `capabilities=capabilities`:

```python
        # The specialists run with thinking off; the lead too, so a model's reasoning channel never leaks into the
        # text a program receives.
        model_settings={"thinking": False},
```

- [ ] **Step 4: List by identity and return the requests the ask made**

In `vis_agent/requests/store.py`, `list_requests`:

```python
    def list_requests(self, dataset_id: str | None = None, conversation_id: str | None = None,
                      unfinished_only: bool = False, limit: int = 50, identity: str | None = None) -> list[RequestSummary]:
        """Newest first. Unfinished means any status but done. identity narrows to one caller's requests."""
```

and inside the loop, after the `conversation_id` filter:

```python
            if identity and request.caller.identity != identity:
                continue
```

In `vis_agent/requests/api.py`, `post_ask`, record the start and return the requests made since:

```python
        started = now()
        try:
            result = await lead.run(prompt, deps=replace(deps, caller_kind="agent", caller_identity=data.caller.identity),
                                    usage_limits=UsageLimits(request_limit=REQUEST_LIMIT))
        except UsageLimitExceeded:
            return error(f"The question used its budget of {REQUEST_LIMIT} model requests; ask a narrower question.", 400)
        made = [summary.model_dump(mode="json") for summary in
                await asyncio.to_thread(requests_of(deps).list_requests, identity=data.caller.identity, limit=10)
                if summary.created_at >= started]
        return JSONResponse({"answer": result.output, "caller": data.caller.identity, "requests": made})
```

- [ ] **Step 5: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/test_agents.py tests/requests/test_store.py tests/requests/test_api.py -q -k "thinking or identity or ask"`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add vis_agent/lead.py vis_agent/requests/store.py vis_agent/requests/api.py tests/test_agents.py tests/requests/test_store.py tests/requests/test_api.py
git commit -m "Run the lead with thinking off and return the requests an ask made"
```

---

### Task 10: Measure, then record the lessons and the rules

**Files:**
- Modify: `docs/phase-7-lessons.md`, `AGENTS.md` (the rules list), `README.md` (the brief paragraph and the Agent channel section)

- [ ] **Step 1: Run the program set on both models**

```bash
uv run python -m evals.analyst.run --cases program --caller program --mismatches --out outputs/program/after-openrouter
```

```bash
uv run python -m evals.analyst.run --cases program --caller program --model litellm --profiler-model litellm --mismatches --out outputs/program/after-litellm
```

Exit line, per the design: at least 90% answered without a question on the proxy model, no echo and no verbatim repeat in any `--mismatches` line. If the proxy model still echoes past the guard (runs failing with "could not answer" rather than asking), the deferred-tool restructuring in the design's "Later" section is the next plan; record the count either way.

- [ ] **Step 2: Run the seed evaluations to prove ordinary runs are unchanged**

```bash
uv run python -m evals.analyst.run --mismatches
```

```bash
uv run python -m evals.lead.run
```

Expected: the same scores as before Task 2 (70 of 70 analyst tables at the last record; the lead's exit line at least 18 of 21).

- [ ] **Step 3: Write the lessons**

In `docs/phase-7-lessons.md`, add under `## After` a table with the four runs (model × before/after), the count answered without a question, the count that asked, the count that failed, and the questions that remain, each classified as real gap, data-quality catch, or leftover presentation question. Add a `## Confirmed lessons` list with what changed the numbers most.

- [ ] **Step 4: Record the rules**

Append to the rules list in `AGENTS.md`:

```markdown
- The specialists are told who is asking: `Caller.role` is `program` on the agent channel and `person` in the chat and
  terminal; `AnalystPrompt.caller` and `DesignerPrompt.caller` carry it, and `vis_agent/analyst/rulebook-program.md`
  and `vis_agent/designer/rulebook-program.md` reach the model per run only. A person's prompt is unchanged.
- A brief that carries `query` marks the table as a finished query result: `vis_agent/analyst/rulebook-query-result.md`
  reaches the analyst per run only; the profiler reads meanings and code meanings from that query.
- `ask_clarification` refuses, with one ModelRetry, a question that equals the caller's question or one the caller
  already answered. A model that keeps echoing ends within the output retries and the request fails; it never waits.
- CSV import never infers BOOLEAN: single-letter codes such as F stay text; yes/no text is still labelled by the
  measurements' boolean vocabulary. Profiles are version 2.1.
- A unit the brief declares is kept by the analyst (`unit_kept_from_brief`); units and code meanings follow the
  caller's language.
- Run `uv run python -m evals.analyst.run --cases program --caller program` before a merge that touches the analyst's
  rulebooks or the clarification path; `--model litellm --profiler-model litellm` runs it on the proxy.
```

In `README.md`, after the paragraph "The brief is context, never fact...", add:

```markdown
When the brief carries the query that produced the file, the analyst treats the file as that query's finished
result: the SQL defines every column, its WHERE and LIMIT clauses are the scope, and nothing is re-derived or
confirmed with the caller. The artifact's lineage repeats the brief's source, query, pull time, and producer.
```

In the "Agent channel" section, after the paragraph on the return address, add:

```markdown
A request from the channel runs the specialists as a program's request: they decide presentation themselves and
record it under the artifact's assumptions, and they ask only when a column is missing or a term has no definition
anywhere. `/agents/ask` returns, beside the lead's answer, the requests that answer created, with their status and
artifact IDs.
```

- [ ] **Step 5: Run the whole suite and commit**

Run: `uv run pytest -q`
Expected: PASS.

```bash
git add docs/phase-7-lessons.md AGENTS.md README.md
git commit -m "Record the program-caller results and rules"
```

---

## Self-review

- Spec coverage: decision 1 is Tasks 2 and 3; decision 2 is Task 4; decision 3 is Task 5; decision 4 is the repair plan, referenced not repeated; decision 5 is Task 6; decision 6 is Task 7; decision 7 is Task 8; decision 8 is Task 9; decision 9 is Tasks 1 and 10.
- Type consistency: `CallerRole` is defined once in `vis_agent/models.py` and imported by `requests/models.py`, `analyst/agent.py`, and `designer/agent.py`; `normalized_question` lives in `analyst/agent.py` and is imported by the designer; `unit_kept_checks` is the only new check function; `score` is the only new eval function; `Lineage` gains four optional fields.
- Ordinary runs: `prompt_json` in both agents drops `caller` for a person, and every new instruction block returns `None` unless its condition holds, so existing prompt and instruction assertions hold.
