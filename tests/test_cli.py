import json

import pytest

import vis_agent.cli as cli
from vis_agent.models import DataBrief

SALES = b"id,region,date,amount\n001,East,2026-01-01,10\n"


def test_profile_subcommand_uploads_and_profiles(store, tmp_path, monkeypatch, capsys):
    csv_path = tmp_path / "sales.csv"
    csv_path.write_bytes(SALES)
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps({"raw_question": "Sales by region"}))
    seen = {}

    async def fake_profile_dataset(store_arg, profiler_arg, dataset_id, brief=None, usage=None):
        seen.update(dataset_id=dataset_id, brief=brief)
        return store_arg.get_upload(dataset_id)

    monkeypatch.setattr(cli, "profile_dataset", fake_profile_dataset)
    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, object(), object()))
    assert cli.main(["profile", "--upload", str(csv_path), "--brief", str(brief_path)]) == 0
    assert seen["brief"] is None
    assert store.get_upload(seen["dataset_id"]).brief == DataBrief(raw_question="Sales by region")
    printed = json.loads(capsys.readouterr().out)
    assert printed["dataset_id"] == seen["dataset_id"]
    assert printed["filename"] == "sales.csv"


def test_profile_subcommand_with_existing_id(store, monkeypatch, capsys):
    dataset = store.save_upload("sales.csv", SALES)

    async def fake_profile_dataset(store_arg, profiler_arg, dataset_id, brief=None, usage=None):
        return store_arg.get_upload(dataset_id)

    monkeypatch.setattr(cli, "profile_dataset", fake_profile_dataset)
    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, object(), object()))
    assert cli.main(["profile", dataset.dataset_id]) == 0
    assert json.loads(capsys.readouterr().out)["dataset_id"] == dataset.dataset_id


def test_profile_subcommand_needs_an_id_or_an_upload(capsys):
    with pytest.raises(SystemExit):
        cli.main(["profile"])


def test_ask_subcommand_prints_the_report(store, tmp_path, monkeypatch, capsys):
    from vis_agent import cli

    async def fake_analyze(store_arg, profiler_arg, analyst_arg, dataset_id, question, brief=None, usage=None):
        return {"dataset_id": dataset_id, "question": question, "brief": brief}

    csv_path = tmp_path / "sales.csv"
    csv_path.write_bytes(SALES)
    monkeypatch.setattr(cli, "analyze_dataset", fake_analyze)
    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, object(), object()))
    assert cli.main(["ask", "--upload", str(csv_path), "Total by region"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["question"] == "Total by region" and printed["dataset_id"].startswith("ds_")


def test_failures_subcommand_lists_failed_checks(store, monkeypatch, capsys):
    from vis_agent import cli

    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, object(), object()))
    monkeypatch.setattr(store, "failed_checks", lambda: [("ds_1", "measure_is_numeric", "error", "region: role is measure but the column has no numeric statistics."),
                                                          ("ds_2", "measure_is_numeric", "error", "x: role is measure but the column has no numeric statistics.")])
    assert cli.main(["failures"]) == 0
    out = capsys.readouterr().out
    assert "measure_is_numeric" in out and "2" in out and "ds_1" in out
