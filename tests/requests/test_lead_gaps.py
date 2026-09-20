"""Reproductions of the flow gaps seen in the Logfire traces of 2026-09-16..19 (analysis branch).

Each test names the trace it reproduces and says what it establishes. The assertions describe what the code does
today; they are evidence, not the desired behaviour. tests/requests/test_lead_gap_fixes.py holds the desired
behaviour for the candidate patches.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import RetryPromptPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from vis_agent.analyst.source import load_csv_report
from vis_agent.designer.agent import build_prompt, create_designer, design_chart
from vis_agent.designer.check import check_render_spec
from vis_agent.designer.models import Design, DesignReport
from vis_agent.designer.resolve import ResolveError, resolve
from vis_agent.designer.syntax import parse
from vis_agent.lead import LEAD_INSTRUCTIONS
from vis_agent.requests.models import Caller
from vis_agent.requests.service import create_request, prepare_request, requests_of
from vis_agent.reviewer.agent import create_reviewer, review_chart

from .conftest import CHART_SPEC, SALES, analyst_drive, call, finish, request_id_of, tool_returns

CHAT = Caller(kind="chat", conversation_id="chat-1")


def returns_of(messages, tool_name):
    return [str(p.content) for p in tool_returns(messages) if p.tool_name == tool_name]


def failed_design(report, *args, **kwargs):
    """What design_chart returns when the designer dies on its two output retries (trace ...b54ec00)."""
    async def run():
        return DesignReport(dataset_id=report.dataset_id, question=report.question, language=report.language,
                            design=None, requests=3, check_calls=1, seconds=1.0,
                            created_at=datetime.now(timezone.utc),
                            warnings=["The designer could not finish: required_columns: the chart omits required "
                                      "result columns city."])
    return run()


# --- 1. Two failed initial designs also close the door on use_fallback -------------------------------------------

def test_two_failed_initial_designs_also_refuse_the_fallback_designer(deps, dataset_id, agents, monkeypatch):
    """Trace 01a0b9c1c45d8af82156c4c80b54ec00: both DeepSeek attempts failed (fold misuse, then an unbindable
    required column that the lead had demanded from the first call on); the cap then refused four more calls,
    the last of which asked for use_fallback=true. Establishes: after two failed initial attempts the fallback
    designer is refused by lead.py, while LEAD_INSTRUCTIONS still name use_fallback=true as the recovery."""
    monkeypatch.setattr("vis_agent.lead.design_chart", failed_design)
    lead = agents[-1]
    assert "use_fallback=true" in LEAD_INSTRUCTIONS

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id=dataset_id, question="Compare the supplied values")
        request_id = request_id_of(messages)
        designs = [p for p in returned if p.tool_name == "design_visualization"]
        if len(designs) < 2:
            return call("design_visualization", request_id=request_id, direction=f"attempt {len(designs) + 1}",
                        required_columns=["region", "amount"])
        if len(designs) == 2:
            return call("design_visualization", request_id=request_id, direction="try the alternate designer",
                        use_fallback=True)
        return finish("No chart.")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(drive)):
        lead.run_sync("Draw", deps=deps, conversation_id="chat-1")
    results = returns_of(messages, "design_visualization")
    assert len(results) == 3
    assert "could not finish" in results[0] and "could not finish" in results[1]
    assert "already used its two initial design attempts" in results[2]


def test_required_columns_are_not_carried_to_the_next_design_call(deps, dataset_id, agents, monkeypatch):
    """Trace 01a0b9b9b84ebc86668979b36cda2c51: the first call required rest_count; the fallback call omitted the
    argument and the alternate designer delivered a donut without it. Establishes: design_visualization passes only
    the current call's required_columns to the designer (lead.py:467-469); nothing retains the earlier list."""
    seen = []

    def recording_design(report, *args, **kwargs):
        seen.append(kwargs.get("required_columns"))
        return failed_design(report, *args, **kwargs)

    monkeypatch.setattr("vis_agent.lead.design_chart", recording_design)
    deps.designer_fallback = deps.designer  # the chat team configures an alternate designer; the fixture does not
    lead = agents[-1]

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id=dataset_id, question="Compare the supplied values")
        request_id = request_id_of(messages)
        designs = [p for p in returned if p.tool_name == "design_visualization"]
        if not designs:
            return call("design_visualization", request_id=request_id, direction="first", required_columns=["amount"])
        if len(designs) == 1:
            return call("design_visualization", request_id=request_id, direction="again", use_fallback=True)
        return finish("No chart.")

    with lead.override(model=FunctionModel(drive)):
        lead.run_sync("Draw", deps=deps, conversation_id="chat-1")
    assert seen == [["amount"], None]


# --- 2. A budget crash in the chat leaves the request running; a running request blocks the next draw ------------

def stuck_request(deps, dataset_id, lead):
    """A lead that keeps calling tools until the request budget ends the run with an exception."""
    def drive(messages, info):
        if not tool_returns(messages):
            return call("draw", dataset_id=dataset_id, question="Compare the supplied values")
        return call("find_dataset", query="")

    with lead.override(model=FunctionModel(drive)), pytest.raises(UsageLimitExceeded):
        lead.run_sync("Draw", deps=deps, conversation_id="chat-1", usage_limits=UsageLimits(request_limit=3))
    return requests_of(deps).list_requests(conversation_id="chat-1", unfinished_only=True, limit=5)


def test_budget_crash_in_chat_leaves_the_request_running(deps, dataset_id, agents):
    """Traces 01a0b9b9b84ebc86668979b36cda2c51, 01a0b0a3c6bfd4b541a5cb9455459eb2, 01a0af8e46b241962d4e037b3d606163
    (request_limit of 18). Establishes: when UsageLimitExceeded ends a chat run, nothing changes the request's
    status; it stays 'running'. The API path marks it failed (requests/service.py:255-267); the chat path has no
    equivalent."""
    unfinished = stuck_request(deps, dataset_id, agents[-1])
    assert [r.status for r in unfinished] == ["running"]


@pytest.mark.parametrize("same_dataset", [False, True], ids=["other dataset", "same dataset, new question"])
def test_running_request_left_by_a_crashed_run_blocks_the_next_draw(deps, dataset_id, agents, store, same_dataset):
    """Trace 01a0b9c3d7532f637f8715e0f219e954: the rephrased question was refused because the previous turn's
    exhausted request (01a0b9c1c45d8af82156c4c80b54ec00, no crash, ended in text) was still running; the turn
    could only publish that request as a table. Establishes: draw refuses any new request while a request of the
    conversation is 'running', whatever left it so (lead.py:165-173). A refusal is correct when the other run is
    still working (trace 01a0af919c8e1cef6e3a92203856f88c was reviewing when 01a0af8e46b241962d4e037b3d606163
    drew); it is a dead end when the owner run is gone."""
    lead = agents[-1]
    stuck_request(deps, dataset_id, lead)
    other = dataset_id if same_dataset else store.save_upload("other.csv", SALES).dataset_id

    def drive(messages, info):
        if not tool_returns(messages):
            return call("draw", dataset_id=other, question="A different question")
        return finish("Blocked.")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(drive)):
        lead.run_sync("Draw again", deps=deps, conversation_id="chat-1")
    assert "already active in this conversation" in returns_of(messages, "draw")[0]


def test_same_run_cannot_redraw_to_bypass_a_diagnostic(deps, dataset_id, agents, store):
    """Guard for any recovery change: one run may not open a second request while its first is running
    (the guard's stated purpose)."""
    lead = agents[-1]
    other = store.save_upload("other.csv", SALES).dataset_id

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id=dataset_id, question="First")
        if len(returned) == 1:
            return call("draw", dataset_id=other, question="Second")
        return finish("Blocked.")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(drive)):
        lead.run_sync("Draw", deps=deps, conversation_id="chat-1")
    assert "already active in this conversation" in returns_of(messages, "draw")[1]


def test_resumed_request_is_not_superseded_by_a_draw_in_the_same_run(deps, dataset_id, agents):
    """Guard (from the independent review): resuming an earlier request and then drawing another question in the
    same run must still be refused, so a recovery change cannot use 'a different run opened it' as its signal."""
    request = create_request(deps, type="new", dataset_id=dataset_id, question="original", caller=CHAT)
    lead = agents[-1]

    def drive(messages, info):
        n = len(tool_returns(messages))
        if n == 0:
            return call("resume", request_id=request.request_id)
        if n == 1:
            return call("draw", dataset_id=dataset_id, question="different")
        return finish("Done")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(drive)):
        lead.run_sync("Continue", deps=deps, conversation_id="chat-1")
    assert "already active in this conversation" in returns_of(messages, "draw")[0]
    # Not superseded: no second request exists, and the resumed one is still unfinished (running, or stopped
    # once a run-end cleanup patch closes a turn that ended without publishing; resume reopens it either way).
    assert [r.request_id for r in requests_of(deps).list_requests(conversation_id="chat-1")] == [request.request_id]
    assert requests_of(deps).get_request(request.request_id).status in ("running", "stopped")


def test_a_live_concurrent_run_keeps_its_request(deps, dataset_id, agents):
    """Guard (from the independent review): a second run in the same conversation must not change the status of a
    request another run is still working on; today it is refused and the request stays running."""
    async def scenario():
        opened, release, first_id = asyncio.Event(), asyncio.Event(), []

        async def first(messages, info):
            if not tool_returns(messages):
                return call("draw", dataset_id=dataset_id, question="First active request")
            first_id.append(tool_returns(messages)[0].model_response_object()["request_id"])
            opened.set()
            await release.wait()
            return finish("Done")

        async def second(messages, info):
            if not tool_returns(messages):
                return call("draw", dataset_id=dataset_id, question="Second question")
            return finish("Done")

        lead = agents[-1]
        with lead.override(model=FunctionModel(first)):
            running = asyncio.create_task(lead.run("First", deps=deps, conversation_id="chat-1"))
            await opened.wait()
            with lead.override(model=FunctionModel(second)), capture_run_messages() as messages:
                await lead.run("Second", deps=deps, conversation_id="chat-1")
            status = requests_of(deps).get_request(first_id[0]).status
            release.set()
            await running
        assert "already active in this conversation" in returns_of(messages, "draw")[0]
        assert status == "running"

    asyncio.run(scenario())


# --- 3. ask_user only pauses a request that is not finished or waiting -------------------------------------------

@pytest.mark.parametrize("status,outcome", [("done", "refused"), ("waiting", "refused"), ("failed", "pauses")])
def test_ask_user_by_request_status(deps, dataset_id, agents, status, outcome):
    """Trace 01a0af8e46b241962d4e037b3d606163: 'which chart do you mean?' about finished artifacts failed with
    'finished or waiting'. Establishes: ask_user goes through active_request (lead.py:312-328), which refuses done
    and waiting requests and reactivates failed or stopped ones; a question that belongs to no request cannot be
    asked through the tool (the lead can still ask in its text)."""
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Show the table", caller=CHAT)
    request.status = status
    requests_of(deps).save_request(request)
    lead = agents[-1]

    def drive(messages, info):
        if not tool_returns(messages):
            return call("ask_user", request_id=request.request_id, question="Which chart do you mean?",
                        reason="Several charts exist.")
        return finish("Asked.")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(drive)):
        lead.run_sync("Show me the table of that chart", deps=deps, conversation_id="chat-1")
    result = returns_of(messages, "ask_user")[0]
    if outcome == "refused":
        assert "finished or waiting" in result
    else:
        assert "clarification" in result and requests_of(deps).get_request(request.request_id).status == "waiting"


# --- 4. One analyst call per request, while answer_question stays on offer ---------------------------------------

def test_analyst_disappears_after_one_consultation_while_answer_question_stays_offered(deps, dataset_id, agents):
    """Trace 01a0b9b9b84ebc86668979b36cda2c51: the lead asked the analyst for a wide table (gender, wealthy_count,
    rest_count), which a single donut cannot show; the analyst was then no longer offered, and the lead spent two
    answer_question calls (4 model requests) whose results cannot enter the request. Establishes: offer_analyst
    hides consult_analyst after one attempt (lead.py:247-253) while answer_question has no such guard."""
    _, analyst, _, lead = agents
    offered = []

    def drive(messages, info):
        returned = tool_returns(messages)
        offered.append(sorted(t.name for t in info.function_tools))
        if not returned:
            return call("draw", dataset_id=dataset_id, question="Compare the supplied values")
        request_id = request_id_of(messages)
        if not any(p.tool_name == "consult_analyst" for p in returned):
            return call("consult_analyst", request_id=request_id, task="add rest_count = total - wealthy")
        return finish("Stuck: the table has the wrong shape for the chart and the analyst is gone.")

    with capture_run_messages() as messages, analyst.override(model=FunctionModel(analyst_drive)), \
            lead.override(model=FunctionModel(drive)):
        lead.run_sync("Draw", deps=deps, conversation_id="chat-1")
    assert len(returns_of(messages, "consult_analyst")) == 1
    assert "consult_analyst" in offered[1]
    assert "consult_analyst" not in offered[-1]
    assert "answer_question" in offered[-1]


# --- 5. check_spec approves what deliver_design then rejects ------------------------------------------------------

def test_check_spec_passes_a_spec_that_deliver_design_rejects_for_required_columns(store):
    """Trace 01a0b9b9b84ebc86668979b36cda2c51: check_spec said ok, deliver_design then said 'omits required result
    columns rest_count'. Establishes: only deliver_design applies the required-column rule, so one of the
    designer's two deliveries is spent on a defect the check could have reported."""
    ds = store.save_upload("wealth.csv", b"gender,wealthy_count,rest_count\nF,37438,150334\nM,37439,149573\n").dataset_id
    report = load_csv_report(store, ds, "Donut per gender")
    spec = "vis donut\ntitle Wealthy by gender\ndescription Two slices\nbind\n  category gender\n  value wealthy_count\n"
    seen = {}

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("check_spec", spec=spec)
        retried = any(isinstance(p, RetryPromptPart) for m in messages for p in m.parts)
        if not retried:
            seen["check"] = returned[-1].model_response_object()
            return call("deliver_design", spec=spec, explanation="Two slices, one per gender.")
        return call("deliver_design", spec="vis table\ntitle Wealth\ndescription All columns\n", explanation="table")

    designer = create_designer("test")
    with capture_run_messages() as messages, designer.override(model=FunctionModel(drive)):
        designed = asyncio.run(design_chart(report, designer, None,
                                            required_columns=["gender", "wealthy_count", "rest_count"]))
    assert seen["check"]["ok"] is True
    retries = [str(p.content) for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]
    assert any("required_columns" in r for r in retries)
    assert designed.design is not None and designed.design.chart == "table"


# --- 6. The grammar's limit key passes the delivery check but never renders on a direct CSV ------------------------

def test_limit_passes_the_check_and_fails_at_render_on_a_direct_csv(store):
    """Trace 01a0b9b484d6422efc70172ee97f3392: the analyst had already selected the top three rows by SQL; the
    designer then added `limit 3` (fold the remainder into Other) and the render failed with 'A limit needs a
    category and additive values for Other'. Establishes: the direct reader marks every column aggregate 'none'
    (analyst/source.py), the resolver refuses limit on such columns (designer/resolve.py:335-338), and the
    delivery check does not. Top-N selection itself is not affected; it is done by the analyst."""
    ds = store.save_upload("wages.csv", b"employer,avg_wage\nA,24305\nB,24261\nC,24260\nD,24225\n").dataset_id
    report = load_csv_report(store, ds, "Top three employers")
    spec = ("vis donut\ntitle Top three\ndescription Averages\nbind\n  category employer\n  value avg_wage\n"
            "sort value desc\nlimit 3\n")
    check = check_render_spec(spec, report.analysis.columns, report.result, "gptvis")
    assert check.ok, [v.message for v in check.violations]
    with pytest.raises(ResolveError, match="additive values"):
        resolve(parse(spec), report.analysis.columns, report.result)


# --- 7. A numeric year column is a measure, so a time axis defaults to value order ---------------------------------

def test_numeric_year_is_a_measure_and_the_line_chart_orders_years_by_value(store):
    """Corpus: all 39 columns whose name is a year word and whose values are four-digit years are typed measure.
    Establishes: the direct reader types integer years numeric (analyst/source.py:88) and the resolver defaults a
    time-role axis of a non-time kind to 'value desc' (designer/resolve.py:326-331); the delivery check accepts
    the spec. No trace this week drew a year axis; this is a code-level defect with a corpus-wide exposure."""
    ds = store.save_upload("years.csv", b"year,amount\n2021,5\n2022,9\n2023,7\n2024,8\n").dataset_id
    report = load_csv_report(store, ds, "Amount over the years")
    kinds = {c.name: c.kind for c in report.analysis.columns}
    assert kinds["year"] == "measure"
    spec = "vis line\ntitle Trend\ndescription Yearly amounts\nbind\n  time year\n  value amount\n"
    assert check_render_spec(spec, report.analysis.columns, report.result, "gptvis").ok
    resolved = resolve(parse(spec), report.analysis.columns, report.result)
    years = [row["time"] for row in resolved.config["data"]]
    assert years == [2022, 2024, 2023, 2021]  # sorted by amount desc, not chronologically


def test_explicit_sort_none_keeps_the_source_order_of_numeric_years(store):
    """Guard for any ordering change: an explicit `sort none` keeps the source order of years it cannot interpret
    (designer/rulebook.md:57 asks for exactly this for Hijri labels)."""
    ds = store.save_upload("hijri.csv", b"year,amount\n1447,5\n1445,9\n1446,7\n").dataset_id
    report = load_csv_report(store, ds, "Amount by Hijri year")
    spec = "vis line\ntitle Trend\ndescription Yearly amounts\nbind\n  time year\n  value amount\nsort none\n"
    resolved = resolve(parse(spec), report.analysis.columns, report.result)
    assert [row["time"] for row in resolved.config["data"]] == [1447, 1445, 1446]


# --- 8. A column with one long cell is removed from the chart table; the lead is told, the designer is not ----------

def test_long_text_column_is_dropped_the_lead_is_told_and_the_designer_is_not(deps, store):
    """Corpus: 31 files are tagged long_text_cells; all 29 columns the direct reader kept local in the corpus pass
    were geometry (wkt). Establishes: any cell over 256 bytes removes the whole column (analyst/source.py:82-84);
    the warning reaches the lead in the draw result (requests/service.py:128) but not the designer prompt
    (designer/agent.py:109-149)."""
    long_label = "x" * 300
    ds = store.save_upload("long.csv", f"label,amount\n{long_label},5\nshort,7\n".encode()).dataset_id
    report = load_csv_report(store, ds, "Compare the labels")
    assert [c.name for c in report.analysis.columns] == ["amount"]
    assert report.warnings and "kept local" in report.warnings[0]
    request = create_request(deps, type="new", dataset_id=ds, question="Compare the labels", caller=CHAT)
    opened = asyncio.run(prepare_request(deps, request))
    assert any("kept local" in w for w in opened["warnings"])
    prompt = build_prompt(report, None)
    assert "kept local" not in prompt.model_dump_json() and "label" not in [c.name for c in prompt.columns]


# --- 9. Any error finding forces revise, even one whose own text says the chart is right -----------------------------

def test_reviewer_error_owned_by_none_yields_revise_even_when_the_summary_retracts_it(store, tmp_path):
    """Trace 01a0b9b80adec66a05a2684f39fbb99b: the finding's observation ends 'This is correct' and the summary says
    'my initial check ... was mistaken', yet level=error gives verdict revise. Establishes: the verdict is derived
    from the level alone (reviewer/agent.py:88), which the rulebook chooses deliberately (rulebook.md:29); an
    owner of none leaves no repair path (lead.material_design_review); an 'image' reference needs no evidence
    check (reviewer/agent.py:62-71). The defect shown is contradictory model evidence reaching the lead as a
    revise verdict, not the owner field."""
    ds = store.save_upload("sales.csv", SALES).dataset_id
    report = load_csv_report(store, ds, "Compare regions")
    design = Design(spec=CHART_SPEC, chart="bar", intent=None, explanation="Bars", considered=["bar"], compromises=[])
    png = tmp_path / "chart.png"
    png.write_bytes(b"png")

    def drive(messages, info):
        return call("deliver_review", summary="The chart is correct; my initial check of the legend was mistaken.",
                    findings=[{"rule": "R-1", "level": "error", "owner": "none", "location": "Legend",
                               "observed": "The legend shows a pink square for males. This is consistent.",
                               "expected": "The legend should map pink to males.",
                               "reference": {"kind": "image"}}])

    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(drive)):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert reviewed.review is not None
    assert reviewed.review.verdict == "revise"
    assert reviewed.review.findings[0].owner == "none"
