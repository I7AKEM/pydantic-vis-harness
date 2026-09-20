import pytest

from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
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
    assert {"profile_csv", "find_dataset", "chart_capabilities"} <= seen["tools"]


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


def test_find_dataset_says_when_nothing_matches(store):
    store.save_upload("first.csv", SALES)
    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"), designer=create_designer("test"))
    drive = call_then_summarize("find_dataset", {"query": "sales.csv"}, lambda part: str(part.content))
    with lead.override(model=FunctionModel(drive)):
        result = lead.run_sync("Chart sales.csv", deps=deps)
    assert result.output == "No dataset matches 'sales.csv'. It has to be uploaded first; do not call draw or answer_question for it."


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
                "sql": f'SELECT region, sum(amount) AS total FROM "{dataset}_values" GROUP BY 1 ORDER BY 2 DESC',
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



# The request fixtures run the real lead and tool functions. Only model responses and rendering are fake.
from tests.requests.conftest import (  # noqa: E402,F401
    agents, call, dataset_id, deps, fake_models, fake_render, finish, reviewer,
)


def complete_lead(start_tool, args):
    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call(start_tool, **args)
        last = returned[-1]
        context = last.model_response_object()
        if last.tool_name in {"draw", "revise", "resume"}:
            if context.get("render"):
                return call("review_visualization", request_id=context["request_id"])
            return call("design_visualization", request_id=context["request_id"])
        if last.tool_name == "design_visualization":
            return call("render_visualization", request_id=context["request_id"])
        if last.tool_name == "render_visualization":
            return call("review_visualization", request_id=context["request_id"])
        if last.tool_name == "review_visualization":
            return call("publish_visualization", request_id=context["request_id"])
        return finish(context["card"])
    return drive


def test_lead_exposes_direct_specialist_tools(deps, agents):
    lead = agents[-1]

    def drive(messages, info):
        names = {tool.name for tool in info.function_tools}
        assert {"draw", "revise", "consult_analyst", "design_visualization", "review_visualization",
                "render_visualization", "publish_visualization", "find_dataset", "find_artifact"} <= names
        assert "make_chart" not in names
        return finish()

    with lead.override(model=FunctionModel(drive)):
        lead.run_sync("What can you do?", deps=deps)


def test_chat_lead_delegates_then_publishes_the_card(deps, dataset_id, agents, fake_models, fake_render):
    lead = agents[-1]
    drive = complete_lead("draw", {"dataset_id": dataset_id, "question": "Compare regional sales"})
    with capture_run_messages() as messages, lead.override(model=FunctionModel(drive)):
        result = lead.run_sync("Chart sales", deps=deps, conversation_id="chat-1")
    summary = deps.requests.list_requests()[0]
    request = deps.requests.get_request(summary.request_id)
    artifact = deps.requests.get_artifact(summary.artifact_id)
    assert request.status == "done" and request.caller.conversation_id == "chat-1"
    assert artifact.png_url in result.output and artifact.artifact_id in result.output
    assert artifact.report.result.rows == [["East", 10], ["West", 20]]
    # The text-only lead never receives renderer image bytes; only the reviewer does.
    assert not any(isinstance(part, UserPromptPart) and isinstance(part.content, list)
                   for message in messages for part in message.parts)
    # Six lead decisions plus one designer and one reviewer call.
    assert result.usage.requests == 8
    assert fake_models[0] == {"profiler": 0, "analyst": 0}


def test_chat_revision_links_a_new_version(deps, dataset_id, agents, fake_models, fake_render):
    lead = agents[-1]
    with lead.override(model=FunctionModel(complete_lead("draw", {"dataset_id": dataset_id, "question": "Sales"}))):
        lead.run_sync("Chart sales", deps=deps)
    first = deps.requests.list_artifacts(dataset_id=dataset_id)[0]
    with lead.override(model=FunctionModel(complete_lead("revise", {"artifact_id": first.artifact_id, "change": "Make it blue"}))):
        lead.run_sync("Make it blue", deps=deps)
    second = deps.requests.list_artifacts(dataset_id=dataset_id)[0]
    assert second.version == 2 and second.parent_artifact_id == first.artifact_id
    assert len(fake_render) == 2


def test_chat_draw_accepts_exact_uploaded_file_name(deps, dataset_id, agents, fake_models, fake_render):
    with agents[-1].override(model=FunctionModel(complete_lead("draw", {"dataset_id": "sales.csv", "question": "Sales"}))):
        agents[-1].run_sync("Chart sales.csv", deps=deps)
    assert deps.requests.list_artifacts(dataset_id=dataset_id)[0].dataset_id == dataset_id


def test_an_unknown_file_name_is_a_plain_failure_not_an_unrelated_upload(deps, dataset_id, agents, fake_models, fake_render):
    def drive(messages, info):
        returned = tool_returns(messages)
        if not returned:
            return call("draw", dataset_id="nothing.csv", question="Sales")
        assert returned[-1].outcome == "failed"
        assert "no uploaded dataset is named" in str(returned[-1].content).lower()
        return finish("Upload nothing.csv first.")

    with agents[-1].override(model=FunctionModel(drive)):
        result = agents[-1].run_sync("Chart nothing.csv", deps=deps)
    assert result.output == "Upload nothing.csv first." and deps.requests.list_requests() == []


def test_resume_is_offered_only_for_an_unfinished_chat_request(deps, agents, dataset_id):
    from vis_agent.requests.models import Caller
    from vis_agent.requests.service import create_request

    observed = []

    def drive(messages, info):
        observed.append("resume" in {tool.name for tool in info.function_tools})
        return finish()

    with agents[-1].override(model=FunctionModel(drive)):
        agents[-1].run_sync("continue", deps=deps, conversation_id="chat-1")
        create_request(deps, type="new", dataset_id=dataset_id, question="Sales",
                       caller=Caller(kind="chat", conversation_id="chat-1"))
        agents[-1].run_sync("continue", deps=deps, conversation_id="other-chat")
        agents[-1].run_sync("continue", deps=deps, conversation_id="chat-1")
    assert observed == [False, False, True]


def test_terminal_caller_identity_survives_delegation(deps, dataset_id, agents, fake_models, fake_render):
    from dataclasses import replace

    drive = complete_lead("draw", {"dataset_id": dataset_id, "question": "Sales"})
    with agents[-1].override(model=FunctionModel(drive)):
        agents[-1].run_sync("Chart sales", deps=replace(deps, caller_kind="terminal", caller_identity="terminal-user"))
    request = deps.requests.get_request(deps.requests.list_requests()[0].request_id)
    assert request.caller.kind == "terminal" and request.caller.identity == "terminal-user"

def test_an_empty_clarification_is_sent_back_to_the_model(store, people):
    from vis_agent.analyst.agent import analyze_dataset

    dataset_id, _profile = people
    profiler, analyst = create_profiler("test"), create_analyst("test")
    attempts = []

    def drive(messages, info):
        attempts.append(any(isinstance(p, RetryPromptPart) for p in messages[-1].parts))
        question = "" if len(attempts) == 1 else "Which amount?"
        return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification", args={"ask": question, "reason": "Two."})])

    with analyst.override(model=FunctionModel(drive)):
        import asyncio
        report = asyncio.run(analyze_dataset(store, profiler, analyst, dataset_id, "Total by region"))
    assert attempts == [False, True]
    assert report.clarification.question == "Which amount?"
