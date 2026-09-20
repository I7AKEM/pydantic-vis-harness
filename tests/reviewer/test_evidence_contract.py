"""Generic source-address and scope contracts, not assertions about a vision model's accuracy."""

import asyncio
import json

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage, UsageLimits

from tests.designer.conftest import column, table
from tests.reviewer.test_agent import inputs
from vis_agent.models import DataBrief, DisplayLabels
from vis_agent.reviewer.agent import ROWS_FOR_REVIEW, build_prompt, create_reviewer, review_chart
from vis_agent.reviewer.models import Review, ReviewerPrompt


def finding(reference=None, **changes):
    return {
        "rule": "R-1", "level": "error", "owner": "designer", "location": "First mark",
        "observed": "The visible label reads 5", "expected": "The source cell is 50",
        "reference": reference or {"kind": "cell", "row": 1, "column": "violations", "quote": "50"},
        **changes,
    }


def answer(findings=(), uncertainties=()):
    return ModelResponse(parts=[ToolCallPart("deliver_review", {
        "summary": "Inspection result.", "findings": list(findings), "uncertainties": list(uncertainties),
    })])


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "chart.png"
    path.write_bytes(b"PNG bytes only needed to test the tool boundary")
    return path


def test_named_rows_use_result_column_order_when_metadata_order_changes():
    report, design = inputs()
    report.analysis.columns.reverse()
    prompt = build_prompt(report, design, None, (), (), 1)
    assert prompt.rows[0] == {"city": "City0", "violations": 50}
    assert prompt.row_ids == [1, 2, 3, 4, 5]
    assert not prompt.rows_are_partial and prompt.truncated_cells == {}


def test_reference_coverage_distinguishes_row_excerpt_cell_abbreviation_and_omitted_columns():
    report, design = inputs()
    columns = [column("label", "category"), column("value", "measure"), column("outline", "geography"),
               column("notes", "category"), column("geometry", "category")]
    rows = [["A long but safe category label " * 3, i, "ordinary", "short", "hidden"]
            for i in range(ROWS_FOR_REVIEW + 2)]
    # Unsafe values beyond the preview still keep their whole column local.
    rows[-1][2] = "POLYGON ((1 2, 3 4, 1 2))"
    rows[-1][3] = "x" * 257
    report.analysis.columns, report.result = columns, table(columns, rows)
    prompt = build_prompt(report, design, None, (), (), 1)
    assert prompt.rows_are_partial and prompt.row_count == ROWS_FOR_REVIEW + 2
    assert len(prompt.rows) == ROWS_FOR_REVIEW
    assert set(prompt.omitted_columns) == {"outline", "notes", "geometry"}
    assert prompt.truncated_cells[1] == ["label"] and prompt.rows[0]["label"].endswith("…")
    assert prompt.rows[0]["value"] == 0
    assert all(set(row) == {"label", "value"} for row in prompt.rows)
    assert "POLYGON" not in prompt.model_dump_json() and "x" * 257 not in prompt.model_dump_json()
    assert rows[0][0] == "A long but safe category label " * 3  # no source mutation


def test_row_count_marks_partial_even_when_saved_rows_are_already_bounded():
    report, design = inputs()
    report.result.row_count = 500
    prompt = build_prompt(report, design, None, (), (), 1)
    assert len(prompt.rows) == 5 and prompt.rows_are_partial


def test_original_intent_caveats_and_approved_labels_survive_without_analysis_claims():
    report, design = inputs()
    brief = DataBrief(raw_question="Keep every source code literal; compare values.",
                      caveats=["Unit has not been supplied."], code_meanings={"city": {"City0": "Area zero"}},
                      display_labels={"en": DisplayLabels(value_labels={"city": {"City0": "Area zero"}})})
    prompt = build_prompt(report, design, brief, (), ("Viewport has horizontal scrolling",), 1)
    assert prompt.question == report.question and prompt.original_question == brief.raw_question
    assert prompt.caveats == brief.caveats and prompt.warnings == ["Viewport has horizontal scrolling"]
    assert prompt.code_meanings["city"]["City0"] == "Area zero"
    assert prompt.display_labels.value_labels["city"]["City0"] == "Area zero"
    assert "All years" not in prompt.model_dump_json() and "City0 leads." not in prompt.model_dump_json()


def test_old_saved_prompts_and_reviews_remain_readable():
    report, design = inputs()
    data = build_prompt(report, design, None, (), (), 1).model_dump(mode="json")
    data["rows"] = report.result.rows
    restored = ReviewerPrompt.model_validate(data)
    assert restored.rows[0] == {"city": "City0", "violations": 50}
    review = Review.model_validate({"verdict": "pass", "summary": "Readable.", "findings": []})
    assert review.evidence == [] and review.uncertainties == [] and review.image_id is None


def test_grounded_evidence_is_retained_for_the_lead_and_cannot_prove_perception(png):
    report, design = inputs()
    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(lambda messages, info: answer([finding()]))):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    review = reviewed.review
    assert review.verdict == "revise" and len(review.image_id) == 64
    assert review.evidence[0].reference.row == 1 and review.evidence[0].reference.column == "violations"
    assert '"quote":"50"' in review.findings[0].message
    # A fake model can still invent visible text. This test checks traceability, not vision correctness.
    assert review.evidence[0].observed == "The visible label reads 5"


@pytest.mark.parametrize("reference", [
    {"kind": "cell", "row": 99, "column": "violations", "quote": "50"},
    {"kind": "cell", "row": 1, "column": "invented", "quote": "50"},
    {"kind": "cell", "row": 1, "column": "violations", "quote": "500"},
    {"kind": "column", "column": "violations", "quote": "USD"},
    {"kind": "spec", "quote": "A setting not in the specification"},
    {"kind": "request", "quote": "Convert all codes into nationalities"},
])
def test_invalid_reference_requests_correction_not_an_automatic_pass(reference, png):
    report, design = inputs()
    calls = 0

    def drive(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return answer([finding(reference)])
        return answer(uncertainties=["Cannot establish the alleged mismatch from the supplied reference."])

    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(drive)):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert calls == 2 and reviewed.review.verdict == "uncertain" and reviewed.review.findings == []


def test_exact_caller_constraint_is_a_valid_reference(png):
    report, design = inputs()
    brief = DataBrief(raw_question="Keep source codes literal.")
    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(lambda messages, info: answer([
        finding({"kind": "request", "quote": "Keep source codes literal."}, rule="R-4",
                observed="A code has been expanded", expected="The caller requires literal codes"),
    ]))):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer, brief=brief))
    assert reviewed.review.verdict == "revise" and reviewed.requests == 1


def test_partial_source_cannot_prove_source_wide_absence(png):
    report, design = inputs()
    report.result.row_count = 100
    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(lambda messages, info: answer([
        finding({"kind": "source"}, observed="There is an unfamiliar category", expected="It must not exist"),
    ]))):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert reviewed.review is None and reviewed.requests == 3
    assert reviewed.warnings  # unknown remains unreviewed, not pass or a false defect


def test_abbreviated_source_cell_cannot_prove_a_full_text_mismatch(png):
    report, design = inputs()
    report.result.rows[0][0] = "A safe long category label whose final words are omitted"
    reviewer = create_reviewer("test")
    prompt = build_prompt(report, design, None, (), (), 1)
    with reviewer.override(model=FunctionModel(lambda messages, info: answer([
        finding({"kind": "cell", "row": 1, "column": "city", "quote": prompt.rows[0]["city"]}),
    ]))):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert reviewed.review is None


def test_identical_observed_and_expected_is_not_accepted_as_error(png):
    report, design = inputs()
    calls = 0

    def drive(messages, info):
        nonlocal calls
        calls += 1
        return (answer([finding(observed="50", expected="50")]) if calls == 1 else
                answer(uncertainties=["The crowded labels are not sufficiently legible to compare."]))

    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(drive)):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert calls == 2 and reviewed.review.verdict == "uncertain"


def test_uncertainty_never_erases_a_separate_confirmed_error(png):
    report, design = inputs()
    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(lambda messages, info: answer(
        [finding()], uncertainties=["A different tiny legend entry is unreadable at this resolution."]
    ))):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert reviewed.review.verdict == "revise" and reviewed.review.uncertainties


@pytest.mark.parametrize("level,uncertainties,expected", [
    ("error", [], "revise"),
    ("error", ["Another region cannot be inspected."], "revise"),
    ("warning", [], "pass"),
    ("warning", ["Another region cannot be inspected."], "uncertain"),
])
def test_owner_none_does_not_hide_errors_or_material_uncertainty(level, uncertainties, expected, png):
    report, design = inputs()
    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(lambda messages, info: answer(
        [finding(owner="none", level=level)], uncertainties=uncertainties,
    ))):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer))
    assert reviewed.review.verdict == expected
    assert reviewed.review.findings[0].owner == "none"
    assert reviewed.review.uncertainties == uncertainties
    assert reviewed.requests == 1  # ownership never schedules another reviewer/model call


def test_reviewer_shares_usage_and_cannot_retry_past_parent_budget(png):
    report, design = inputs()
    usage = RunUsage(requests=4)
    reviewer = create_reviewer("test")
    calls = 0

    def ignores_correction(messages, info):
        nonlocal calls
        calls += 1
        return answer([finding({"kind": "cell", "row": 999, "column": "violations", "quote": "50"})])

    with reviewer.override(model=FunctionModel(ignores_correction)):
        reviewed = asyncio.run(review_chart(report, design, png, reviewer, usage=usage,
                                            usage_limits=UsageLimits(request_limit=5)))
    assert calls == 1 and usage.requests == 5 and reviewed.requests == 1
    assert reviewed.review is None and reviewed.warnings


def test_instructions_do_not_delegate_translation_or_analysis_to_inspector(png):
    report, design = inputs()
    reviewer = create_reviewer("test")
    seen = {}

    def inspect_contract(messages, info):
        seen["instructions"] = info.instructions
        seen["prompt"] = json.loads(messages[0].parts[-1].content[0])
        return answer()

    with reviewer.override(model=FunctionModel(inspect_contract)):
        asyncio.run(review_chart(report, design, png, reviewer))
    assert "in the existing design call" not in seen["instructions"]
    assert "owner user" not in seen["instructions"]
    assert "Do not invent translations or code expansions" in seen["instructions"]
