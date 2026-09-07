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
    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, object()))
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
    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, object()))
    assert cli.main(["profile", dataset.dataset_id]) == 0
    assert json.loads(capsys.readouterr().out)["dataset_id"] == dataset.dataset_id


def test_profile_subcommand_needs_an_id_or_an_upload(capsys):
    with pytest.raises(SystemExit):
        cli.main(["profile"])
