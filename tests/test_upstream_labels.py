"""Approved labels survive the upstream handoff while source keys and values remain unchanged."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from starlette.applications import Starlette
from starlette.testclient import TestClient

from evals.lead.run import load_cases, run_case, score_turn
from vis_agent.analyst.models import ResultColumn
from vis_agent.analyst.source import load_csv_report
from vis_agent.labels import display_value, project_display_labels
from vis_agent.models import DataBrief, DisplayLabels
from vis_agent.uploads import add_upload_routes

CASES = load_cases(Path(__file__).resolve().parents[1] / "evals/lead/prepared/label-cases.json")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_approved_labels_round_trip_through_upload_without_rewriting_csv(store, case):
    app = Starlette()
    add_upload_routes(app, store)
    raw = case["csv_text"].encode("utf-8")
    brief = DataBrief.model_validate(case["brief"])
    with TestClient(app) as client:
        response = client.post("/datasets/upload", files={"file": (case["filename"], raw, "text/csv")},
                               data={"brief": brief.model_dump_json()})
    assert response.status_code == 201
    dataset_id = response.json()["dataset_id"]
    saved = store.get_upload(dataset_id)
    assert saved.brief == brief
    assert saved.brief.fingerprint() == brief.fingerprint()
    assert (store.uploads / f"{dataset_id}.csv").read_bytes() == raw
    report = load_csv_report(store, dataset_id, brief.raw_question, language="Arabic")
    expected = case["turns"][0]
    assert report.result.columns == expected["source_columns"]
    assert report.result.rows == expected["source_rows"]
    assert report.brief_fingerprint == brief.fingerprint()
    meanings, labels = project_display_labels(saved.brief, report.analysis.columns, "Arabic")
    assert meanings == brief.code_meanings
    assert labels.model_dump() == expected["display_labels"]


def test_empty_display_metadata_preserves_the_legacy_brief_fingerprint():
    brief = DataBrief(raw_question="Compare the supplied counts.", units={"count": "person"})
    # Fingerprint of this brief before the display_labels field was introduced.
    assert brief.fingerprint() == "1c9a29343d94799b"
    assert DataBrief.model_validate_json(brief.model_dump_json()).fingerprint() == brief.fingerprint()


def test_approved_label_changes_change_fingerprint_but_not_source_data(store):
    case = CASES[0]
    original = DataBrief.model_validate(case["brief"])
    uploaded = store.save_upload(case["filename"], case["csv_text"].encode(), original)
    before = load_csv_report(store, uploaded.dataset_id, original.raw_question, language="Arabic")
    changed = original.model_dump(mode="json")
    changed["display_labels"]["ar"]["value_labels"]["gender"]["M"] = "ذكور"
    replacement = DataBrief.model_validate(changed)
    store.update_brief(uploaded.dataset_id, replacement)
    after = load_csv_report(store, uploaded.dataset_id, replacement.raw_question, language="Arabic")
    assert replacement.fingerprint() != original.fingerprint()
    assert before.brief_fingerprint != after.brief_fingerprint
    assert before.result.columns == after.result.columns
    assert before.result.rows == after.result.rows == [["M", 42], ["F", 58]]
    assert store.get_upload(uploaded.dataset_id).sha256 == uploaded.sha256
    assert (store.uploads / f"{uploaded.dataset_id}.csv").read_text() == case["csv_text"]


def test_code_meaning_and_display_labels_project_by_source_column_and_alias():
    brief = DataBrief(
        code_meanings={"gender": {"M": "Male"}, "marital_status": {"M": "Married"}},
        display_labels={"ar": DisplayLabels(
            column_labels={"gender": "الجنس", "marital_status": "الحالة الاجتماعية"},
            value_labels={"gender": {"M": "ذكر"}, "marital_status": {"M": "متزوج"}},
        )},
    )
    columns = [ResultColumn(name="sex", meaning="Gender", kind="category", source="gender"),
               ResultColumn(name="civil", meaning="Marital status", kind="category", source="marital_status")]
    meanings, labels = project_display_labels(brief, columns, "ar")
    assert meanings == {"sex": {"M": "Male"}, "civil": {"M": "Married"}}
    assert labels.column_labels == {"sex": "الجنس", "civil": "الحالة الاجتماعية"}
    assert display_value(labels, "sex", "M") == "ذكر"
    assert display_value(labels, "civil", "M") == "متزوج"
    assert display_value(labels, "unrelated", "M") == "M"
    assert display_value(labels, "sex", "m") == "m"
    assert display_value(labels, "sex", None) is None
    assert brief.display_labels["ar"].value_labels == {"gender": {"M": "ذكر"}, "marital_status": {"M": "متزوج"}}


def test_computed_measures_do_not_inherit_category_translations():
    brief = DataBrief.model_validate(CASES[0]["brief"])
    columns = [ResultColumn(name="distinct_genders", meaning="Distinct gender count", kind="measure",
                            source="gender", aggregate="count_distinct")]
    meanings, labels = project_display_labels(brief, columns, "ar")
    assert meanings == {}
    assert labels == DisplayLabels()


def test_missing_translation_does_not_trigger_an_automatic_code_dictionary():
    brief = DataBrief(code_meanings={"marital_status": {"M": "Married"}})
    columns = [ResultColumn(name="marital_status", meaning="Marital status", kind="category")]
    meanings, labels = project_display_labels(brief, columns, "ar")
    assert meanings == {"marital_status": {"M": "Married"}}
    assert labels == DisplayLabels()
    assert display_value(labels, "marital_status", "M") == "M"


def test_malformed_display_metadata_is_rejected_at_the_upload_boundary(store):
    app = Starlette()
    add_upload_routes(app, store)
    with TestClient(app) as client:
        response = client.post("/datasets/upload", files={"file": ("codes.csv", b"code,count\nM,2\n", "text/csv")},
                               data={"brief": json.dumps({"display_labels": {"ar": {"translation": {"M": "Male"}}}})})
    assert response.status_code == 400
    assert "brief" in response.json()["error"]
    assert store.list_datasets() == []


@pytest.mark.parametrize("language", ["Arabic", "ar-SA", "fr"])
def test_unsupported_display_language_is_rejected_at_the_upload_boundary(store, language):
    app = Starlette()
    add_upload_routes(app, store)
    brief = {"display_labels": {language: {"value_labels": {"gender": {"M": "ذكر"}}}}}
    with TestClient(app) as client:
        response = client.post("/datasets/upload", files={"file": ("codes.csv", b"gender,count\nM,2\n", "text/csv")},
                               data={"brief": json.dumps(brief)})
    assert response.status_code == 400
    assert "brief" in response.json()["error"]
    assert store.list_datasets() == []


@pytest.mark.parametrize("label", ["", " ", "\n\t"])
@pytest.mark.parametrize("mapping", ["column_labels", "value_labels"])
def test_blank_approved_labels_are_rejected_at_the_upload_boundary(store, mapping, label):
    app = Starlette()
    add_upload_routes(app, store)
    labels = {mapping: {"gender": label if mapping == "column_labels" else {"M": label}}}
    with TestClient(app) as client:
        response = client.post("/datasets/upload", files={"file": ("codes.csv", b"gender,count\nM,2\n", "text/csv")},
                               data={"brief": json.dumps({"display_labels": {"ar": labels}})})
    assert response.status_code == 400
    assert "brief" in response.json()["error"]
    assert store.list_datasets() == []


def test_inline_synthetic_cases_run_without_a_csv_file_or_models():
    lead = Agent("test")

    def respond(messages, info):
        return ModelResponse(parts=[TextPart("Fixture loaded.")])

    case = {**CASES[0], "turns": [{"message": "Inspect this fixture.", "tool": "none", "outcome": "text"}]}
    with lead.override(model=FunctionModel(respond)):
        record = asyncio.run(run_case(case, lead, None, None, None))
    assert "error" not in record
    assert record["csv"] == case["filename"]
    assert record["turns"][0]["outcome_ok"]


def test_label_evaluation_rejects_wrong_semantics_even_when_raw_rows_are_correct():
    expected = CASES[1]["turns"][0]
    artifact = {
        "artifact_id": "art_fixture", "chart": "bar",
        "columns": [{"name": "marital_status"}, {"name": "count"}],
        "rows": [["M", 35], ["S", 65]],
        "spec": 'vis bar\ncolumnLabels\n  - ["marital_status", "الحالة الاجتماعية"]\n'
                '  - ["count", "عدد الأشخاص"]\nvalueLabels\n'
                '  - ["marital_status", "M", "متزوج"]\n  - ["marital_status", "S", "أعزب"]',
    }
    messages = [ModelResponse(parts=[ToolCallPart("draw", {}, tool_call_id="start")]),
                ModelRequest(parts=[ToolReturnPart("draw", {"request_id": "rq_fixture"}, tool_call_id="start")]),
                ModelResponse(parts=[ToolCallPart("publish_visualization", {}, tool_call_id="publish")]),
                ModelRequest(parts=[ToolReturnPart("publish_visualization", {"artifact": artifact}, tool_call_id="publish")])]
    scored = score_turn(expected, messages)
    assert scored["source_fidelity_ok"] and scored["labels_ok"]
    artifact["spec"] = artifact["spec"].replace('"متزوج"', '"ذكر"')
    wrong = score_turn(expected, messages)
    assert wrong["source_fidelity_ok"] and wrong["labels_ok"] is False


def test_label_evaluation_rejects_rewritten_source_values():
    expected = CASES[2]["turns"][0]
    artifact = {"rows": [["سعودي", 70], ["غير سعودي", 30]],
                "columns": [{"name": "nationality"}, {"name": "count"}]}
    messages = [ModelResponse(parts=[ToolCallPart("draw", {}, tool_call_id="start")]),
                ModelRequest(parts=[ToolReturnPart("draw", {"artifact": artifact}, tool_call_id="start")])]
    assert score_turn(expected, messages)["source_fidelity_ok"] is False
