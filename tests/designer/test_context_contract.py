"""Context plumbing checks, not claims that a fake model measures design quality."""

import json

import pytest
from pydantic_ai.messages import UserPromptPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.designer.agent import build_prompt, grammar, prompt_json
from vis_agent.designer.models import PreviousDesign, ReviewRound
from vis_agent.designer.syntax import parse
from vis_agent.findings import Finding
from vis_agent.models import DataBrief, QuestionAnswer

from .conftest import column, table
from .test_agent import report, run, tool_call


def payload(messages):
    prompts = [part.content for message in messages for part in message.parts
               if isinstance(part, UserPromptPart) and isinstance(part.content, str)]
    return json.loads(prompts[0])


@pytest.mark.parametrize("dimension,measure,codes", [
    ("batch_tag", "humidity_index", ["H-8", "L-3"]),
    ("segment_renamed_v17", "observed_zeta", ["07", "03"]),
    ("فئة_التجربة", "المؤشر_المقاس", ["س-ب", "ك-د"]),
])
def test_original_constraints_reach_the_model_despite_short_delegation(dimension, measure, codes):
    columns = [column(dimension, "category"), column(measure, "measure")]
    rows = [[codes[0], 3.125], [codes[1], 1.75]]
    source = report(columns, table(columns, rows), question="Compare the supplied measurements.")
    raw = f"Compare {measure} by {dimension}. Keep {codes!r} literal; do not infer a unit."
    enriched = f"The prepared result has one measurement per {dimension}; retain the supplied precision."
    caveat = f"{dimension} contains identifiers, not a codebook of semantic meanings."
    brief = DataBrief(raw_question=raw, enriched_question=enriched, caveats=[caveat],
                      source="private://source-location", query="SELECT secret_source FROM upstream")
    direction = "Use a horizontal comparison with no unnecessary decoration."
    before = source.model_dump_json()
    observed = []

    def drive(messages, info):
        context = payload(messages)
        observed.append(context)
        assert context["question"] == source.question
        assert context["raw_question"] == raw
        assert context["enriched_question"] == enriched
        assert context["caveats"] == [caveat]
        assert context["previous"] == {"spec": None, "change": direction}
        assert context["columns"][1]["unit"] is None
        assert context["preview"] == rows
        assert "A requested revision" not in messages[0].instructions
        assert "SELECT secret_source" not in json.dumps(context)
        assert "private://source-location" not in json.dumps(context)
        return tool_call("deliver_design", spec=(
            f"vis bar\ntitle Comparison\ndescription Supplied measurements by identifier\n"
            f"bind\n  category {dimension}\n  value {measure}\n"
        ), explanation="Position compares the supplied measurements; identifiers stay literal.")

    result = run(source, FunctionModel(drive), brief=brief,
                 previous=PreviousDesign(spec=None, change=direction))
    assert result.design is not None, result.warnings
    assert result.requests == 1 and len(observed) == 1
    assert parse(result.design.spec).bind == {"category": dimension, "value": measure}
    assert source.model_dump_json() == before


def test_duplicate_upstream_questions_do_not_expand_the_serialized_prompt():
    columns = [column("stratum", "category"), column("signal", "measure")]
    source = report(columns, table(columns, [["q", 8]]), question="Show the supplied signal.")
    brief = DataBrief(raw_question=source.question, enriched_question=source.question)
    prompt = build_prompt(source, brief)
    assert prompt.raw_question == prompt.enriched_question == source.question
    assert prompt_json(prompt) == prompt_json(build_prompt(source, None))

    distinct = "Keep stratum literal and do not assign a unit to signal."
    brief = DataBrief(raw_question=distinct, enriched_question=distinct)
    data = json.loads(prompt_json(build_prompt(source, brief)))
    assert data["raw_question"] == distinct
    assert "enriched_question" not in data


def test_initial_clarification_is_preserved_without_claiming_a_prior_chart():
    columns = [column("experiment", "category"), column("reading", "measure")]
    source = report(columns, table(columns, [["control", 1.2], ["treatment", 1.5]]))
    clarification = QuestionAnswer(question="What should be emphasized?", answer="The contrast, not a total.")

    def drive(messages, info):
        assert payload(messages)["clarifications"] == [clarification.model_dump()]
        assert "A requested revision" not in messages[0].instructions
        return tool_call("deliver_design", spec="vis table\ntitle Readings\ndescription Readings by experiment\n",
                         explanation="Each supplied reading remains directly comparable.")

    result = run(source, FunctionModel(drive), clarifications=[clarification])
    assert result.design is not None and result.requests == 1


def test_changed_goal_remains_distinct_from_an_unchanged_result_table():
    columns = [column("period_label", "time"), column("output_rate", "measure", unit="kg/h")]
    source = report(columns, table(columns, [["P1", 4], ["P2", 7], ["P3", 6]]), question="Display the result.")
    trend = build_prompt(source, DataBrief(raw_question="Show how output evolves over the supplied periods.",
                                           intent="trend"))
    rank = build_prompt(source, DataBrief(raw_question="Compare output by period; identify the highest period.",
                                          intent="rank"))
    assert trend.raw_question != rank.raw_question
    assert trend.intent == "trend" and rank.intent == "rank"
    assert trend.columns == rank.columns and trend.preview == rank.preview


def test_uncertain_feedback_can_return_an_unchanged_spec_in_one_call():
    columns = [column("batch_code", "category"), column("assay_reading", "measure")]
    source = report(columns, table(columns, [[f"B{i:03}", i + 0.125] for i in range(18)]))
    spec = "vis table\ntitle Assays\ndescription Supplied assay readings\n"
    allegation = "B017 might be invented because it does not appear in the supplied preview."
    review = ReviewRound(spec=spec, summary="The excerpt does not establish this claim.", findings=[
        Finding(rule="R-3", level="warning", owner="none", message=allegation),
    ])
    original = "Keep the supplied batch identifiers literal; their semantic meanings are unknown."

    def drive(messages, info):
        data = payload(messages)
        assert data["raw_question"] == original
        assert data["preview_is_partial"] is True
        assert data["row_count"] == 18
        assert data["review"]["findings"][0]["message"] == allegation
        assert data["review"]["findings"][0]["level"] == "warning"
        guidance = messages[0].instructions
        assert "allegations to assess" in guidance and "You do not receive the image" in guidance
        assert "A partial data preview cannot establish" in guidance
        assert "severity alone does not prove a defect" in guidance
        return tool_call("deliver_design", spec=spec, explanation=(
            "No change: absence from a partial preview does not establish an invented identifier. "
            "The source-bound table is retained; I have not visually verified the image."
        ))

    result = run(source, FunctionModel(drive), brief=DataBrief(raw_question=original), review=review,
                 previous=PreviousDesign(spec=spec, change="Assess the review finding."))
    assert result.design is not None, result.warnings
    assert result.requests == 1
    assert parse(result.design.spec) == parse(spec)
    assert result.design.explanation.startswith("No change:")


def test_grammar_examples_do_not_assign_meanings_to_ambiguous_codes():
    assert '["gender", "M", "ذكور"]' not in grammar()
    assert "use only established meanings" in grammar()
