import json

from evals.profiler.make_cases import write_cases
from measurements import compute_statistics
from profile_models import ColumnSemantics, DataBrief, SemanticProfile
from profile_review import failed_checks, run_checks


def test_generated_cases_match_their_deterministic_expectations(store, tmp_path):
    expected = write_cases(tmp_path)
    assert len(expected) >= 12
    for name, case in expected.items():
        csv_path = tmp_path / f"{name}.csv"
        brief_path = tmp_path / f"{name}.brief.json"
        brief = DataBrief.model_validate_json(brief_path.read_text()) if brief_path.exists() else None
        source = store.save_upload(csv_path.name, csv_path.read_bytes(), brief)
        store.import_csv(source.dataset_id)
        statistics = compute_statistics(store, source)
        levels = {c.name: c.measurement_levels for c in statistics.columns}
        for column, wanted in case["levels"].items():
            assert set(wanted) <= set(levels[column]), (name, column, levels[column])
        semantic = SemanticProfile(description="stub", row_meaning=None, columns=[
            ColumnSemantics(name=c, meaning=None, role=r, unit=None, confidence="low", evidence="stub")
            for c, r in case["roles"].items()
        ])
        found = sorted(c.check for c in failed_checks(run_checks(statistics, semantic, brief)))
        assert found == sorted(case["failed_checks"]), (name, found)
        assert isinstance(case["units"], dict)
    assert expected["sales"]["units"] == {"amount": "USD"}
    assert json.loads((tmp_path / "expected.json").read_text()) == expected


def test_runner_builds_its_dataset_without_a_model():
    from evals.profiler.run import build_dataset

    dataset = build_dataset()
    assert dataset.name == "profiler-phase-1"
    assert len(dataset.cases) == 12
    assert len(dataset.evaluators) == 3
    assert {case.name for case in dataset.cases} >= {"sales", "conflict_units", "conflict_codes", "arabic"}
