# tests/test_lead_validator.py
import asyncio

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.analyst.agent import create_analyst
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import create_designer
from vis_agent.lead import create_lead, invented_numbers
from vis_agent.profiler.agent import create_profiler


def test_invented_numbers_ignore_list_markers_ids_and_known_values():
    known = {"20", "33.333", "2026"}
    assert invented_numbers("1. West 20\n2. East 33.3 (art_ab12, rq_9f, 2026)", known) == []
    assert invented_numbers("The total is 999 and 20.", known) == ["999"]


def test_the_lead_is_sent_back_once_for_a_number_no_tool_returned(store):
    replies = iter(["The total is 999.", "The total is 12."])

    def drive(messages, info):
        return ModelResponse(parts=[TextPart(next(replies))])

    lead = create_lead("test")
    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"), designer=create_designer("test"))
    with lead.override(model=FunctionModel(drive)):
        result = asyncio.run(lead.run("What is 12 plus nothing?", deps=deps))
    assert result.output == "The total is 12."
