from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from vis_agent.analyst.agent import create_analyst
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
        lead.run_sync("hello", deps=AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test")))
    assert lead.name == "vis-lead"
    assert {"profile_csv", "find_dataset"} <= seen["tools"]


def test_lead_profiles_a_csv_through_the_agent(store):
    source = store.save_upload("sales.csv", SALES)
    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"))

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


def test_unknown_id_is_a_failed_tool_result_not_a_retry(store):
    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"))
    drive = call_then_summarize("profile_csv", {"uploaded_file_id": "ds_" + "0" * 32},
                                lambda part: f"outcome={part.outcome}: {part.content}")
    with lead.override(model=FunctionModel(drive)):
        with capture_run_messages() as messages:
            result = lead.run_sync("Profile ds_000", deps=deps)
    assert result.output.startswith("outcome=failed: File ID not found")
    assert not [p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]


def test_malformed_id_asks_the_model_to_correct_it(store):
    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"))
    attempts = []

    def drive(messages, info):
        retries = [p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]
        attempts.append(len(retries))
        if not retries:
            return ModelResponse(parts=[ToolCallPart(tool_name="profile_csv", args={"uploaded_file_id": "nope"})])
        return ModelResponse(parts=[TextPart(content="I need the ds_ ID from the upload.")])

    with lead.override(model=FunctionModel(drive)):
        result = lead.run_sync("Profile nope", deps=deps)
    assert result.output == "I need the ds_ ID from the upload."
    assert attempts == [0, 1]


def test_find_dataset_lists_uploads(store):
    first = store.save_upload("first.csv", SALES)
    store.save_upload("second.csv", SALES)
    lead, profiler = create_lead("test"), create_profiler("test")
    deps = AppDeps(store=store, profiler=profiler, analyst=create_analyst("test"))
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

    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=analyst)
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

    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"))
    lead = create_lead("test")
    with lead.override(model=FunctionModel(lead_drive)):
        assert lead.run_sync("?", deps=deps).output == "No such dataset."
