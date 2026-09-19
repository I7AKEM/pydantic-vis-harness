"""Reproductions of the flow gaps seen in the Logfire traces of 2026-09-16..19 (analysis branch).

Each test names the trace it reproduces. The assertions describe what the code does today; they are evidence,
not the desired behaviour.
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
from vis_agent.requests.service import create_request, requests_of
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


# --- 1. The instructions offer use_fallback after a failure; the code refuses it after two failures ---------------

def test_two_failed_initial_designs_also_refuse_the_fallback_designer(deps, dataset_id, agents, monkeypatch):
    """Trace 01a0b9c1c45d8af82156c4c80b54ec00: two DeepSeek failures, then use_fallback=true refused four times."""
    monkeypatch.setattr("vis_agent.lead.design_chart", failed_design)
    lead = agents[-1]
    assert "use_fallback=true" in LEAD_INSTRUCTIONS  # the lead is told this is the recovery after a failed design

    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id=dataset_id, question="Compare the supplied values")
        request_id = request_id_of(messages)
        designs = [p for p in returned if p.tool_name == "design_visualization"]
        if len(designs) < 2:
            return call("design_visualization", request_id=request_id, direction=f"attempt {len(designs) + 1}")
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


# --- 2. A budget crash in the chat leaves the request running, and that blocks every later draw ----------------

def stuck_request(deps, dataset_id, lead):
    def drive(messages, info):
        if not tool_returns(messages):
            return call("draw", dataset_id=dataset_id, question="Compare the supplied values")
        return call("find_dataset", query="")

    with lead.override(model=FunctionModel(drive)), pytest.raises(UsageLimitExceeded):
        lead.run_sync("Draw", deps=deps, conversation_id="chat-1", usage_limits=UsageLimits(request_limit=3))
    unfinished = requests_of(deps).list_requests(conversation_id="chat-1", unfinished_only=True, limit=5)
    return unfinished


def test_budget_crash_in_chat_leaves_the_request_running(deps, dataset_id, agents):
    """Traces 01a0b9b9b84ebc86668979b36cda2c51 and 01a0af8e46b241962d4e037b3d606163 (request_limit of 18)."""
    unfinished = stuck_request(deps, dataset_id, agents[-1])
    assert [r.status for r in unfinished] == ["running"]


@pytest.mark.parametrize("same_dataset", [False, True], ids=["other dataset", "same dataset, new question"])
def test_stale_running_request_blocks_the_next_draw_in_the_conversation(deps, dataset_id, agents, store, same_dataset):
    """Trace 01a0af8e46b241962d4e037b3d606163 (other dataset) and 01a0b9c3d7532f637f8715e0f219e954 (same dataset,
    the user rephrased after the two design attempts were spent)."""
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


# --- 3. ask_user only works on a running request -----------------------------------------------------------------

def test_ask_user_cannot_ask_about_a_finished_request(deps, dataset_id, agents):
    """Trace 01a0af8e46b241962d4e037b3d606163: 'which chart do you mean?' failed, then 280 s of answer_question."""
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Show the table", caller=CHAT)
    request.status = "done"
    requests_of(deps).save_request(request)
    lead = agents[-1]

    def drive(messages, info):
        if not tool_returns(messages):
            return call("ask_user", request_id=request.request_id, question="Which chart do you mean?",
                        reason="Several charts exist.")
        return finish("Could not ask.")

    with capture_run_messages() as messages, lead.override(model=FunctionModel(drive)):
        lead.run_sync("Show me the table of that chart", deps=deps, conversation_id="chat-1")
    assert "finished or waiting" in returns_of(messages, "ask_user")[0]


# --- 4. One analyst call per request, while answer_question stays on offer ---------------------------------------

def test_analyst_disappears_after_one_consultation_while_answer_question_stays_offered(deps, dataset_id, agents):
    """Trace 01a0b9b9b84ebc86668979b36cda2c51: the first reshape was the wrong shape for the chart; the lead then
    leaked into answer_question twice, which cannot feed the request."""
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
    assert "consult_analyst" in offered[1]  # offered before the first consultation
    assert "consult_analyst" not in offered[-1]  # hidden after it (offer_analyst), so no reshape can follow
    assert "answer_question" in offered[-1]  # while the request-less numbers path stays on offer


# --- 5. check_spec approves what deliver_design then rejects ------------------------------------------------------

def test_check_spec_passes_a_spec_that_deliver_design_rejects_for_required_columns(store):
    """Trace 01a0b9b9b84ebc86668979b36cda2c51: check_spec ok, deliver_design 'omits required result columns'."""
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


# --- 6. limit (top-N with Other) passes the delivery check but can never render on a direct CSV --------------------

def test_limit_passes_the_check_and_fails_at_render_on_a_direct_csv(store):
    """Trace 01a0b9b484d6422efc70172ee97f3392: 'Rendering failed: A limit needs a category and additive values'."""
    ds = store.save_upload("wages.csv", b"employer,avg_wage\nA,24305\nB,24261\nC,24260\nD,24225\n").dataset_id
    report = load_csv_report(store, ds, "Top three employers")
    spec = ("vis donut\ntitle Top three\ndescription Averages\nbind\n  category employer\n  value avg_wage\n"
            "sort value desc\nlimit 3\n")
    check = check_render_spec(spec, report.analysis.columns, report.result, "gptvis")
    assert check.ok, [v.message for v in check.violations]
    with pytest.raises(ResolveError, match="additive values"):
        resolve(parse(spec), report.analysis.columns, report.result)


# --- 7. A numeric year column is a measure, so a time axis is sorted by value ------------------------------------

def test_numeric_year_is_a_measure_and_the_line_chart_orders_years_by_value(store):
    """Corpus: 73 files carry a temporal column; integer years are typed numeric by the direct reader."""
    ds = store.save_upload("years.csv", b"year,amount\n2021,5\n2022,9\n2023,7\n2024,8\n").dataset_id
    report = load_csv_report(store, ds, "Amount over the years")
    kinds = {c.name: c.kind for c in report.analysis.columns}
    assert kinds["year"] == "measure"
    spec = "vis line\ntitle Trend\ndescription Yearly amounts\nbind\n  time year\n  value amount\n"
    resolved = resolve(parse(spec), report.analysis.columns, report.result)
    years = [row["time"] for row in resolved.config["data"]]
    assert years == [2022, 2024, 2023, 2021]  # sorted by amount desc, not chronologically


# --- 8. A column with one long cell disappears before the designer sees the table --------------------------------

def test_long_text_column_is_dropped_and_the_designer_is_not_told(store):
    """Corpus: 31 files are tagged long_text_cells; any cell over 256 bytes removes the whole column."""
    long_label = "x" * 300
    ds = store.save_upload("long.csv", f"label,amount\n{long_label},5\nshort,7\n".encode()).dataset_id
    report = load_csv_report(store, ds, "Compare the labels")
    assert [c.name for c in report.analysis.columns] == ["amount"]
    assert report.warnings and "kept local" in report.warnings[0]
    prompt = build_prompt(report, None)
    assert "kept local" not in prompt.model_dump_json() and "label" not in [c.name for c in prompt.columns]


# --- 9. A reviewer error owned by nobody still forces a revise verdict --------------------------------------------

def test_reviewer_error_owned_by_none_yields_revise_even_when_the_summary_retracts_it(store, tmp_path):
    """Trace 01a0b9b80adec66a05a2684f39fbb99b: 'The chart is correct; my initial check ... was mistaken' -> revise."""
    ds = store.save_upload("sales.csv", SALES).dataset_id
    report = load_csv_report(store, ds, "Compare regions")
    design = Design(spec=CHART_SPEC, chart="bar", intent=None, explanation="Bars", considered=["bar"], compromises=[])
    png = tmp_path / "chart.png"
    png.write_bytes(b"png")

    def drive(messages, info):
        return call("deliver_review", summary="The chart is correct; my initial check of the legend was mistaken.",
                    findings=[{"rule": "R-1", "level": "error", "owner": "none", "location": "Legend",
                               "observed": "The legend shows a pink square for males.",
                               "expected": "The legend should map pink to males.",
                               "reference": {"kind": "image"}}])

    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(drive)):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert reviewed.review is not None
    assert reviewed.review.verdict == "revise"
    assert reviewed.review.findings[0].owner == "none"  # no repair path exists for this owner (lead.material_design_review)
