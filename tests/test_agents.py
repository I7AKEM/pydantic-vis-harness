import re

import pytest

from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from vis_agent.analyst.agent import create_analyst
from vis_agent.designer.agent import create_designer
from vis_agent.lead import create_lead
from vis_agent.profiler.models import DatasetProfile
from vis_agent.deps import AppDeps
from vis_agent.profiler.agent import create_profiler

SALES = b"id,region,date,amount\n001,East,2026-01-01,10\n002,West,2026-01-02,20\n"


def semantic_output(names):
    return {"description": "Sales.", "row_meaning": None, "questions": [], "columns": [
        {"name": n, "meaning": None, "role": "unknown", "unit": None, "confidence": "low", "evidence": "e"}
        for n in names
    ]}


def tool_returns(messages):
    return [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]


def call_then_summarize(tool_name, args, summarize):
    def drive(messages, info):
        returns = tool_returns(messages)
        if not returns:
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=args)])
        return ModelResponse(parts=[TextPart(content=summarize(returns[-1]))])
    return drive


def test_lead_exposes_its_tools_to_the_model(store):
    lead = create_lead("test")
    seen = {}

    def drive(messages, info):
        seen["tools"] = {tool.name for tool in info.function_tools}
        return ModelResponse(parts=[TextPart(content="ok")])

    with lead.override(model=FunctionModel(drive)):
        lead.run_sync("hello", deps=AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"), designer=create_designer("test")))
    assert lead.name == "vis-lead"
    assert {"profile_csv", "find_dataset"} <= seen["tools"]


def test_lead_profiles_a_csv_through_the_agent(store):
    source = store.save_upload("sales.csv", SALES)
    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"), designer=create_designer("test"))

    def summarize(part):
        content = part.content
        profile = content if isinstance(content, DatasetProfile) else DatasetProfile.model_validate(content)
        return f"Profiled {profile.deterministic.row_count} rows."

    drive = call_then_summarize("profile_csv", {"uploaded_file_id": source.dataset_id}, summarize)
    with profiler.override(model=TestModel(call_tools=[], custom_output_args=semantic_output(source.headers))):
        with lead.override(model=FunctionModel(drive)):
            result = lead.run_sync("Profile the attached CSV", deps=deps)
    assert result.output == "Profiled 2 rows."
    assert store.get_profile(source.dataset_id).status == "complete"


@pytest.mark.parametrize("tool_name", ["profile_csv", "make_chart"])
def test_unknown_id_is_a_failed_tool_result_not_a_retry(store, tool_name):
    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"), designer=create_designer("test"))
    args = ({"uploaded_file_id": "ds_" + "0" * 32} if tool_name == "profile_csv"
            else {"dataset_id": "ds_" + "0" * 32, "question": "Total by region"})
    drive = call_then_summarize(tool_name, args,
                                lambda part: f"outcome={part.outcome}: {part.content}")
    with lead.override(model=FunctionModel(drive)):
        with capture_run_messages() as messages:
            result = lead.run_sync("Profile ds_000", deps=deps)
    assert result.output.startswith("outcome=failed: File ID not found")
    assert not [p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]


@pytest.mark.parametrize("tool_name", ["profile_csv", "make_chart"])
def test_malformed_id_asks_the_model_to_correct_it(store, tool_name):
    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"), designer=create_designer("test"))
    attempts = []

    def drive(messages, info):
        retries = [p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]
        attempts.append(len(retries))
        if not retries:
            args = ({"uploaded_file_id": "nope"} if tool_name == "profile_csv"
                    else {"dataset_id": "nope", "question": "Total by region"})
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=args)])
        return ModelResponse(parts=[TextPart(content="I need the ds_ ID from the upload.")])

    with lead.override(model=FunctionModel(drive)):
        result = lead.run_sync("Profile nope", deps=deps)
    assert result.output == "I need the ds_ ID from the upload."
    assert attempts == [0, 1]


def test_find_dataset_lists_uploads(store):
    first = store.save_upload("first.csv", SALES)
    store.save_upload("second.csv", SALES)
    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"), designer=create_designer("test"))
    drive = call_then_summarize("find_dataset", {"query": "first"},
                                lambda part: ",".join(s["dataset_id"] if isinstance(s, dict) else s.dataset_id
                                                      for s in part.content))
    with lead.override(model=FunctionModel(drive)):
        result = lead.run_sync("Which datasets do we have?", deps=deps)
    assert result.output == first.dataset_id


def test_lead_answers_a_question_through_the_analyst(store, people):
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel

    from vis_agent.analyst.agent import create_analyst
    from vis_agent.deps import AppDeps
    from vis_agent.lead import create_lead
    from vis_agent.profiler.agent import create_profiler

    dataset, _profile = people
    analyst = create_analyst("test")

    def analyst_drive(messages, info):
        calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
        if not calls:
            return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={
                "sql": f'SELECT region, sum(amount) AS total FROM "{dataset}" GROUP BY 1 ORDER BY 2 DESC',
                "columns": [{"name": "region", "meaning": "Region", "kind": "geography", "source": "region"},
                            {"name": "total", "meaning": "Total", "kind": "measure", "source": "amount", "aggregate": "sum"}]})])
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_analysis", args={"summary": "West leads with 65."})])

    def lead_drive(messages, info):
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart(tool_name="answer_question", args={"dataset_id": dataset, "question": "Total by region"})])
        answer = returns[-1].model_response_object()  # the tool returns a Pydantic object; read its serialized form
        assert answer["summary"] == "West leads with 65." and answer["rows"] == [["West", 65], ["East", 40]]
        assert answer["row_count"] == 2 and answer["sql"].startswith("SELECT") and answer["clarification"] is None
        return ModelResponse(parts=[TextPart(content="West leads with 65.")])

    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=analyst, designer=create_designer("test"))
    lead = create_lead("test")
    with analyst.override(model=FunctionModel(analyst_drive)):
        with lead.override(model=FunctionModel(lead_drive)):
            result = lead.run_sync("Total by region", deps=deps)
    assert result.output == "West leads with 65."


def test_lead_tool_reports_unknown_datasets_as_failures(store):
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel

    from vis_agent.analyst.agent import create_analyst
    from vis_agent.deps import AppDeps
    from vis_agent.lead import create_lead
    from vis_agent.profiler.agent import create_profiler

    def lead_drive(messages, info):
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart(tool_name="answer_question", args={"dataset_id": "ds_" + "0" * 32, "question": "?"})])
        assert "not found" in str(returns[-1].content).lower()
        return ModelResponse(parts=[TextPart(content="No such dataset.")])

    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"), designer=create_designer("test"))
    lead = create_lead("test")
    with lead.override(model=FunctionModel(lead_drive)):
        assert lead.run_sync("?", deps=deps).output == "No such dataset."


CHART_SPEC = (
    "vis bar\ntitle Total by region\ndescription Total sales by region\n"
    "bind\n  category region\n  value total\nsort value desc\n"
)
CHART_EXPLANATION = "West leads with 20. A bar chart compares regional totals."


def analyst_chart_drive(messages, info):
    if not tool_returns(messages):
        import json

        prompt = json.loads(messages[0].parts[-1].content)
        return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={
            "sql": f'SELECT region, sum(amount) AS total FROM {prompt["table"]} GROUP BY 1 ORDER BY 2 DESC',
            "columns": [{"name": "region", "meaning": "Region", "kind": "category", "source": "region"},
                        {"name": "total", "meaning": "Total sales", "kind": "measure", "source": "amount",
                         "aggregate": "sum"}],
        })])
    return ModelResponse(parts=[ToolCallPart(tool_name="deliver_analysis", args={"summary": "West leads with 20."})])


def designer_chart_drive(messages, info):
    returns = tool_returns(messages)
    if not returns:
        return ModelResponse(parts=[ToolCallPart(tool_name="recommend_charts", args={"intent": "compare"})])
    if len(returns) == 1:
        return ModelResponse(parts=[ToolCallPart(tool_name="check_spec", args={"spec": CHART_SPEC})])
    checked = returns[-1].model_response_object()
    assert checked["ok"]
    return ModelResponse(parts=[ToolCallPart(tool_name="deliver_design", args={
        "spec": checked["canonical"], "explanation": CHART_EXPLANATION,
    })])


@pytest.fixture
def chart_run(store):
    from vis_agent.designer.agent import LeadChart
    from vis_agent.models import DataBrief

    source = store.save_upload("sales.csv", SALES, DataBrief(suggested_chart_type="bar"))
    lead, profiler = create_lead("test"), create_profiler("test")
    analyst, designer = create_analyst("test"), create_designer("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=analyst, designer=designer)

    def run(analyst_drive=analyst_chart_drive, designer_drive=designer_chart_drive):
        drive = call_then_summarize("make_chart", {"dataset_id": source.dataset_id, "question": "Total by region"},
                                    lambda part: LeadChart.model_validate(part.model_response_object()).model_dump_json())
        with profiler.override(model=TestModel(call_tools=[], custom_output_args=semantic_output(source.headers))), \
                analyst.override(model=FunctionModel(analyst_drive)), \
                designer.override(model=FunctionModel(designer_drive)), lead.override(model=FunctionModel(drive)):
            result = lead.run_sync("Chart total by region", deps=deps)
        return LeadChart.model_validate_json(result.output), result

    return run


def test_lead_exposes_make_chart(store):
    lead = create_lead("test")

    def drive(messages, info):
        assert "make_chart" in {tool.name for tool in info.function_tools}
        return ModelResponse(parts=[TextPart(content="ok")])

    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"),
                   designer=create_designer("test"))
    with lead.override(model=FunctionModel(drive)):
        assert lead.run_sync("hello", deps=deps).output == "ok"


def test_lead_makes_a_chart_through_the_agent(store, chart_run, monkeypatch):
    from vis_agent.designer.agent import render_id
    from vis_agent.designer.models import Compromise
    from vis_agent.render.base import Rendered

    compromise = Compromise(key="test", message="A renderer compromise.")

    def render(report, design, out_dir, renderer="gptvis"):
        assert out_dir == store.directory / "renders" / render_id(design.spec, report)
        out_dir.mkdir(parents=True)
        (out_dir / "chart.png").write_bytes(b"fake png")
        return Rendered(png=out_dir / "chart.png", html=out_dir / "chart.html", config=out_dir / "config.json",
                        width=640, height=480, seconds=0, non_background_share=0.5,
                        compromises=[*design.compromises, compromise], drawn_rows=2, folded_rows=0, dropped_rows=0)

    def designer_drive(messages, info):
        import json

        prompt = json.loads(messages[0].parts[-1].content)
        assert prompt["suggested_chart_type"] == "bar"
        return designer_chart_drive(messages, info)

    monkeypatch.setattr("vis_agent.designer.agent.render_design", render)
    chart, result = chart_run(designer_drive=designer_drive)
    assert re.search(r"/renders/[0-9a-f]{12}/chart\.png", result.output)
    assert "vis bar" in result.output and chart.spec.startswith("vis bar\n")
    assert chart.png_url == f"/renders/{chart.render_id}/chart.png"
    assert chart.html_url == f"/renders/{chart.render_id}/chart.html"
    assert (store.directory / chart.png_url.lstrip("/")).read_bytes() == b"fake png"
    assert chart.chart == "bar" and chart.explanation == CHART_EXPLANATION
    assert chart.summary == "West leads with 20." and chart.warnings == []
    assert compromise in chart.compromises and chart.clarification is None
    assert result.usage.requests == 8  # lead + profiler + analyst + designer share the run's usage


def test_make_chart_returns_the_analyst_clarification(chart_run, monkeypatch):
    def clarify(messages, info):
        return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification", args={
            "question": "Which amount do you mean?", "reason": "The measure is ambiguous.",
        })])

    def unexpected(*args, **kwargs):
        pytest.fail("An analyst clarification must stop before design or rendering")

    monkeypatch.setattr("vis_agent.designer.agent.render_design", unexpected)
    chart, _ = chart_run(analyst_drive=clarify, designer_drive=unexpected)
    assert chart.clarification.question == "Which amount do you mean?"
    assert chart.spec is None and chart.png_url is None and chart.html_url is None


@pytest.mark.parametrize("failure", ["RenderFailed", "RendererUnavailable"])
def test_make_chart_reports_a_render_failure_as_a_warning(chart_run, monkeypatch, failure):
    from vis_agent.render import base

    def render(*args, **kwargs):
        raise getattr(base, failure)("Renderer unavailable for this test.")

    monkeypatch.setattr("vis_agent.designer.agent.render_design", render)
    chart, _ = chart_run()
    assert chart.spec.startswith("vis bar\n") and chart.explanation == CHART_EXPLANATION
    assert chart.png_url is None and chart.html_url is None
    assert len(chart.warnings) == 1 and "Renderer unavailable for this test." in chart.warnings[0]


def test_make_chart_returns_the_designer_clarification(chart_run, monkeypatch):
    def clarify(messages, info):
        return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification", args={
            "question": "Which colors can I use?", "reason": "The colors lack contrast.",
        })])

    def unexpected(*args, **kwargs):
        pytest.fail("A designer clarification must stop before rendering")

    monkeypatch.setattr("vis_agent.designer.agent.render_design", unexpected)
    chart, _ = chart_run(designer_drive=clarify)
    assert chart.clarification.question == "Which colors can I use?"
    assert chart.summary == "West leads with 20."
    assert chart.spec is None and chart.png_url is None


@pytest.mark.parametrize("stage", ["analyst", "designer"])
def test_make_chart_preserves_warnings_when_an_agent_cannot_finish(chart_run, monkeypatch, stage):
    from pydantic_ai.exceptions import ModelAPIError

    def fail(messages, info):
        raise ModelAPIError("test", "Cannot finish this test.")

    def unexpected(*args, **kwargs):
        pytest.fail("An incomplete report must stop before rendering")

    monkeypatch.setattr("vis_agent.designer.agent.render_design", unexpected)
    chart, _ = chart_run(**{f"{stage}_drive": fail})
    assert chart.spec is None and chart.png_url is None
    assert len(chart.warnings) == 1 and "Cannot finish this test." in chart.warnings[0]


def test_make_chart_reports_a_database_failure_without_retry(store, monkeypatch):
    import duckdb

    async def fail(*args, **kwargs):
        raise duckdb.Error("Database unavailable.")

    monkeypatch.setattr("vis_agent.designer.agent.analyze_dataset", fail)
    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"),
                   designer=create_designer("test"))
    lead = create_lead("test")
    drive = call_then_summarize("make_chart", {"dataset_id": "ds_" + "0" * 32, "question": "Total by region"},
                                lambda part: f"outcome={part.outcome}: {part.content}")
    with lead.override(model=FunctionModel(drive)), capture_run_messages() as messages:
        result = lead.run_sync("Chart total by region", deps=deps)
    assert result.output == "outcome=failed: DuckDB could not run the analysis on this dataset."
    assert not [p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]
