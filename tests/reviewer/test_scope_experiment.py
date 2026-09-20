"""Local contracts for the controlled reviewer trial; model quality is scored separately."""

import asyncio
import json

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from evals.reviewer.compare_scope import (
    AttemptedModel, EvidenceFinding, TRIAL20_LEGACY, capture_contract, experiment_reviewer, grounded_payload, grounded_reviewer,
    named_payload, select_trial20, summary, summary_first_reviewer,
)
from tests.reviewer.test_agent import inputs
from vis_agent.reviewer.agent import ReviewerDeps, build_prompt, create_reviewer


def test_named_reference_rows_use_result_order_not_column_metadata_order():
    report, design = inputs()
    report.analysis.columns.reverse()
    prompt = build_prompt(report, design, None, (), (), 1)
    payload = grounded_payload(prompt, report.result.columns)
    assert payload["rows"][0] == {"city": "City0", "violations": 50}
    assert "question" not in payload and "clarifications" not in payload and "round" not in payload
    assert payload["spec"] == design.spec


def test_named_ablation_changes_only_the_rows_encoding():
    report, design = inputs()
    prompt = build_prompt(report, design, None, (), (), 1)
    before = prompt.model_dump(mode="json")
    after = named_payload(prompt, report.result.columns)
    assert {k: v for k, v in before.items() if k != "rows"} == {k: v for k, v in after.items() if k != "rows"}
    assert after["rows"][0] == {"city": "City0", "violations": 50}


@pytest.mark.parametrize("field,value", [("owner", "analyst"), ("owner", "user"), ("rule", "S5")])
def test_visual_finding_schema_excludes_analytical_owners_and_rules(field, value):
    finding = dict(rule="R-2", level="error", owner="designer", location="Donut left arc",
                   observed="First digit is clipped", expected="373,877 should be readable")
    finding[field] = value
    with pytest.raises(ValidationError):
        EvidenceFinding.model_validate(finding)


def test_visible_evidence_survives_the_existing_review_contract():
    report, design = inputs()
    prompt = build_prompt(report, design, None, (), (), 1)
    reviewer = grounded_reviewer("test")

    def drive(messages, info):
        return ModelResponse(parts=[ToolCallPart("deliver_review", {
            "summary": "One clipped label.", "findings": [{
                "rule": "R-2", "level": "error", "owner": "designer", "location": "Donut left arc",
                "observed": "First digit is clipped", "expected": "373,877 should be readable",
            }],
        })])

    with reviewer.override(model=FunctionModel(drive)):
        result = asyncio.run(reviewer.run(json.dumps(grounded_payload(prompt, report.result.columns)),
                                         deps=ReviewerDeps(prompt)))
    assert result.output.verdict == "revise"
    assert result.output.findings[0].owner == "designer"
    assert result.output.findings[0].message.startswith(
        "Donut left arc: First digit is clipped — 373,877 should be readable"
    )
    assert result.output.evidence[0].reference.kind == "image"


def test_unreviewed_is_not_success_or_excluded_from_the_denominator():
    rows = [dict(expected="pass", got="pass", seconds=2, requests=1),
            dict(expected="pass", got="unreviewed", seconds=30, requests=1),
            dict(expected="revise", got="revise", seconds=4, requests=1)]
    scored = summary(rows)
    assert scored["agreement"] == 2 / 3
    assert scored["clean_acceptance"] == .5 and scored["bad_detection"] == 1
    assert scored["requests"] == 3


def test_trial20_is_fixed_and_balanced_before_calls():
    cases = [dict(name=name, set="legacy", expected="pass" if i < 8 else "revise")
             for i, name in enumerate(TRIAL20_LEGACY)]
    cases += [dict(name=f"probe-{i}", set="visible-regressions", expected="pass" if i < 2 else "revise")
              for i in range(5)]
    selected = select_trial20(list(reversed(cases)))
    assert len(selected) == 20 and [c["name"] for c in selected[:15]] == list(TRIAL20_LEGACY)
    assert sum(c["expected"] == "pass" for c in selected) == 10
    with pytest.raises(ValueError):
        select_trial20(cases[:-1])


def test_cancelled_model_requests_are_still_counted():
    async def never_returns(messages, info):
        await asyncio.Event().wait()

    measured = AttemptedModel(FunctionModel(never_returns))
    reviewer = grounded_reviewer("test")
    report, design = inputs()
    prompt = build_prompt(report, design, None, (), (), 1)

    async def run():
        with reviewer.override(model=measured):
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(.01):
                    await reviewer.run("Inspect", deps=ReviewerDeps(prompt))

    asyncio.run(run())
    assert measured.attempts == 1 and measured.completed == 0


def test_summary_first_changes_only_output_argument_order():
    report, design = inputs()
    prompt = build_prompt(report, design, None, (), (), 1)
    baseline = asyncio.run(capture_contract(create_reviewer("test"), prompt))
    reordered = asyncio.run(capture_contract(summary_first_reviewer("test"), prompt))
    assert baseline["instructions"] == reordered["instructions"]
    assert baseline["model_settings"] == reordered["model_settings"]
    first = baseline["output_tools"][0]
    second = reordered["output_tools"][0]
    assert first["description"] == second["description"] and first["name"] == second["name"]
    assert list(first["parameters_json_schema"]["properties"]) == ["findings", "summary", "uncertainties"]
    assert list(second["parameters_json_schema"]["properties"]) == ["summary", "findings", "uncertainties"]
    assert baseline["sha256"] != reordered["sha256"]
    first["parameters_json_schema"]["required"].sort()
    second["parameters_json_schema"]["required"].sort()
    assert first == second


@pytest.mark.parametrize("variant", ["baseline", "named", "grounded", "summary-first"])
def test_thinking_ablation_changes_only_model_thinking_setting(variant):
    report, design = inputs()
    prompt = build_prompt(report, design, None, (), (), 1)
    before = asyncio.run(capture_contract(experiment_reviewer(variant, "test"), prompt))
    after = asyncio.run(capture_contract(experiment_reviewer(variant, "test", "low"), prompt))
    assert before["declared_model_settings"]["thinking"] is False
    assert after["declared_model_settings"]["thinking"] == "low"
    assert before["sha256"] != after["sha256"]
    before["declared_model_settings"]["thinking"] = "low"
    assert {k: v for k, v in before.items() if k != "sha256"} == {k: v for k, v in after.items() if k != "sha256"}
