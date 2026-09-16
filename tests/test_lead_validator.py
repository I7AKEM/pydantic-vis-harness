"""Prose policy no longer adds another lead request on top of valid tool delegation."""

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.analyst.agent import create_analyst
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import create_designer
from vis_agent.lead import create_lead
from vis_agent.profiler.agent import create_profiler


def test_presentation_suggestions_do_not_trigger_numeric_prose_retries(store):
    calls = []

    def drive(messages, info):
        calls.append(1)
        return ModelResponse(parts=[TextPart("I can suggest 3 chart options.")])

    lead = create_lead("test")
    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"), designer=create_designer("test"))
    with lead.override(model=FunctionModel(drive)):
        result = lead.run_sync("Can you help choose a chart?", deps=deps)
    assert result.output == "I can suggest 3 chart options." and len(calls) == 1
