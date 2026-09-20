"""Offline regression metrics, explicit semantics, and fail-closed E2E feedback."""

import asyncio
from copy import deepcopy

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from evals.lead import run
from vis_agent.models import DataBrief


def numeric_artifact():
    return {"columns": [{"name": "gender", "kind": "category"},
                        {"name": "count_under_30", "kind": "measure"},
                        {"name": "percentage", "kind": "measure"}],
            "rows": [["F", 121, 49.5], ["M", 125, 50.5]], "row_count": 2}


@pytest.mark.parametrize("identifier", ["count_under_30", "`count_under_30`", "**count_under_30**",
                                         "[count_under_30](/datasets/abc/profile)"])
def test_literal_source_identifiers_are_not_numeric_claims(identifier):
    assert run.answer_numbers_match(f"{identifier}: 121 and 125.", numeric_artifact(), "Show count_under_30.")


@pytest.mark.parametrize("reply", ["count_under_30 is 30.", "count_under_30 is 31.",
                                    "count_under_31 is 121.", "fake_count_under_30 is 121.",
                                    "count_under_30_suffix is 121."])
def test_identifier_exemption_never_whitelists_adjacent_or_unknown_numeric_claims(reply):
    assert not run.answer_numbers_match(reply, numeric_artifact(), "Show count_under_30.")


def test_identifier_can_contain_unicode_and_actual_30_remains_allowed_when_measured():
    artifact = numeric_artifact()
    artifact["columns"][1]["name"] = "الفئة_30"
    assert run.answer_numbers_match("الفئة_30: 121.", artifact, "Show الفئة_30.")
    assert not run.answer_numbers_match("الفئة_30: 30.", artifact, "Show الفئة_30.")
    artifact["rows"][0][1] = 30
    assert run.answer_numbers_match("الفئة_30: 30.", artifact, "Show الفئة_30.")


def test_numeric_column_names_are_not_removed_as_identifiers():
    artifact = numeric_artifact()
    artifact["columns"][1]["name"] = "30"
    assert not run.answer_numbers_match("The total is 30.", artifact, "Show the total.")


def semantic_contract():
    return {"unknown_codes": {"gender": ["F", "M"]},
            "forbidden_expansions": {"gender": {
                "F": ["female", "women", "إناث", "الإناث", "للإناث"],
                "M": ["male", "men", "ذكور", "الذكور", "للذكور"],
            }}}


def public_artifact():
    return {**numeric_artifact(), "artifact_id": "art_test", "chart": "bar",
            "png_url": "/renders/test/chart.png",
            "review": {"status": "reviewed", "review": {"verdict": "pass", "findings": []}},
            "spec": "vis bar\ntitle Percentage by code\nbind\n  category gender\n  value percentage"}


@pytest.mark.parametrize("reply", ["F is 49.5 and M is 50.5.",
                                    "F/M: no supplied mapping to female/male exists.",
                                    "I cannot infer whether F means female.",
                                    "احتفظت بالرمزين F وM دون افتراض أنهما إناث وذكور."])
def test_unknown_codes_and_explicit_nonassertion_are_allowed(reply):
    assert run.semantic_fidelity(reply, public_artifact(), semantic_contract()) == (True, [])


@pytest.mark.parametrize("reply", ["F means female; M means male.", "Female (F): 49.5.",
                                    "أعلى نسبة للإناث (F): الجوف؛ أعلى نسبة للذكور (M): مكة.",
                                    "No mapping is provided; F means female.",
                                    "No issue exists: women (F) are the largest group.",
                                    "No mapping provided but F means female.",
                                    "No mapping provided and F means female.",
                                    "F means female without mapping."])
def test_known_expansion_regressions_fail_without_guessing_code_meanings(reply):
    passed, diagnostics = run.semantic_fidelity(reply, public_artifact(), semantic_contract())
    assert not passed
    assert any("Unsupported expansion" in reason for reason in diagnostics)


def test_relabelled_unknown_code_is_rejected_even_without_a_known_expansion_list():
    artifact = public_artifact()
    artifact["spec"] += '\nvalueLabels\n  - ["gender", "F", "Invented meaning"]'
    passed, diagnostics = run.semantic_fidelity("F: 49.5.", artifact, {"unknown_codes": {"gender": ["F"]}})
    assert not passed and "relabelled" in diagnostics[0]


@pytest.mark.parametrize("field", ["title", "subtitle", "description", "axisXTitle", "axisYTitle"])
def test_design_text_is_checked_alongside_final_prose(field):
    artifact = public_artifact()
    artifact["spec"] = f"vis table\n{field} Female samples"
    passed, diagnostics = run.semantic_fidelity("F: 49.5.", artifact, semantic_contract())
    assert not passed and any("design title/description" in reason for reason in diagnostics)


@pytest.mark.parametrize("brief", [
    {"code_meanings": {"gender": {"F": "female", "M": "male"}}},
    {"display_labels": {"ar": {"value_labels": {"gender": {"F": "إناث", "M": "ذكور"}}}}},
])
def test_authoritative_meanings_or_approved_labels_allow_translation(brief):
    artifact = public_artifact()
    artifact["spec"] += '\nvalueLabels\n  - ["gender", "F", "إناث"]\n  - ["gender", "M", "ذكور"]'
    assert run.semantic_fidelity("Female (F) and male (M).", artifact, semantic_contract(),
                                 DataBrief.model_validate(brief)) == (True, [])


def test_authorization_is_column_and_code_scoped():
    brief = {"code_meanings": {"status": {"F": "female"}, "gender": {"M": "male"}}}
    passed, diagnostics = run.semantic_fidelity("Female F and male M.", public_artifact(), semantic_contract(), brief)
    assert not passed
    assert len(diagnostics) == 1 and "gender.F" in diagnostics[0]


@pytest.mark.parametrize("mutation", ["reply", "spec", "columns", "rows"])
def test_required_semantics_fail_closed_when_evidence_is_missing(mutation):
    artifact = public_artifact()
    reply = "F: 49.5."
    if mutation == "reply":
        reply = None
    else:
        artifact.pop(mutation)
    passed, diagnostics = run.semantic_fidelity(reply, artifact, semantic_contract())
    assert not passed and diagnostics


@pytest.mark.parametrize("contract", [{}, {"unknown_codes": []}, {"unknown_codes": {"gender": "F"}},
                                        {"unknown_codes": {"gender": ["F"]},
                                         "forbidden_expansions": {"other": {"F": ["female"]}}}])
def test_invalid_semantic_contract_is_an_evaluation_error(contract):
    expected = {"tool": "none", "outcome": "text", "semantic_fidelity": contract}
    scored = run.safe_score_turn(expected, [], "Done.")
    assert scored["outcome_ok"] is False
    assert "ValueError" in scored["evaluation_error"]


def messages(name, content):
    return [ModelResponse(parts=[ToolCallPart(name, {}, tool_call_id=name)]),
            ModelRequest(parts=[ToolReturnPart(name, content, tool_call_id=name)])]


def e2e_turn():
    expected = {"message": "Show count_under_30 by gender.", "tool": "draw", "outcome": "artifact",
                "prepared_csv": True, "strict_source": True, "require_delivery": True,
                "require_render_evidence": True, "review_required": True, "review_pass_required": True,
                "max_seconds": 60, "semantic_fidelity": semantic_contract()}
    artifact = public_artifact()
    captured = []
    for name in ("draw", "design_visualization", "render_visualization", "review_visualization"):
        captured += messages(name, {"request_id": "rq_test"})
    captured += messages("publish_visualization", {"request_id": "rq_test", "artifact": artifact})
    reply = "F: 49.5; M: 50.5. ![Chart](/renders/test/chart.png)"
    turn = {**run.score_turn(expected, captured, reply), "expected": expected, "reply": reply,
            "source_fidelity_ok": True, "latency_ok": True, "seconds": 5,
            "artifact_source_signature": run.source_signature([column["name"] for column in artifact["columns"]],
                                                               artifact["rows"]),
            "render_evidence_ok": True,
            "render_evidence": {"sha256": "a" * 64, "bytes": 100, "width": 300, "height": 200,
                                "url": artifact["png_url"]}}
    assert run.turn_passes(turn), run.turn_diagnostics(turn)
    return turn


@pytest.mark.parametrize("gate", ["source_fidelity_ok", "delivery_ok", "render_evidence_ok", "review_ok",
                                   "reply_ok", "latency_ok", "semantic_fidelity_ok", "answer_fidelity_ok"])
@pytest.mark.parametrize("state", [None, False, "missing"])
def test_required_gates_cannot_be_omitted_or_set_null_to_pass(gate, state):
    turn = e2e_turn()
    if gate == "reply_ok":
        turn["expected"]["reply_patterns"] = ["F"]
    if state == "missing":
        turn.pop(gate, None)
    else:
        turn[gate] = state
    assert not run.turn_passes(turn)
    assert any(reason.startswith(gate + ":") for reason in run.turn_diagnostics(turn))


@pytest.mark.parametrize("field", ["artifact_source_signature", "render_evidence", "semantic_diagnostics", "reply", "seconds"])
def test_success_flags_without_required_underlying_evidence_do_not_pass(field):
    turn = e2e_turn()
    turn.pop(field)
    assert not run.turn_passes(turn)


@pytest.mark.parametrize("field,value", [("tool_return", "Malformed publication"),
                                          ("render_evidence", "Not evidence"),
                                          ("artifact_source_signature", "Not a signature")])
def test_malformed_evidence_produces_feedback_instead_of_crashing(field, value):
    turn = e2e_turn()
    turn[field] = value
    assert not run.turn_passes(turn)


@pytest.mark.parametrize("field,value", [("error", "Timed out"), ("evaluation_error", "Incomplete evidence"),
                                          ("seconds", 61), ("seconds", float("nan")), ("seconds", -1)])
def test_errors_or_invalid_latency_cannot_be_hidden_by_true_gates(field, value):
    turn = e2e_turn()
    turn[field] = value
    assert not run.turn_passes(turn)


def test_missing_expectations_are_not_success_and_latency_exclusion_is_explicit():
    turn = e2e_turn()
    turn["seconds"] = 61
    turn["latency_ok"] = False
    assert run.turn_passes(turn, include_latency=False)
    assert not run.turn_passes(turn, expected={})
    assert not run.turn_passes({"tool_ok": True, "outcome_ok": True, "reply": "Done."})


def test_review_and_delivery_evidence_must_match_positive_scores():
    turn = e2e_turn()
    turn["tool_return"]["artifact"]["review"]["review"]["verdict"] = "revise"
    assert not run.turn_passes(turn)
    turn = e2e_turn()
    turn["render_evidence"]["url"] = "/renders/stale/chart.png"
    assert not run.turn_passes(turn)
    turn = e2e_turn()
    turn["reply"] = "I will publish it next."
    assert not run.turn_passes(turn)


def test_semantic_check_is_opt_in_not_a_universal_translation_ban():
    artifact = public_artifact()
    expected = {"tool": "draw", "outcome": "artifact"}
    scored = run.score_turn(expected, messages("draw", {"artifact": artifact}), "Female F.")
    assert scored["semantic_fidelity_ok"] is None and scored["semantic_diagnostics"] == []


def test_run_case_passes_the_authoritative_brief_to_the_semantic_scorer():
    artifact = public_artifact()
    lead = Agent("test")

    @lead.tool_plain
    def draw() -> dict:
        return {"artifact": deepcopy(artifact)}

    def respond(history, info):
        return ModelResponse(parts=[TextPart("Female F, male M.")]) if any(
            isinstance(part, ToolReturnPart) for message in history for part in message.parts
        ) else ModelResponse(parts=[ToolCallPart("draw", {})])

    expected = {"message": "Show the codes.", "tool": "draw", "outcome": "artifact",
                "semantic_fidelity": semantic_contract()}
    case = {"name": "brief-semantics", "filename": "tiny.csv", "csv_text": "gender,value\nF,5\nM,7\n",
            "brief": {"code_meanings": {"gender": {"F": "female", "M": "male"}}}, "turns": [expected]}
    with lead.override(model=FunctionModel(respond)):
        record = asyncio.run(run.run_case(case, lead, None, None, None))
    assert record["turns"][0]["semantic_fidelity_ok"] is True
    assert record["turns"][0]["semantic_diagnostics"] == []
