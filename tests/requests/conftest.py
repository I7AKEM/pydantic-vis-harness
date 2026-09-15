import json

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from vis_agent.analyst.agent import create_analyst
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import create_designer
from vis_agent.lead import create_lead
from vis_agent.profiler.agent import create_profiler
from vis_agent.render.base import Rendered
from vis_agent.requests.store import RequestStore
from vis_agent.reviewer.agent import create_reviewer

SALES = b"id,region,date,amount\n001,East,2026-01-01,10\n002,West,2026-01-02,20\n"
CHART_SPEC = (
    "vis bar\ntitle Total by region\ndescription Total sales by region\n"
    "bind\n  category region\n  value total\nsort value desc\n"
)


def semantic_output(names):
    return {"description": "Sales.", "row_meaning": None, "questions": [], "columns": [
        {"name": n, "meaning": None, "role": "unknown", "unit": None, "confidence": "low", "evidence": "e"}
        for n in names
    ]}


def tool_returns(messages):
    return [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]


def prompt_of(messages) -> dict:
    return json.loads(messages[0].parts[-1].content)


def analyst_drive(messages, info):
    """Two calls: the query, then the delivery. Reads the table name from the prompt."""
    if not tool_returns(messages):
        prompt = prompt_of(messages)
        return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={
            "sql": f'SELECT region, sum(amount) AS total FROM {prompt["table"]} GROUP BY 1 ORDER BY 2 DESC',
            "columns": [{"name": "region", "meaning": "Region", "kind": "category", "source": "region"},
                        {"name": "total", "meaning": "Total sales", "kind": "measure", "source": "amount",
                         "aggregate": "sum"}],
        })])
    return ModelResponse(parts=[ToolCallPart(tool_name="deliver_analysis", args={"summary": "West leads with 20."})])


def designer_drive(messages, info):
    returns = tool_returns(messages)
    if not returns:
        return ModelResponse(parts=[ToolCallPart(tool_name="recommend_charts", args={"intent": "compare"})])
    if len(returns) == 1:
        return ModelResponse(parts=[ToolCallPart(tool_name="check_spec", args={"spec": CHART_SPEC})])
    checked = returns[-1].model_response_object()
    assert checked["ok"], checked
    return ModelResponse(parts=[ToolCallPart(tool_name="deliver_design", args={
        "spec": checked["canonical"], "explanation": "West leads with 20. A bar chart compares regional totals.",
    })])


def reviewer_pass(messages, info):
    return ModelResponse(parts=[ToolCallPart(tool_name="deliver_review", args={"summary": "Fine.", "findings": []})])


def reviewer_finding(rule="R-5", level="error", owner="designer", message="The bars are sorted ascending."):
    def drive(messages, info):
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_review", args={
            "summary": "Something is off.", "findings": [{"rule": rule, "level": level, "owner": owner, "message": message}]})])
    return drive


class Counting:
    """Wraps a drive function and counts the runs it starts (first model call of each run)."""

    def __init__(self, drive):
        self.drive, self.runs = drive, 0

    def __call__(self, messages, info):
        if not tool_returns(messages):
            self.runs += 1
        return self.drive(messages, info)


@pytest.fixture
def agents():
    return create_profiler("test"), create_analyst("test"), create_designer("test"), create_lead("test")


@pytest.fixture
def reviewer():
    return create_reviewer("test")


@pytest.fixture
def deps(store, agents, reviewer):
    profiler, analyst, designer, _lead = agents
    return AppDeps(store=store, profiler=profiler, analyst=analyst, designer=designer, requests=RequestStore(store),
                   reviewer=reviewer)



@pytest.fixture
def dataset_id(store):
    return store.save_upload("sales.csv", SALES).dataset_id


@pytest.fixture
def fake_models(agents, reviewer):
    """Override every agent with fakes; yields the counting analyst and designer drives. The reviewer passes."""
    profiler, analyst, designer, _lead = agents
    counted_analyst, counted_designer = Counting(analyst_drive), Counting(designer_drive)
    with profiler.override(model=TestModel(call_tools=[], custom_output_args=semantic_output(["id", "region", "date", "amount"]))), \
            analyst.override(model=FunctionModel(counted_analyst)), \
            designer.override(model=FunctionModel(counted_designer)), \
            reviewer.override(model=FunctionModel(reviewer_pass)):
        yield counted_analyst, counted_designer


@pytest.fixture
def fake_render(monkeypatch, store):
    """The renderer writes a fake picture instead of calling Node."""
    calls = []

    def render(report, design, out_dir, renderer="gptvis"):
        calls.append(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "chart.png").write_bytes(b"png")
        return Rendered(png=out_dir / "chart.png", html=out_dir / "chart.html", config=out_dir / "config.json",
                        width=2400, height=1350, seconds=0.1, non_background_share=0.2, compromises=[],
                        drawn_rows=2, folded_rows=0, dropped_rows=0)

    monkeypatch.setattr("vis_agent.requests.runner.render_design", render)
    return calls
