"""Indicator requests use the ordinary saved pipeline, including reuse and recovery."""

import asyncio

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from tests.requests.conftest import Counting, prompt_of, tool_returns
from vis_agent.render.base import RenderFailed
from vis_agent.requests import runner
from vis_agent.requests.models import Caller
from vis_agent.requests.runner import create_request, run_request

CALLER = Caller(kind="chat", conversation_id="indicator-tests")
SPEC = "vis indicator\ntitle Total sales\ndescription Sales for the requested scope\ncards\n  - value total\n"


def scalar_analysis(messages, info):
    prompt = prompt_of(messages)
    if not tool_returns(messages):
        change = prompt.get("previous", {}).get("change", "")
        filtered = " WHERE region = 'East'" if "East" in change else ""
        return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={
            "sql": f'SELECT sum(amount) AS total FROM {prompt["table"]}{filtered}',
            "columns": [{"name": "total", "meaning": "Total sales", "kind": "measure",
                         "source": "amount", "aggregate": "sum"}],
        })])
    return ModelResponse(parts=[ToolCallPart(tool_name="deliver_analysis", args={
        "summary": "The result contains total sales for the requested scope."})])


def indicator_design(messages, info):
    returned = tool_returns(messages)
    if not returned:
        previous = prompt_of(messages).get("previous", {})
        spec = SPEC + ("palette\n  - #1e40af\n" if "blue" in previous.get("change", "") else "")
        return ModelResponse(parts=[ToolCallPart(tool_name="check_spec", args={"spec": spec})])
    checked = returned[-1].model_response_object()
    assert checked["ok"], checked
    return ModelResponse(parts=[ToolCallPart(tool_name="deliver_design", args={
        "spec": checked["canonical"], "explanation": "A card presents total sales with its scope."})])


@pytest.fixture
def indicator_models(agents, fake_models):
    _, analyst, designer, _ = agents
    counts = Counting(scalar_analysis), Counting(indicator_design)
    with analyst.override(model=FunctionModel(counts[0])), designer.override(model=FunctionModel(counts[1])):
        yield counts


def new_indicator(deps, dataset_id):
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Show total sales as a KPI", caller=CALLER)
    return request, asyncio.run(run_request(deps, request.request_id))


def test_indicator_style_revision_reuses_sql_and_versions(deps, dataset_id, indicator_models, fake_render):
    _, first = new_indicator(deps, dataset_id)
    assert first.artifact.chart == "indicator"
    revision = create_request(deps, type="revise", dataset_id=dataset_id, question="Make it blue", caller=CALLER,
                              parent_artifact_id=first.artifact.artifact_id)
    second = asyncio.run(run_request(deps, revision.request_id))
    assert second.status == "done" and second.artifact.chart == "indicator"
    assert "#1e40af" in second.artifact.spec
    assert second.artifact.sql == first.artifact.sql and second.artifact.rows == [[30]]
    assert second.artifact.version == 2 and second.artifact.parent_artifact_id == first.artifact.artifact_id
    assert [counter.runs for counter in indicator_models] == [1, 2]


def test_indicator_filter_revision_reanalyses_source(deps, dataset_id, indicator_models, fake_render):
    _, first = new_indicator(deps, dataset_id)
    revision = create_request(deps, type="revise", dataset_id=dataset_id, question="Only East", caller=CALLER,
                              parent_artifact_id=first.artifact.artifact_id, redo_analysis=True)
    second = asyncio.run(run_request(deps, revision.request_id))
    assert second.artifact.rows == [[10]] and "WHERE" in second.artifact.sql
    assert [counter.runs for counter in indicator_models] == [2, 2]


@pytest.mark.parametrize("change", ["اجعل البطاقة باللغة العربية", "Make this card Arabic"])
def test_indicator_language_revision_translates_labels_without_new_sql(deps, dataset_id, indicator_models, fake_render, agents, change):
    from vis_agent.designer.syntax import parse

    _, first = new_indicator(deps, dataset_id)
    _, _, designer, _ = agents
    translated = ('vis indicator\ntitle إجمالي المبيعات\ndescription إجمالي المبيعات للنطاق المطلوب\n'
                  'language ar\ncards\n  - value total\ncolumnLabels\n  - ["total", "إجمالي المبيعات"]\n')

    def arabic_design(messages, info):
        prompt = prompt_of(messages)
        assert prompt["previous"]["change"] == change
        assert prompt["columns"][0]["meaning"] == "Total sales"
        if not tool_returns(messages):
            return ModelResponse(parts=[ToolCallPart(tool_name="check_spec", args={"spec": translated})])
        checked = tool_returns(messages)[-1].model_response_object()
        assert checked["ok"], checked
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_design", args={
            "spec": checked["canonical"], "explanation": "تمت ترجمة تسميات البطاقة."})])

    revision = create_request(deps, type="revise", dataset_id=dataset_id, question=change,
                              caller=CALLER, parent_artifact_id=first.artifact.artifact_id)
    with designer.override(model=FunctionModel(arabic_design)):
        second = asyncio.run(run_request(deps, revision.request_id))
    assert second.artifact.sql == first.artifact.sql and second.artifact.rows == [[30]]
    assert parse(second.artifact.spec).column_labels == {"total": "إجمالي المبيعات"}
    assert indicator_models[0].runs == 1


def test_grouped_to_total_card_reanalyses_instead_of_picking_a_row(deps, dataset_id, fake_models, fake_render, agents):
    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total by region", caller=CALLER)
    first = asyncio.run(run_request(deps, request.request_id)).artifact
    _, analyst, designer, _ = agents
    with analyst.override(model=FunctionModel(scalar_analysis)), designer.override(model=FunctionModel(indicator_design)):
        revision = create_request(deps, type="revise", dataset_id=dataset_id, question="Show the overall total as a KPI",
                                  caller=CALLER, parent_artifact_id=first.artifact_id, redo_analysis=True)
        second = asyncio.run(run_request(deps, revision.request_id)).artifact
    assert first.rows == [["West", 20], ["East", 10]]
    assert second.chart == "indicator" and second.rows == [[30]] and "GROUP BY" not in second.sql


def test_resume_after_render_interruption_reuses_indicator_design(deps, dataset_id, indicator_models, fake_render, monkeypatch):
    render = runner.render_design

    def interrupted(*args, **kwargs):
        raise RuntimeError("interrupted before writing the PNG")

    request = create_request(deps, type="new", dataset_id=dataset_id, question="Total sales KPI", caller=CALLER)
    monkeypatch.setattr(runner, "render_design", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        asyncio.run(run_request(deps, request.request_id))
    saved = deps.requests.get_request(request.request_id)
    assert "design" in saved.steps and "render" not in saved.steps
    monkeypatch.setattr(runner, "render_design", render)
    resumed = asyncio.run(run_request(deps, request.request_id))
    assert resumed.artifact.chart == "indicator" and resumed.artifact.png_url
    assert [counter.runs for counter in indicator_models] == [1, 1]


def test_historical_scalar_skip_is_preserved_until_a_new_revision(deps, dataset_id, indicator_models, fake_render, monkeypatch):
    async def historical_skip(*args, **kwargs):
        return {"skipped": "The answer is a single number; it needs no chart."}

    with monkeypatch.context() as patch:
        patch.setitem(runner.STEP_FUNCTIONS, "design", historical_skip)
        request, first = new_indicator(deps, dataset_id)
    assert first.artifact.chart is None and not fake_render
    again = asyncio.run(run_request(deps, request.request_id))
    assert again.artifact.artifact_id == first.artifact.artifact_id
    assert indicator_models[1].runs == 0
    revision = create_request(deps, type="revise", dataset_id=dataset_id, question="Make this a blue KPI card", caller=CALLER,
                              parent_artifact_id=first.artifact.artifact_id)
    second = asyncio.run(run_request(deps, revision.request_id))
    assert second.artifact.chart == "indicator" and second.artifact.version == 2
    assert "#1e40af" in second.artifact.spec
    assert [counter.runs for counter in indicator_models] == [1, 1]


def test_indicator_render_failure_is_disclosed_with_table(deps, dataset_id, indicator_models, monkeypatch):
    def broken(*args, **kwargs):
        raise RenderFailed("The metric cannot fit in the requested dimensions.")

    monkeypatch.setattr(runner, "render_design", broken)
    _, outcome = new_indicator(deps, dataset_id)
    assert outcome.artifact.png_url is None and outcome.artifact.rows == [[30]]
    assert "cannot fit" in outcome.artifact.no_chart_reason


def test_numbers_only_tool_does_not_create_a_card_or_request(deps, dataset_id, indicator_models, agents):
    _, _, _, lead = agents

    def numbers_only(messages, info):
        if not tool_returns(messages):
            return ModelResponse(parts=[ToolCallPart(tool_name="answer_question", args={
                "dataset_id": dataset_id, "question": "Total sales, numbers only"})])
        answer = tool_returns(messages)[-1].model_response_object()
        return ModelResponse(parts=[TextPart(content=str(answer["rows"][0][0]))])

    with lead.override(model=FunctionModel(numbers_only)):
        result = lead.run_sync("Just the total, no chart", deps=deps)
    assert result.output == "30" and indicator_models[1].runs == 0
    assert deps.requests.list_requests(dataset_id=dataset_id) == []
