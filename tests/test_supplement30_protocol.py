"""The expanded study's inputs are fixed before external model calls."""

import hashlib
import json
from pathlib import Path

from evals.lead.prepare_supplement30 import PERSONAL_COLUMN
from vis_agent.models import DataBrief
from vis_agent.profiler.measurements import GEOMETRY_NAME

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "evals/lead"
CASES = json.loads((EVAL / "supplement30-v3-cases.json").read_text())
MANIFEST = json.loads((EVAL / "supplement30-v3-manifest.json").read_text())


def test_supplement_is_thirty_distinct_inputs_outside_original_twenty():
    initial = {"corpus-" + entry["id"] for entry in json.loads((EVAL / "dev20-expectations.json").read_text())
               if entry["id"] != "vizcsv-839d109a0db9ce25"}
    initial.add("corpus-" + json.loads((EVAL / "dev20-additional.json").read_text())["id"])
    names = {case["name"] for case in CASES}
    assert len(CASES) == len(names) == 30
    assert len(initial) == 20 and not initial.intersection(names)
    assert len(initial | names) == MANIFEST["combined_count"] == 50


def test_supplement_manifest_freezes_exact_case_payloads():
    digest = hashlib.sha256(json.dumps(CASES, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert digest == MANIFEST["cases_sha256"]
    assert [case["name"] for case in CASES] == ["corpus-" + source["id"] for source in MANIFEST["sources"]]
    assert all(len(source["csv_sha256"]) == 64 for source in MANIFEST["sources"])


def test_boundary_tests_are_not_credited_as_verified_charts():
    charts = [case for case in CASES if case["turns"][0]["disposition"] == "chart"]
    boundaries = [case for case in CASES if case not in charts]
    assert len(charts) == MANIFEST["rendered_presentations"] == 28
    assert len(boundaries) == MANIFEST["technical_boundaries"] == 2
    for case in charts:
        expected = case["turns"][0]
        assert expected["strict_source"] and expected["require_delivery"] and expected["require_render_evidence"]
        assert expected["review_pass_required"] and expected["visible_columns"]
    for case in boundaries:
        expected = case["turns"][0]
        assert expected["no_image"] and not expected.get("require_render_evidence")
        assert expected["outcome"] in {"handled", "fallback"}
    fallback = next(case for case in boundaries if case["turns"][0]["outcome"] == "fallback")
    assert fallback["turns"][0]["strict_source"]


def test_supplement_has_diverse_stressors_not_only_single_value_cards():
    features = [source["features"] for source in MANIFEST["sources"]]
    for stress in ("temporal", "nulls", "negatives", "long_text"):
        assert any(feature[stress] for feature in features)
    assert {"1", "2-10", "11-50", "51-200", "201-1000", "1001+"} <= {feature["rows_bucket"] for feature in features}
    assert sum(feature["rows"] == 1 for feature in features) < 10


def test_input_briefs_validate_and_do_not_require_geometry_or_identifiers():
    for case, source in zip(CASES, MANIFEST["sources"]):
        brief = DataBrief.model_validate(case["brief"])
        assert set(brief.units) <= set(source["columns"])
        assert all(not PERSONAL_COLUMN.search(column) for column in source["columns"])
        assert all(not GEOMETRY_NAME.search(column) for column in case["turns"][0].get("visible_columns", []))
        assert case["caller_kind"] == "agent"
        assert case["turns"][0]["max_seconds"] == 60
