"""Offline tests of the frozen challenge and its independent evidence scorer."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from evals.generalization.bank import HERE, freeze, load_bank, make_bank, sha256
from evals.generalization.run import case_adapter, runtime_fingerprint
from evals.generalization.scoring import observations, score_case, score_pairs, summarize


def test_bank_is_frozen_and_all_families_are_held_out():
    bank, manifest = load_bank()
    assert len(bank["cases"]) == len({case["id"] for case in bank["cases"]}) == 24
    assert len(bank["families"]) == 6
    assert len(bank["pairs"]) == 18
    assert sha256(bank) == manifest["semantic_sha256"]
    assert bank == make_bank()
    assert not bank["provenance"]["human_gold"]
    assert all(case["provenance"]["synthetic"] and not case["provenance"]["tuning_allowed"] for case in bank["cases"])
    assert {case["split"] for case in bank["cases"]} == {"blinded_challenge"}
    for family in bank["families"]:
        members = [case for case in bank["cases"] if case["family"] == family["id"]]
        assert len(members) == 4
        assert len({case["goal"] for case in members}) == 2
        assert {case["variant"] for case in members} == {"original", "transformed"}


def test_meaning_preserving_pairs_are_not_new_numbers_in_old_templates():
    bank, _ = load_bank()
    cases = {case["id"]: case for case in bank["cases"]}
    for pair in bank["pairs"]:
        left, right = [cases[key] for key in pair["members"]]
        assert observations(left["source_columns"], left["source_rows"], left["canonical_columns"]) == observations(
            right["source_columns"], right["source_rows"], right["canonical_columns"])
        if pair["kind"] == "meaning_preserving":
            assert left["source_csv_sha256"] != right["source_csv_sha256"]
            assert left["goal"] == right["goal"]
            assert set(left["source_columns"]).isdisjoint(right["source_columns"])
        else:
            assert left["goal"] != right["goal"]
            assert left["request"] != right["request"]


def test_freeze_rejects_overwrite_and_tampering(tmp_path):
    freeze(tmp_path)
    with pytest.raises(FileExistsError):
        freeze(tmp_path)
    path = tmp_path / "bank.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_bank(tmp_path)


def test_adapter_never_sends_the_oracle_to_the_agent():
    bank, _ = load_bank()
    case = bank["cases"][0]
    adapted = case_adapter(case)
    assert adapted["caller_kind"] == "agent"
    assert adapted["turns"][0]["message"].endswith(f"[{case['filename']}](/datasets/{{dataset_id}}/profile)")
    assert "contract" not in adapted and "allowed_charts" not in adapted
    assert adapted["csv_text"] == case["csv_text"]
    assert adapted["brief"] == case["brief"]


def _evidence(case, root, *, source_rows=None, spec=None):
    contract = case["contract"]
    if spec is None:
        spec = "vis scatter\nbind\n" + "\n".join(f"  {role} {column}" for role, column in contract["required_bindings"].items())
    directory = root / case["id"] / "renders" / "a123"
    directory.mkdir(parents=True)
    # Header-only test fixture: scorer promises a valid header, not decoded image
    # correctness. A real render requires independent image review later.
    directory.joinpath("chart.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + (400).to_bytes(4, "big") + (300).to_bytes(4, "big"))
    directory.joinpath("config.json").write_text("{}")
    return {"artifacts": [{"artifact_id": "art_test", "png_url": "/renders/a123/chart.png", "design": {"spec": spec},
                            "report": {"result": {"columns": case["source_columns"], "rows": source_rows or case["source_rows"]},
                                       "analysis": {"columns": [{"name": column, "unit": contract["units"].get(column)} for column in case["source_columns"]]}},
                            "review": {"status": "reviewed", "review": {"verdict": "pass"}}}],
            "turns": [{"artifact_id": "art_test", "reply": "![Chart](/renders/a123/chart.png)", "seconds": 5.0,
                       "usage": {"requests": 6, "tool_calls": 5}, "messages": []}]}


def test_positive_contract_does_not_claim_visual_quality(tmp_path):
    case = load_bank()[0]["cases"][0]
    score = score_case(case, _evidence(case, tmp_path), tmp_path)
    assert score["deterministic_contract_pass"]
    assert not score["visual_quality_verified"] and not score["human_gold"]
    assert not score["provider_attempt_count_complete"]
    assert score["render_assets"][0]["width"] == 400


def test_online_reviewer_pass_does_not_hide_fidelity_failure(tmp_path):
    case = load_bank()[0]["cases"][0]
    rows = copy.deepcopy(case["source_rows"])
    rows[0][1] = 999
    score = score_case(case, _evidence(case, tmp_path, source_rows=rows), tmp_path)
    assert not score["checks"]["source_fidelity"]
    assert not score["deterministic_contract_pass"]
    assert score["online_reviewer"]["review"]["verdict"] == "pass"


def test_published_artifact_is_not_credited_as_delivered_without_link(tmp_path):
    case = load_bank()[0]["cases"][0]
    record = _evidence(case, tmp_path)
    record["turns"][0]["reply"] = "Done, I published it."
    score = score_case(case, record, tmp_path)
    assert score["checks"]["artifact_persisted"] and score["checks"]["render_file"]
    assert not score["checks"]["delivered_link"]


def test_timeout_is_retained_even_after_publishing(tmp_path):
    bank, _ = load_bank()
    case = bank["cases"][0]
    record = _evidence(case, tmp_path)
    record["turns"][0].update(error="TimeoutError: exceeded 120s", seconds=120.01, reply=None)
    score = score_case(case, record, tmp_path)
    summary = summarize(bank, [score])
    assert score["timed_out"] and not score["deterministic_contract_pass"]
    assert summary["timeouts"] == 1 and summary["attempts"] == 1 and summary["latency_censored"]
    assert summary["p95_seconds"] == 120.01


def test_pair_checks_meaning_not_pixels_or_chart_identity(tmp_path):
    bank, _ = load_bank()
    left, right = bank["cases"][:2]
    scores = [score_case(case, _evidence(case, tmp_path), tmp_path) for case in (left, right)]
    pair = score_pairs(bank, scores)[0]
    assert pair["metamorphic_contract_pass"]
    assert not pair["chart_equality_required"] and not pair["pixel_equality_required"]
    assert not pair["visual_quality_verified"]


def test_leading_zero_id_is_not_equivalent_to_numeric_cell():
    assert observations(["id"], [["0017"]]) != observations(["id"], [[17]])
    assert observations(["measure"], [[2]]) == observations(["measure"], [[2.0]])


def test_runtime_fingerprint_tracks_selected_package_and_ignores_dependencies(tmp_path):
    package = tmp_path / "vis_agent"
    package.mkdir()
    package.joinpath("__init__.py").write_text("")
    package.joinpath("rules.md").write_text("a")
    dependency = package / "render" / "node_modules"
    dependency.mkdir(parents=True)
    dependency.joinpath("large.js").write_text("dependency")
    before = runtime_fingerprint(package)
    dependency.joinpath("large.js").write_text("changed dependency")
    assert runtime_fingerprint(package) == before
    package.joinpath("rules.md").write_text("b")
    assert runtime_fingerprint(package)["sha256"] != before["sha256"]


def test_dry_run_requires_no_provider_calls_or_credentials():
    result = subprocess.run([sys.executable, "-m", "evals.generalization.run"], capture_output=True, text=True,
                            cwd=HERE.parents[1], timeout=30)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["dry_run"] and output["provider_calls"] == 0
    assert output["maximum_model_requests_per_arm"] == 432
    assert output["maximum_paired_model_requests"] == 864
