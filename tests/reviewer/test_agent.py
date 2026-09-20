# tests/reviewer/test_agent.py
import asyncio
import json
from datetime import datetime, timezone

import pytest
from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.analyst.models import Analysis, AnalysisReport
from vis_agent.designer.models import Compromise, Design
from vis_agent.findings import Finding
from vis_agent.models import QuestionAnswer
from vis_agent.reviewer.agent import create_reviewer, review_chart
from vis_agent.reviewer.rubric import REVIEWER_RULES, rubric_text
from tests.designer.conftest import cities

SPEC = "vis bar\ntitle Violations by city\ndescription Cities ranked\nbind\n  category city\n  value violations\nsort value desc\n"


def inputs():
    columns, result = cities()
    report = AnalysisReport(dataset_id="ds", question="Top cities by violations", language="English",
                            analysis=Analysis(sql="x", columns=columns, summary="City0 leads.", assumptions=["All years"]),
                            result=result, seconds=0, created_at=datetime.now(timezone.utc))
    design = Design(spec=SPEC, chart="bar", intent="rank", explanation="A bar ranks the cities.", considered=[],
                    compromises=[Compromise(key="direction", message="the legend stays where the package puts it")])
    return report, design


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "chart.png"
    path.write_bytes(b"\x89PNG fake")
    return path


def reviewing(findings, summary="Looked at it."):
    def drive(messages, info):
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_review", args={"summary": summary, "findings": findings})])
    return drive


def test_an_error_finding_makes_the_verdict_revise_and_the_picture_reaches_the_model(png):
    report, design = inputs()
    seen = {}

    def drive(messages, info):
        seen["content"] = messages[0].parts[-1].content
        return reviewing([{"rule": "R-5", "level": "error", "owner": "designer",
                           "message": "The bars are sorted ascending while the question asks for the top cities."}])(messages, info)

    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(drive)):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer, round_=1))
    assert reviewed.review.verdict == "revise" and reviewed.review.findings[0].owner == "designer" and reviewed.round == 1
    text, picture = seen["content"]
    assert isinstance(picture, BinaryContent) and picture.media_type == "image/png" and picture.data == b"\x89PNG fake"
    prompt = json.loads(text)
    assert prompt["chart"] == "bar" and prompt["rows"][0] == ["City0", 50] and prompt["row_count"] == 5
    assert prompt["compromises"] == ["the legend stays where the package puts it"] and prompt["assumptions"] == ["All years"]


def test_a_decision_only_the_caller_can_make_is_an_open_finding_not_a_send_back(png):
    report, design = inputs()
    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(reviewing([{"rule": "R-3", "level": "error", "owner": "user",
                                                            "message": "Cities, not hospitals: the caller's call."}]))):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert reviewed.review.verdict == "pass" and reviewed.review.findings[0].owner == "user"


def test_the_callers_answers_reach_the_reviewer(png):
    report, design = inputs()
    seen = {}

    def drive(messages, info):
        seen["prompt"] = json.loads(messages[0].parts[-1].content[0])
        return reviewing([])(messages, info)

    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(drive)):
        asyncio.run(review_chart(report, design, png, reviewer,
                                 clarifications=[QuestionAnswer(question="Which hospital column?", answer="Use the city.")]))
    assert seen["prompt"]["clarifications"] == [{"question": "Which hospital column?", "answer": "Use the city."}]


def test_warnings_alone_pass(png):
    report, design = inputs()
    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(reviewing([{"rule": "S5", "level": "warning", "owner": "designer",
                                                            "message": "Long labels crowd the axis."}]))):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert reviewed.review.verdict == "pass" and reviewed.warnings == []


def test_a_reviewer_that_cannot_finish_is_a_warning_not_a_verdict(png):
    report, design = inputs()

    def talking(messages, info):
        return ModelResponse(parts=[TextPart("I think it is fine.")])

    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(talking)):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert reviewed.review is None and reviewed.warnings and "could not finish" in reviewed.warnings[0]


def test_a_missing_picture_is_a_warning(tmp_path):
    report, design = inputs()
    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(reviewing([]))):
        reviewed = asyncio.run(review_chart(report, design, tmp_path / "missing.png", reviewer))
    assert reviewed.review is None and "could not finish" in reviewed.warnings[0]


def test_the_rubric_names_the_five_rules_and_their_levels():
    text = rubric_text()
    assert [rule for rule, _, _ in REVIEWER_RULES] == ["R-1", "R-2", "R-3", "R-4", "R-5"]
    assert "R-1 (error)" in text and "R-2 (warning)" in text and "do not report them again" in text


def test_a_finding_rejects_unknown_levels_and_owners():
    with pytest.raises(ValueError):
        Finding(rule="R-1", level="fatal", owner="designer", message="m")
    with pytest.raises(ValueError):
        Finding(rule="R-1", level="error", owner="lead", message="m")
