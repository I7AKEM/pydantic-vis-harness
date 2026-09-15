# tests/designer/test_ledger.py
import asyncio
from datetime import datetime, timezone

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.analyst.models import Analysis, AnalysisReport
from vis_agent.designer.agent import create_designer, design_chart
from vis_agent.designer.check import check_spec
from tests.designer.conftest import cities
from tests.requests.conftest import tool_returns


def report(question, language="English"):
    columns, result = cities()
    return AnalysisReport(dataset_id="ds", question=question, language=language,
                          analysis=Analysis(sql="x", columns=columns, summary="City0 leads."), result=result,
                          seconds=0, created_at=datetime.now(timezone.utc))


def delivering(spec):
    def drive(messages, info):
        if not tool_returns(messages):
            return ModelResponse(parts=[ToolCallPart(tool_name="check_spec", args={"spec": spec})])
        checked = tool_returns(messages)[-1].model_response_object()
        assert checked["ok"], checked
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_design", args={
            "spec": checked["canonical"], "explanation": "City0 leads. A bar ranks the cities."})])
    return drive


SPEC = "vis bar\ntitle Top 5 cities by violations\ndescription Cities ranked by violations\nbind\n  category city\n  value violations\nsort value desc\n"


def test_a_number_in_the_title_the_question_did_not_name_is_a_compromise():
    designer = create_designer("test")
    with designer.override(model=FunctionModel(delivering(SPEC))):
        designed = asyncio.run(design_chart(report("Top five cities"), designer))
        named = asyncio.run(design_chart(report("Top 5 cities"), designer))
    assert [c.key for c in designed.design.compromises] == ["title"] and "5" in designed.design.compromises[0].message
    assert "title" not in [c.key for c in named.design.compromises]


def test_an_arabic_spec_without_a_direction_records_no_direction_compromise():
    columns, result = cities()
    plain = "vis bar\ntitle عدد المخالفات حسب المدينة\ndescription وصف\nlanguage ar\nbind\n  category city\n  value violations\n"
    explicit = plain + "direction rtl\n"
    assert "direction" not in [c.key for c in check_spec(plain, columns, result).compromises]
    assert "direction" in [c.key for c in check_spec(explicit, columns, result).compromises]
