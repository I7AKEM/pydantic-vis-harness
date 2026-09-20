"""Real lead/tool conversations with fake models and a filesystem renderer."""

import json
import re

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.analyst.agent import create_analyst
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import create_designer
from vis_agent.lead import create_lead
from vis_agent.profiler.agent import create_profiler
from vis_agent.render.base import Rendered
from vis_agent.requests.store import RequestStore
from vis_agent.reviewer.agent import create_reviewer

# This is the upstream data agent's finished answer, not raw events to aggregate again.
SALES = b"region,amount\nEast,10\nWest,20\n"
CHART_SPEC = (
    "vis bar\ntitle Sales by region\ndescription Supplied regional sales\n"
    "bind\n  category region\n  value amount\nsort value desc\n"
)


def tool_returns(messages):
    return [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]


def prompt_of(messages) -> dict:
    return json.loads(messages[0].parts[-1].content)


def call(name, **args):
    return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])


def finish(text="Done."):
    return ModelResponse(parts=[TextPart(content=text)])


def request_id_of(messages):
    for part in reversed(tool_returns(messages)):
        value = part.model_response_object()
        if isinstance(value, dict) and value.get("request_id"):
            return value["request_id"]
    for message in messages:
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                found = re.search(r"rq_[0-9a-f]{32}", str(part.content))
                if found:
                    return found.group()
    raise AssertionError("The lead was not given the saved request ID")


def analyst_drive(messages, info):
    """Legacy analysis fake kept for focused optional-analyst tests."""
    if not tool_returns(messages):
        prompt = prompt_of(messages)
        return call("run_query", sql=f'SELECT region, amount FROM {prompt["table"]}', columns=[
            {"name": "region", "meaning": "Region", "kind": "category", "source": "region"},
            {"name": "amount", "meaning": "Sales", "kind": "measure", "source": "amount"},
        ])
    return call("deliver_analysis", summary="Supplied sales by region.")


def designer_drive(messages, info):
    prompt = prompt_of(messages)
    spec = CHART_SPEC
    if (prompt.get("previous") or {}).get("spec"):
        spec += "palette\n  - #0F6CBD\n"
    return call("deliver_design", spec=spec, explanation="Bars compare the supplied regional sales.")


def reviewer_pass(messages, info):
    return call("deliver_review", summary="The chart represents the supplied table.", findings=[])


def reviewer_finding(rule="R-5", level="error", owner="designer", message="The title is hard to read."):
    def drive(messages, info):
        return call("deliver_review", summary="Improve the title.", findings=[
            {"rule": rule, "level": level, "owner": owner, "location": "Title or label region",
             "observed": message, "expected": "Meaning-bearing text is legible and correctly paired.",
             "reference": {"kind": "image"}},
        ])
    return drive


class Counting:
    def __init__(self, drive):
        self.drive, self.runs, self.calls = drive, 0, 0

    def __call__(self, messages, info):
        self.calls += 1
        if not tool_returns(messages):
            self.runs += 1
        return self.drive(messages, info)


def lead_drive(deps):
    """A lead choosing the short path; the service itself makes no specialist choice."""
    def drive(messages, info):
        returned = tool_returns(messages)
        request_id = request_id_of(messages)
        if not returned:
            return call("resume", request_id=request_id)
        context = returned[-1].model_response_object()
        if context.get("artifact_id") or returned[-1].tool_name == "publish_visualization":
            return finish()
        if (context.get("render") or {}).get("png_url"):
            if not context.get("review"):
                return call("review_visualization", request_id=request_id)
            return call("publish_visualization", request_id=request_id)
        if returned[-1].tool_name == "review_visualization":
            return call("publish_visualization", request_id=request_id)
        if (context.get("design") or {}).get("design"):
            return call("render_visualization", request_id=request_id)
        return call("design_visualization", request_id=request_id, direction=context.get("question", "Compare supplied values."))
    return drive


@pytest.fixture
def agents():
    return create_profiler("test"), create_analyst("test"), create_designer("test"), create_lead("test")


@pytest.fixture
def reviewer():
    return create_reviewer("test")


@pytest.fixture
def deps(store, agents, reviewer):
    profiler, analyst, designer, lead = agents
    return AppDeps(store=store, profiler=profiler, analyst=analyst, designer=designer, requests=RequestStore(store),
                   reviewer=reviewer, lead=lead)


@pytest.fixture
def dataset_id(store):
    return store.save_upload("sales.csv", SALES).dataset_id


@pytest.fixture
def fake_models(agents, reviewer, deps):
    profiler, analyst, designer, lead = agents
    counts = {"profiler": 0, "analyst": 0}

    def forbidden(name):
        def drive(messages, info):
            counts[name] += 1
            raise AssertionError(f"The prepared CSV must not require the {name}")
        return drive

    counted_designer, counted_reviewer = Counting(designer_drive), Counting(reviewer_pass)
    with profiler.override(model=FunctionModel(forbidden("profiler"))), \
            analyst.override(model=FunctionModel(forbidden("analyst"))), \
            designer.override(model=FunctionModel(counted_designer)), \
            reviewer.override(model=FunctionModel(counted_reviewer)), \
            lead.override(model=FunctionModel(lead_drive(deps))):
        yield counts, counted_designer, counted_reviewer


@pytest.fixture
def fake_render(monkeypatch, store):
    calls = []

    def render(report, design, out_dir, renderer="gptvis"):
        calls.append((report, design, out_dir))
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "chart.png").write_bytes(b"png")
        (out_dir / "chart.html").write_text("<html>chart</html>")
        return Rendered(png=out_dir / "chart.png", html=out_dir / "chart.html", config=out_dir / "config.json",
                        width=2400, height=1350, seconds=0.1, non_background_share=0.2, compromises=[],
                        drawn_rows=report.result.row_count, folded_rows=0, dropped_rows=0)

    monkeypatch.setattr("vis_agent.lead.render_design", render)
    return calls
