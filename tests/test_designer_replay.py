import asyncio
from copy import deepcopy

import pytest
from pydantic_ai import Agent, ToolOutput
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from evals.designer.agent.replay import CountingModel, model_turn_metrics, replay_input, replay_settings, summarise


def fixture_case():
    report = {
        "dataset_id": "ds_replay", "question": "Compare female and male percentages", "language": "English",
        "analysis": {"sql": "SELECT * FROM source", "summary": "", "columns": [
            {"name": "count", "meaning": "Count", "kind": "measure"},
            {"name": "percentage", "meaning": "After revision", "kind": "share", "unit": "%"},
        ]},
        "result": {"sql": "SELECT * FROM source", "columns": ["count", "percentage"],
                   "types": ["INTEGER", "DOUBLE"], "rows": [[10, 20.0]], "row_count": 1, "seconds": 0},
        "seconds": 0, "created_at": "2026-09-17T00:00:00Z",
    }
    return {
        "name": "saved-case", "requests": [{"steps": {"analyze": report}}],
        "turns": [{
            "tool_sequence": [{"name": "design_visualization", "args": {
                "direction": "Use a supported comparison", "required_columns": ["percentage"],
                "columns": [{"name": "percentage", "meaning": "Original percentage", "kind": "share", "unit": "%"}],
            }}],
            "messages": [{"parts": [{"tool_name": "draw", "content": {"table": {"columns": [
                {"name": "count", "meaning": "Original count", "kind": "measure", "distinct": 1},
                {"name": "percentage", "meaning": "percentage", "kind": "measure", "distinct": 1},
            ]}}}]}],
        }],
    }


def test_replay_restores_initial_metadata_then_merges_partial_annotations_without_mutation():
    case = fixture_case()
    before = deepcopy(case)
    inputs = replay_input(case)
    assert case == before
    columns = inputs["report"]["analysis"]["columns"]
    assert [value["meaning"] for value in columns] == ["Original count", "Original percentage"]
    assert columns[1]["unit"] == "%"
    assert inputs["report"]["result"]["rows"] == [[10, 20.0]]
    assert inputs["direction"] == "Use a supported comparison"
    assert inputs["required_columns"] == ["percentage"]


def test_intent_only_changes_direction_not_source_or_binding_requirements():
    case = fixture_case()
    saved, intent = replay_input(case), replay_input(case, "intent")
    assert intent["direction"] == intent["report"]["question"]
    assert saved["report"] == intent["report"]
    assert saved["required_columns"] == intent["required_columns"]


def test_replay_rejects_unknown_annotation_instead_of_changing_source_schema():
    case = fixture_case()
    case["turns"][0]["tool_sequence"][0]["args"]["columns"][0]["name"] = "invented"
    with pytest.raises(ValueError, match="annotation identities"):
        replay_input(case)


def test_replay_summary_does_not_claim_semantic_or_visual_success():
    row = {"model": "example", "guidance": "saved", "result": {"design": {}, "requests": 2, "seconds": 3.5},
           "rendered": {}, "source_unchanged": True, "missing_required_columns": []}
    result = summarise([row])[0]
    assert result["rendered"] == 1
    assert result["requests"] == 2
    assert result["semantic_and_visual_correctness"].startswith("not scored")


def test_routing_override_keeps_reasoning_and_does_not_mutate_defaults():
    model = "openrouter:z-ai/glm-5.3"
    normal, latency = replay_settings(model, "default"), replay_settings(model, "latency")
    assert normal["openrouter_provider"] == {"require_parameters": True}
    assert latency["openrouter_provider"] == {"require_parameters": True, "sort": "latency"}
    assert normal["openrouter_reasoning"] == latency["openrouter_reasoning"] == {"effort": "low"}
    assert replay_settings(model, "default") == normal


def test_timeout_record_distinguishes_attempted_turn_from_completed_response():
    messages = [{"kind": "request"}, {"kind": "response", "provider_details": {"downstream_provider": "Example"}},
                {"kind": "request"}]
    assert model_turn_metrics(messages) == {"model_request_messages": 2, "model_response_messages": 1,
                                           "downstream_providers": ["Example"]}


def test_model_counter_counts_an_inflight_timeout_without_a_completed_response():
    async def respond(messages, info):
        await asyncio.sleep(1)
        return ModelResponse(parts=[TextPart("unused")])

    counted = CountingModel(FunctionModel(respond))
    agent = Agent("test")

    async def run():
        with agent.override(model=counted):
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.01):
                    await agent.run("test")

    asyncio.run(run())
    assert counted.requests_started == 1


def test_model_counter_does_not_count_terminal_output_acknowledgement_as_another_call():
    def finish(value: str) -> str:
        return value

    counted = CountingModel(FunctionModel(lambda messages, info: ModelResponse(
        parts=[ToolCallPart("finish", {"value": "done"})],
    )))
    agent = Agent("test", output_type=ToolOutput(finish, name="finish"))
    with agent.override(model=counted):
        result = asyncio.run(agent.run("test"))
    assert result.output == "done"
    assert len([message for message in result.all_messages() if message.kind == "request"]) == 2
    assert counted.requests_started == 1
