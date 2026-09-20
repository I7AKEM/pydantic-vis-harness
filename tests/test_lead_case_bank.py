"""Offline dataset integrity: no model or network access is required."""

from copy import deepcopy
import hashlib
import json
import shutil

import pytest

from evals.lead import case_bank as cb


@pytest.fixture
def bank():
    return cb.load_bank()


@pytest.fixture
def bank_directory(tmp_path):
    path = tmp_path / "bank"
    path.mkdir()
    for name in ("cases.json", "manifest.json", "findings.json"):
        shutil.copyfile(cb.BANK / name, path / name)
    return path


def edit_json(directory, name, edit):
    path = directory / name
    value = json.loads(path.read_text())
    edit(value)
    path.write_text(json.dumps(value, ensure_ascii=False))


def test_fifty_inputs_are_not_fifty_executed_cases(bank):
    assert cb.summary(bank) == {
        "cases": 50, "cases_with_saved_runs": 20, "cases_without_saved_runs": 30,
        "saved_runs": 40, "splits": {"train": 35, "validation": 15, "heldout": 0},
        "dispositions": {"chart": 48, "unsupported": 1, "table_fallback": 1},
        "documented_findings": 10, "regression_cases": 12,
        "gold_model_outputs": 0, "model_calls": 0,
    }
    for source in bank["manifest"]["sources"].values():
        if source["segment"] == "initial20":
            assert {o["arm"] for o in source["observations"]} == {"glm", "claude"}
        else:
            assert source["observations"] == []


def test_original_frozen_study_segments_and_gates_are_unchanged(bank):
    assert cb.digest(bank["cases"][:20]) == "8541cb0af6a7f19a8acde058cef7f785e00f16799f45d0cee1492d6102eeb477"
    assert cb.digest(bank["cases"][20:]) == "eaa0510a99c6ba5cca3e76ee1b4dde58de766c558b982cfd0557fe1421f624f7"
    for case in bank["cases"]:
        turn = case["turns"][0]
        assert turn["max_seconds"] == 60
        if turn["disposition"] == "chart":
            assert turn["require_render_evidence"] and turn["require_delivery"]
        else:
            assert turn["no_image"] and not turn.get("require_render_evidence")


def test_split_is_source_grouped_and_reproducible(bank):
    manifest = bank["manifest"]
    groups = sorted({s["group_id"] for s in manifest["sources"].values()},
                    key=lambda group: hashlib.sha256(f"{manifest['split_seed']}:{group}".encode()).hexdigest())
    train = set(manifest["splits"]["train"])
    validation = set(manifest["splits"]["validation"])
    assert train.isdisjoint(validation)
    assert {manifest["sources"][name]["group_id"] for name in train} == set(groups[:35])
    assert {manifest["sources"][name]["group_id"] for name in validation} == set(groups[35:])


@pytest.mark.parametrize("key", ["group_id", "csv_sha256"])
def test_source_duplicates_cannot_cross_tuning_splits(bank_directory, key):
    def cross(manifest):
        train = manifest["splits"]["train"][0]
        validation = manifest["splits"]["validation"][0]
        manifest["sources"][validation][key] = manifest["sources"][train][key]
    edit_json(bank_directory, "manifest.json", cross)
    with pytest.raises(ValueError, match="source group crosses"):
        cb.load_bank(bank_directory)


def test_known_development_data_cannot_be_called_heldout(bank_directory):
    edit_json(bank_directory, "manifest.json",
              lambda m: m["splits"]["heldout"].append(m["splits"]["validation"][0]))
    with pytest.raises(ValueError, match="no independent held-out"):
        cb.load_bank(bank_directory)


def test_changed_acceptance_contract_is_detected(bank_directory):
    edit_json(bank_directory, "cases.json", lambda cases: cases[0]["turns"][0].update(max_seconds=9999))
    with pytest.raises(ValueError, match="frozen input hash"):
        cb.load_bank(bank_directory)
    # Merely updating the combined hash cannot bypass the segment-level freeze.
    changed = json.loads((bank_directory / "cases.json").read_text())
    edit_json(bank_directory, "manifest.json", lambda m: m.update(cases_sha256=cb.digest(changed)))
    with pytest.raises(ValueError, match="Frozen study segment changed"):
        cb.load_bank(bank_directory)


def test_unknown_finding_case_is_rejected(bank_directory):
    edit_json(bank_directory, "findings.json", lambda findings: findings[0]["case_names"].append("invented"))
    with pytest.raises(ValueError, match="unknown case"):
        cb.load_bank(bank_directory)


def test_regression_subset_retains_original_contracts(bank):
    selected = cb.select_cases(bank, "regression")
    originals = {case["name"]: case for case in bank["cases"]}
    assert len(selected) == 12
    assert all(case == originals[case["name"]] for case in selected)
    selected[0]["turns"][0]["message"] = "changed in caller"
    assert originals[selected[0]["name"]]["turns"][0]["message"] != "changed in caller"


def test_actual_dspy_examples_have_no_label_or_evidence_leak(monkeypatch, bank):
    import dspy

    def forbidden(*args, **kwargs):
        pytest.fail("Dataset loading must not construct or call a language model")

    monkeypatch.setattr(dspy, "LM", forbidden)
    monkeypatch.setattr(dspy.Predict, "forward", forbidden)
    monkeypatch.setattr(dspy, "configure", forbidden)
    train = cb.dspy_examples("train")
    validation = cb.dspy_examples("validation")
    assert len(train) == 35 and len(validation) == 15
    assert {e.case_id for e in train}.isdisjoint({e.case_id for e in validation})
    original = {case["name"]: case for case in bank["cases"]}
    for example in train + validation:
        assert isinstance(example, dspy.Example)
        assert set(example.inputs().keys()) == {"case_input"}
        assert set(example.case_input) == {"csv", "brief", "caller_kind", "caller_identity", "messages"}
        assert example.case_input["messages"] == [t["message"] for t in original[example.case_id]["turns"]]
        assert "message" not in example.expectations[0]
        assert "expectations" in example.labels() and "findings" in example.labels()
        assert not any(field in example for field in ("answer", "spec", "verdict", "design"))
        assert example.gold_output_status.startswith("not_provided")


@pytest.mark.parametrize("split", ["all", "regression", "heldout", "test"])
def test_optimizer_loader_never_silently_combines_or_relabels_splits(split):
    with pytest.raises(ValueError, match="train or validation only"):
        cb.dspy_examples(split)


def test_csv_content_drift_is_detected_without_reading_rest_of_corpus(bank_directory, tmp_path):
    changed_csv = tmp_path / "changed.csv"
    changed_csv.write_text("value\n999999\n")
    # Redirect only the read: the frozen case and manifest remain unchanged.
    bank = cb.load_bank(bank_directory)
    original_read_bytes = cb.Path.read_bytes
    first_path = cb.Path(bank["cases"][0]["csv"])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cb.Path, "read_bytes",
                      lambda path: original_read_bytes(changed_csv if path == first_path else path))
        with pytest.raises(ValueError, match="Source CSV changed"):
            cb.load_bank(bank_directory, verify_sources=True)


def test_evidence_association_is_checked_without_external_services(tmp_path):
    record = {"name": "case1", "source_csv_sha256": "abc", "assets": ["case1/chart.png"]}
    result = tmp_path / "run.json"
    result.write_text(json.dumps({"cases": [record]}))
    checkpoint = tmp_path / "run-assets/case1/case.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(json.dumps(record))
    image = checkpoint.with_name("chart.png")
    image.write_bytes(b"synthetic evidence fixture, not a real evaluated image")
    evidence = {"cases": [], "findings": [], "manifest": {
        "result_files": [{"path": "run.json", "arm": "glm", "case_count": 1,
                          "sha256": hashlib.sha256(result.read_bytes()).hexdigest()}],
        "sources": {"case1": {"csv_sha256": "abc", "observations": [{
            "result_file": "run.json", "arm": "glm", "checkpoint": "run-assets/case1/case.json",
            "images": ["run-assets/case1/chart.png"],
        }]}},
    }}
    cb.validate_evidence(evidence, tmp_path)
    wrong = deepcopy(evidence)
    wrong["manifest"]["sources"]["case1"]["observations"][0]["images"] = []
    with pytest.raises(ValueError, match="Image evidence"):
        cb.validate_evidence(wrong, tmp_path)
    checkpoint.write_text(json.dumps({**record, "name": "different-case"}))
    with pytest.raises(ValueError, match="Checkpoint belongs"):
        cb.validate_evidence(evidence, tmp_path)


def test_findings_preserve_uncertainty_and_scroll_scope(bank):
    assert all(f["status"] == "agent_audited" and not f["human_adjudication"] for f in bank["findings"])
    assert all(f["acceptance"] and f["evidence"] and f["optimization_use"] for f in bank["findings"])
    assert "functioning scrollable viewport" in bank["manifest"]["scroll_policy"]
    assert "static PNG" in bank["manifest"]["scroll_policy"]
