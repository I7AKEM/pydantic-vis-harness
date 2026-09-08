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


@pytest.mark.parametrize("tool_name", ["profile_csv", "draw"])
def test_unknown_id_is_a_failed_tool_result_not_a_retry(store, tool_name):
    from vis_agent.requests.store import RequestStore

    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"), designer=create_designer("test"),
                   requests=RequestStore(store))
    args = ({"uploaded_file_id": "ds_" + "0" * 32} if tool_name == "profile_csv"
            else {"dataset_id": "ds_" + "0" * 32, "question": "Total by region"})
    drive = call_then_summarize(tool_name, args,
                                lambda part: f"outcome={part.outcome}: {part.content}")
    with lead.override(model=FunctionModel(drive)):
        with capture_run_messages() as messages:
            result = lead.run_sync("Profile ds_000", deps=deps)
    assert result.output.startswith("outcome=failed: File ID not found")
    assert not [p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]


@pytest.mark.parametrize("tool_name", ["profile_csv", "draw"])
def test_malformed_id_asks_the_model_to_correct_it(store, tool_name):
    from vis_agent.requests.store import RequestStore

    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"), designer=create_designer("test"),
                   requests=RequestStore(store))
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
def conversation(store, monkeypatch):
    """A lead with fake specialists and a fake renderer, run the way the web chat runs it."""
    from vis_agent.render.base import Rendered
    from vis_agent.requests.store import RequestStore

    source = store.save_upload("sales.csv", SALES)
    lead, profiler = create_lead("test"), create_profiler("test")
    analyst, designer = create_analyst("test"), create_designer("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=analyst, designer=designer, requests=RequestStore(store))

    def render(report, design, out_dir, renderer="gptvis"):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "chart.png").write_bytes(b"png")
        return Rendered(png=out_dir / "chart.png", html=out_dir / "chart.html", config=out_dir / "config.json",
                        width=2400, height=1350, seconds=0.1, non_background_share=0.2, compromises=[],
                        drawn_rows=2, folded_rows=0, dropped_rows=0)

    monkeypatch.setattr("vis_agent.requests.runner.render_design", render)

    def run(message, drive, analyst_drive=analyst_chart_drive, designer_drive=designer_chart_drive, **kwargs):
        with profiler.override(model=TestModel(call_tools=[], custom_output_args=semantic_output(source.headers))), \
                analyst.override(model=FunctionModel(analyst_drive)), \
                designer.override(model=FunctionModel(designer_drive)), lead.override(model=FunctionModel(drive)):
            return lead.run_sync(message, deps=deps, **kwargs)

    return source.dataset_id, deps, run


def outcome_of(part):
    from vis_agent.requests.models import RequestOutcome

    return RequestOutcome.model_validate(part.model_response_object())


def test_lead_exposes_the_phase_6_tools(store):
    lead = create_lead("test")

    def drive(messages, info):
        names = {tool.name for tool in info.function_tools}
        assert {"profile_csv", "find_dataset", "answer_question", "draw", "revise", "resume", "find_artifact"} <= names
        assert "make_chart" not in names
        return ModelResponse(parts=[TextPart(content="ok")])

    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"),
                   designer=create_designer("test"))
    with lead.override(model=FunctionModel(drive)):
        assert lead.run_sync("hello", deps=deps).output == "ok"


def test_draw_delivers_an_artifact_and_records_the_conversation(conversation):
    dataset_id, deps, run = conversation
    drive = call_then_summarize("draw", {"dataset_id": dataset_id, "question": "Total by region"},
                                lambda part: outcome_of(part).model_dump_json())
    result = run("Chart total by region", drive, conversation_id="chat-1")
    from vis_agent.requests.models import RequestOutcome

    outcome = RequestOutcome.model_validate_json(result.output)
    assert outcome.status == "done" and outcome.artifact.chart == "bar" and outcome.artifact.rows == [["West", 20], ["East", 10]]
    assert outcome.artifact.png_url.startswith("/renders/")
    request = deps.requests.get_request(outcome.request_id)
    assert request.caller.kind == "chat" and request.caller.conversation_id == "chat-1"


def test_draw_returns_the_question_and_resume_answers_it(conversation):
    import json

    dataset_id, deps, run = conversation

    def asking(messages, info):
        prompt = json.loads(messages[0].parts[-1].content)
        if not prompt.get("clarifications"):
            return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification",
                                                     args={"question": "Which amount?", "reason": "Two."})])
        assert prompt["clarifications"][0]["answer"] == "The amount column"
        return analyst_chart_drive(messages, info)

    drive = call_then_summarize("draw", {"dataset_id": dataset_id, "question": "Total by region"},
                                lambda part: outcome_of(part).model_dump_json())
    from vis_agent.requests.models import RequestOutcome

    first = RequestOutcome.model_validate_json(run("Chart total by region", drive, analyst_drive=asking,
                                                   conversation_id="chat-1").output)
    assert first.status == "waiting" and first.clarification.question == "Which amount?"
    resume = call_then_summarize("resume", {"request_id": "", "answer": "The amount column"},
                                 lambda part: outcome_of(part).model_dump_json())
    second = RequestOutcome.model_validate_json(run("The amount column", resume, analyst_drive=asking,
                                                    conversation_id="chat-1").output)
    assert second.status == "done" and second.request_id == first.request_id and second.artifact.chart == "bar"


def test_revise_links_a_new_version(conversation):
    dataset_id, deps, run = conversation
    from vis_agent.requests.models import RequestOutcome

    draw = call_then_summarize("draw", {"dataset_id": dataset_id, "question": "Total by region"},
                               lambda part: outcome_of(part).model_dump_json())
    v1 = RequestOutcome.model_validate_json(run("Chart total by region", draw).output).artifact
    revise = call_then_summarize("revise", {"artifact_id": v1.artifact_id, "change": "Make it blue", "redo_analysis": False},
                                 lambda part: outcome_of(part).model_dump_json())
    v2 = RequestOutcome.model_validate_json(run("Make it blue", revise).output).artifact
    assert v2.version == 2 and v2.parent_artifact_id == v1.artifact_id and v2.change == "Make it blue"
    found = call_then_summarize("find_artifact", {"artifact_id": v1.artifact_id, "dataset_id": ""},
                                lambda part: str(len(part.content)))
    assert run("Show the versions", found).output == "2"


def test_lead_tools_report_unknown_ids_as_failures(conversation):
    dataset_id, deps, run = conversation

    def drive(messages, info):
        returns = tool_returns(messages)
        if not returns:
            return ModelResponse(parts=[ToolCallPart(tool_name="revise", args={
                "artifact_id": "art_" + "0" * 32, "change": "x", "redo_analysis": False})])
        assert "not found" in str(returns[-1].content).lower()
        return ModelResponse(parts=[TextPart(content="No such artifact.")])

    assert run("Change it", drive).output == "No such artifact."


def test_resume_without_a_request_in_the_conversation_is_a_failure(conversation):
    dataset_id, deps, run = conversation

    def drive(messages, info):
        returns = tool_returns(messages)
        if not returns:
            return ModelResponse(parts=[ToolCallPart(tool_name="resume", args={"request_id": "", "answer": ""})])
        assert "no unfinished request" in str(returns[-1].content).lower()
        return ModelResponse(parts=[TextPart(content="Nothing to continue.")])

    assert run("continue", drive, conversation_id="chat-9").output == "Nothing to continue."
