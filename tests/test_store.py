from pathlib import Path

import pytest

from vis_agent.store import DatasetNotFound, DatasetStore
from vis_agent.models import DataBrief

SALES = b"id,region,date,amount\n001,East,2026-01-01,10\n002,West,2026-01-02,20\n"


def test_database_path_can_be_chosen(tmp_path):
    chosen = tmp_path / "elsewhere" / "local.duckdb"
    chosen.parent.mkdir()
    store = DatasetStore(tmp_path, database=chosen)
    assert store.database == chosen.resolve()
    assert chosen.exists()
    assert not (tmp_path / "datasets.duckdb").exists()


def test_default_database_lives_in_the_data_directory(tmp_path):
    store = DatasetStore(tmp_path)
    assert store.database == (tmp_path / "datasets.duckdb").resolve()


def test_brief_is_saved_with_the_upload_and_can_change(store):
    brief = DataBrief(raw_question="Sales by region", units={"amount": "USD"})
    dataset = store.save_upload("sales.csv", SALES, brief)
    assert store.get_upload(dataset.dataset_id).brief == brief
    changed = store.update_brief(dataset.dataset_id, DataBrief(raw_question="Sales by region", units={"amount": "SAR"}))
    assert changed.brief.units == {"amount": "SAR"}
    assert store.get_upload(dataset.dataset_id).brief.units == {"amount": "SAR"}
    assert store.update_brief(dataset.dataset_id, None).brief is None


def test_unknown_and_malformed_ids_are_different_errors(store):
    with pytest.raises(DatasetNotFound, match="not found"):
        store.get_upload("ds_" + "0" * 32)
    with pytest.raises(ValueError, match="Invalid file ID") as excinfo:
        store.get_upload("../../.env")
    assert not isinstance(excinfo.value, DatasetNotFound)


def test_list_datasets_newest_first_with_profile_status(store):
    first = store.save_upload("first.csv", SALES)
    second = store.save_upload("second.csv", SALES, DataBrief(raw_question="q"))
    summaries = store.list_datasets()
    assert [s.dataset_id for s in summaries] == [second.dataset_id, first.dataset_id]
    assert [s.has_brief for s in summaries] == [True, False]
    assert {s.profile_status for s in summaries} == {"none"}
    assert summaries[0].row_count is None


def test_failed_checks_across_saved_profiles(store):
    from datetime import datetime, timezone

    from vis_agent.profiler.measurements import compute_statistics
    from vis_agent.profiler.models import DatasetProfile, ProfileCheck

    source = store.save_upload("sales.csv", b"region,amount\nEast,1\n")
    store.import_csv(source.dataset_id)
    review = [ProfileCheck(column="region", check="measure_is_numeric", severity="error", passed=False, message="bad"),
              ProfileCheck(column="amount", check="unit_only_on_measures", severity="error", passed=True, message="ok")]
    store.save_profile(DatasetProfile(source=source, status="complete", deterministic=compute_statistics(store, source),
                                      review=review, created_at=datetime.now(timezone.utc)))
    assert store.failed_checks() == [(source.dataset_id, "measure_is_numeric", "error", "bad")]
