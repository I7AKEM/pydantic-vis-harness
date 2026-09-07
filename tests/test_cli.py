import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

import vis_agent.cli as cli
from tests.designer.conftest import gender_share
from vis_agent.analyst.models import Analysis, AnalysisReport, Clarification
from vis_agent.models import DataBrief
from vis_agent.render import gptvis
from vis_agent.render.base import RenderFailed, RendererUnavailable

SALES = b"id,region,date,amount\n001,East,2026-01-01,10\n"
DONUT = "vis donut\ntitle Gender share\ndescription Share by gender\nbind\n  category label\n  value share\nsort value desc\n"


@pytest.fixture
def report_path(tmp_path):
    columns, result = gender_share()
    report = AnalysisReport(dataset_id="ds_1", question="Share by gender?", language="en",
                            analysis=Analysis(sql="x", columns=columns, summary="s"), result=result,
                            seconds=0, created_at=datetime(2026, 9, 7, tzinfo=timezone.utc))
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    return path


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


def test_recommend_subcommand_prints_candidates(report_path, capsys):
    assert cli.main(["recommend", str(report_path), "--intent", "share", "--suggested", "donut"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["candidates"][0]["name"] == "donut"
    assert {score["rule"] for score in printed["candidates"][0]["breakdown"]} >= {"S1", "S2"}


@pytest.mark.parametrize("with_report", [False, True])
def test_check_subcommand_prints_syntax_violations(report_path, tmp_path, capsys, with_report):
    spec = tmp_path / "bad.vis"
    spec.write_text("vis donut\nnotAKey value\n")
    args = ["check", str(spec), "--renderer", "gptvis"]
    if with_report:
        args += ["--report", str(report_path)]
    assert cli.main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert not printed["ok"]
    assert printed["violations"][0]["rule"] == "syntax"
    assert printed["violations"][0]["line"] == 2
    assert ("note" in printed) is not with_report


def test_check_subcommand_skips_rules_without_report(report_path, tmp_path, capsys):
    spec = tmp_path / "bad.vis"
    spec.write_text("vis donut\n")
    assert cli.main(["check", str(spec)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["ok"] and not printed["violations"] and not printed["compromises"]
    assert "skip" in printed["note"].lower() and printed["canonical"].startswith("vis donut")
    assert cli.main(["check", str(spec), "--report", str(report_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert not printed["ok"] and {v["rule"] for v in printed["violations"]} >= {"C2", "C8"}


def test_check_subcommand_prints_compromises(report_path, tmp_path, capsys):
    spec = tmp_path / "donut.vis"
    spec.write_text(DONUT + "language ar\n")
    assert cli.main(["check", str(spec), "--report", str(report_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["ok"] and printed["canonical"]
    assert "direction" in {c["key"] for c in printed["compromises"]}


def test_render_subcommand_refuses_failing_spec(report_path, tmp_path, monkeypatch, capsys):
    spec = tmp_path / "bad.vis"
    spec.write_text("vis donut\n")

    def unexpected_render(*args, **kwargs):
        pytest.fail("A failing spec must not reach the renderer")

    monkeypatch.setattr(gptvis, "render", unexpected_render)
    out = tmp_path / "rendered"
    assert cli.main(["render", str(spec), "--report", str(report_path), "--out", str(out)]) == 2
    printed = json.loads(capsys.readouterr().out)
    assert not printed["ok"] and printed["violations"]
    assert not out.exists()


@pytest.mark.skipif(gptvis.available() is not None, reason=gptvis.available() or "")
@pytest.mark.parametrize("explicit_out", [False, True])
def test_render_subcommand_writes_files(report_path, store, tmp_path, monkeypatch, capsys, explicit_out):
    spec = tmp_path / "donut.vis"
    spec.write_text(DONUT, encoding="utf-8")
    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, None, None))
    args = ["render", str(spec), "--report", str(report_path), "--renderer", "gptvis"]
    if explicit_out:
        out = tmp_path / "rendered"
        args += ["--out", str(out)]
    else:
        digest = sha256(DONUT.encode("utf-8") + report_path.read_bytes()).hexdigest()[:12]
        out = store.directory / "renders" / digest
    assert cli.main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    for key, filename in [("png", "chart.png"), ("html", "chart.html"), ("config", "config.json")]:
        assert Path(printed[key]) == out / filename and Path(printed[key]).is_file()
    assert Path(printed["png"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert (printed["width"], printed["height"]) == (2400, 1350)
    assert printed["seconds"] > 0 and isinstance(printed["compromises"], list)


@pytest.mark.parametrize("command", ["recommend", "check", "render"])
@pytest.mark.parametrize("missing", ["analysis", "result"])
def test_chart_commands_reject_incomplete_reports(report_path, tmp_path, capsys, command, missing):
    report = AnalysisReport.model_validate_json(report_path.read_bytes())
    setattr(report, missing, None)
    if missing == "analysis":
        report.clarification = Clarification(question="Which population?", reason="Ambiguous population")
    report_path.write_text(report.model_dump_json())
    spec = tmp_path / "donut.vis"
    spec.write_text(DONUT)
    args = ["recommend", str(report_path)] if command == "recommend" else [command, str(spec), "--report", str(report_path)]
    assert cli.main(args) == 2
    assert "error" in json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("error", [RendererUnavailable("install the renderer"), RenderFailed("render timed out")])
def test_render_subcommand_reports_runtime_failure(report_path, tmp_path, monkeypatch, capsys, error):
    spec = tmp_path / "donut.vis"
    spec.write_text(DONUT)

    def fail_render(*args, **kwargs):
        raise error

    monkeypatch.setattr(gptvis, "render", fail_render)
    assert cli.main(["render", str(spec), "--report", str(report_path), "--out", str(tmp_path / "rendered")]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == str(error)


def test_doctor_subcommand_runs(capsys):
    status = cli.main(["doctor"])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("Node:") and lines[1].startswith("available:") and lines[2].startswith("smoke_test:")
    if gptvis.available() is None:
        assert status == 0


@pytest.mark.parametrize("unavailable,smoke", [("missing package", "renderer unavailable"), (None, "fonts: Arabic text did not render")])
def test_doctor_subcommand_reports_failure(monkeypatch, capsys, unavailable, smoke):
    monkeypatch.setattr(gptvis, "available", lambda: unavailable)
    monkeypatch.setattr(gptvis, "smoke_test", lambda: smoke)
    assert cli.main(["doctor"]) == 1
    assert smoke in capsys.readouterr().out


def test_render_subcommand_reports_resolve_error(report_path, tmp_path, capsys):
    report = AnalysisReport.model_validate_json(report_path.read_bytes())
    report.result.rows[0][-1] = "not numeric"
    report_path.write_text(report.model_dump_json())
    spec = tmp_path / "donut.vis"
    spec.write_text(DONUT)
    assert cli.main(["render", str(spec), "--report", str(report_path), "--out", str(tmp_path / "out")]) == 2
    assert "must be numeric" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.skipif(gptvis.available() is not None, reason=gptvis.available() or "")
@pytest.mark.parametrize("chart", ["line", "table"])
def test_render_subcommand_preserves_check_compromises(report_path, tmp_path, capsys, chart):
    from tests.designer.conftest import monthly

    report = AnalysisReport.model_validate_json(report_path.read_bytes())
    columns, result = monthly(3)
    for i, row in enumerate(result.rows):
        row[1] = 100 + i
    report.analysis.columns, report.result = columns, result
    report_path.write_text(report.model_dump_json())
    text = ("vis line\nbind\n  time month\n  value visits\nzero false" if chart == "line"
            else "vis table\nlabels on")
    spec = tmp_path / "chart.vis"
    spec.write_text(text + "\ntitle Visits\ndescription Monthly visits\n")
    assert cli.main(["render", str(spec), "--report", str(report_path), "--out", str(tmp_path / "out")]) == 0
    compromises = json.loads(capsys.readouterr().out)["compromises"]
    expected = ("The value axis starts at 100 instead of zero." if chart == "line"
                else "tables are drawn as the package draws them")
    assert any(c["message"] == expected for c in compromises)
