import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

import vis_agent.cli as cli
from tests.designer.conftest import gender_share
from vis_agent.analyst.models import Analysis, AnalysisReport, Clarification
from vis_agent.designer.agent import render_id
from vis_agent.designer.models import Design, DesignReport
from vis_agent.models import DataBrief
from vis_agent.render import gptvis
from vis_agent.render.base import Rendered, RenderFailed, RendererUnavailable

SALES = b"id,region,date,amount\n001,East,2026-01-01,10\n"
DONUT = "vis donut\ntitle Gender share\ndescription Share by gender\nbind\n  category label\n  value share\nsort value desc\n"


@pytest.fixture
def design_report(report_path):
    report = AnalysisReport.model_validate_json(report_path.read_bytes())
    return DesignReport(
        dataset_id=report.dataset_id, question=report.question, language=report.language,
        design=Design(spec=DONUT, chart="donut", intent="share", explanation="Share by gender.",
                      considered=["donut", "pie"], compromises=[]),
        seconds=0, created_at=report.created_at,
    )


@pytest.mark.parametrize("explicit_out", [False, True])
def test_design_subcommand_prints_the_report(report_path, design_report, store, tmp_path, monkeypatch, capsys,
                                           explicit_out):
    designer = object()
    brief = DataBrief(intent="share", brand_colors=["#112233", "#334455"])
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(brief.model_dump_json())
    source = AnalysisReport.model_validate_json(report_path.read_bytes())
    out = tmp_path / "chart" if explicit_out else store.directory / "renders" / render_id(DONUT, source)

    async def fake_design(report_arg, designer_arg, brief_arg, renderer):
        assert report_arg == source and designer_arg is designer
        assert brief_arg == brief and renderer == "gptvis"
        return design_report

    def fake_render(report_arg, design_arg, out_arg, renderer="gptvis"):
        assert report_arg == source and design_arg == design_report.design
        assert out_arg == out and renderer == "gptvis"
        return Rendered(png=out / "chart.png", html=out / "chart.html", config=out / "config.json",
                        width=2400, height=1350, seconds=1, non_background_share=0.1,
                        compromises=[], drawn_rows=2, folded_rows=0, dropped_rows=0)

    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, None, None, designer))
    monkeypatch.setattr(cli, "design_chart", fake_design)
    monkeypatch.setattr(cli, "render_design", fake_render)
    args = ["design", str(report_path), "--brief", str(brief_path), "--renderer", "gptvis"]
    if explicit_out:
        args += ["--out", str(out)]
    assert cli.main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert {key: printed[key] for key in design_report.model_dump()} == design_report.model_dump(mode="json")
    for key, filename in [("png", "chart.png"), ("html", "chart.html"), ("config", "config.json")]:
        assert printed["render"][key] == str(out / filename)


def test_design_subcommand_without_render(report_path, design_report, monkeypatch, capsys):
    async def fake_design(report, designer, brief, renderer):
        assert brief is None
        return design_report

    def unexpected_render(*args, **kwargs):
        pytest.fail("--no-render must not call the renderer")

    monkeypatch.setattr(cli, "resources", lambda: (None, None, None, None, None, object()))
    monkeypatch.setattr(cli, "design_chart", fake_design)
    monkeypatch.setattr(cli, "render_design", unexpected_render)
    assert cli.main(["design", str(report_path), "--no-render"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["design"] == design_report.design.model_dump(mode="json")
    assert printed["render"] is None


def test_design_subcommand_reports_a_clarification(report_path, design_report, monkeypatch, capsys):
    design_report.design = None
    design_report.clarification = Clarification(question="Which chart?", reason="The request is ambiguous.")

    async def fake_design(*args):
        return design_report

    def unexpected_render(*args, **kwargs):
        pytest.fail("A clarification must not reach the renderer")

    monkeypatch.setattr(cli, "resources", lambda: (None, None, None, None, None, object()))
    monkeypatch.setattr(cli, "design_chart", fake_design)
    monkeypatch.setattr(cli, "render_design", unexpected_render)
    assert cli.main(["design", str(report_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["design"] is None and printed["render"] is None
    assert printed["clarification"] == design_report.clarification.model_dump(mode="json")


@pytest.mark.parametrize("missing", ["analysis", "result"])
def test_design_subcommand_rejects_an_incomplete_report(report_path, monkeypatch, capsys, missing):
    report = AnalysisReport.model_validate_json(report_path.read_bytes())
    setattr(report, missing, None)
    report_path.write_text(report.model_dump_json())

    def unexpected_resources():
        pytest.fail("An incomplete report must be rejected before loading application resources")

    monkeypatch.setattr(cli, "resources", unexpected_resources)
    assert cli.main(["design", str(report_path)]) == 2
    assert "analysis and a result" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.parametrize("error", [RendererUnavailable("install the renderer"), RenderFailed("render timed out")])
def test_design_subcommand_reports_runtime_failure(report_path, design_report, monkeypatch, capsys, error):
    async def fake_design(*args):
        return design_report

    def fail_render(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli, "resources", lambda: (None, None, None, None, None, object()))
    monkeypatch.setattr(cli, "design_chart", fake_design)
    monkeypatch.setattr(cli, "render_design", fail_render)
    assert cli.main(["design", str(report_path), "--out", "unused"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == str(error)


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
    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, object(), object(), object()))
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
    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, object(), object(), object()))
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
    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, object(), object(), object()))
    assert cli.main(["ask", "--upload", str(csv_path), "Total by region"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["question"] == "Total by region" and printed["dataset_id"].startswith("ds_")


def test_failures_subcommand_lists_failed_checks(store, monkeypatch, capsys):
    from vis_agent import cli

    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, object(), object(), object()))
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
    spec.write_text(DONUT + "language ar\ndirection rtl\n")
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
    monkeypatch.setattr(cli, "resources", lambda: (None, None, store, None, None, None))
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


@pytest.mark.parametrize("chart", ["column", "donut"])
def test_render_subcommand_reports_invalid_numeric_value(report_path, tmp_path, capsys, chart):
    report = AnalysisReport.model_validate_json(report_path.read_bytes())
    report.result.rows[0][-1] = "not numeric"
    report_path.write_text(report.model_dump_json())
    spec = tmp_path / "donut.vis"
    spec.write_text(DONUT.replace("vis donut", f"vis {chart}"))
    assert cli.main(["render", str(spec), "--report", str(report_path), "--out", str(tmp_path / "out")]) == 2
    printed = json.loads(capsys.readouterr().out)
    if chart == "column":
        assert "must be numeric" in printed["error"]
    else:
        assert not printed["ok"]
        assert any(v["rule"] == "C10" and v["message"].startswith("H14:") for v in printed["violations"])


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


class FakeRequests:
    def __init__(self):
        self.summaries, self.artifacts = [], []

    def list_requests(self, dataset_id=None, conversation_id=None, unfinished_only=False, limit=50):
        return self.summaries

    def list_artifacts(self, dataset_id=None, artifact_id=None, limit=50):
        return self.artifacts

    def get_artifact(self, artifact_id):
        from types import SimpleNamespace

        return SimpleNamespace(dataset_id="ds_" + "1" * 32, artifact_id=artifact_id)


class FakeDeps:
    def __init__(self):
        self.requests = FakeRequests()


def outcome(status="done", **fields):
    from vis_agent.requests.models import RequestOutcome

    return RequestOutcome(request_id="rq_" + "a" * 32, status=status, **fields)


@pytest.fixture
def request_cli(monkeypatch, store):
    from types import SimpleNamespace

    deps, calls = FakeDeps(), []
    request = SimpleNamespace(request_id="rq_" + "a" * 32)

    def fake_create(deps_arg, **kwargs):
        calls.append(("create", kwargs))
        return request

    async def fake_run(deps_arg, request_id, usage=None):
        calls.append(("run", request_id))
        return outcome()

    async def fake_answer(deps_arg, request_id, answer, answered_by, usage=None):
        calls.append(("answer", request_id, answer, answered_by))
        return outcome("waiting")

    monkeypatch.setattr(cli, "resources", lambda: (None, deps, store, None, None, None))
    monkeypatch.setattr(cli, "create_request", fake_create)
    monkeypatch.setattr(cli, "run_request", fake_run)
    monkeypatch.setattr(cli, "answer_request", fake_answer)
    return deps, calls


def test_draw_creates_and_runs_a_request(request_cli, store, tmp_path, capsys):
    deps, calls = request_cli
    dataset_id = store.save_upload("sales.csv", SALES).dataset_id
    assert cli.main(["draw", dataset_id, "Total by region"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "done" and printed["request_id"].startswith("rq_")
    kind, kwargs = calls[0]
    assert kind == "create" and kwargs["type"] == "new" and kwargs["dataset_id"] == dataset_id
    assert kwargs["question"] == "Total by region" and kwargs["caller"].kind == "terminal"
    assert calls[1] == ("run", "rq_" + "a" * 32)


def test_draw_uploads_first(request_cli, tmp_path, capsys):
    deps, calls = request_cli
    csv = tmp_path / "sales.csv"
    csv.write_bytes(SALES)
    assert cli.main(["draw", "--upload", str(csv), "Total by region"]) == 0
    assert re.fullmatch(r"ds_[0-9a-f]{32}", calls[0][1]["dataset_id"])


def test_revise_names_the_parent_and_the_change(request_cli, capsys):
    deps, calls = request_cli
    assert cli.main(["revise", "art_" + "b" * 32, "Make it blue", "--redo-analysis"]) == 0
    kind, kwargs = calls[0]
    assert kwargs["type"] == "revise" and kwargs["parent_artifact_id"] == "art_" + "b" * 32
    assert kwargs["question"] == "Make it blue" and kwargs["redo_analysis"] is True
    assert kwargs["dataset_id"] == "ds_" + "1" * 32


def test_resume_with_an_answer_exits_three_while_waiting(request_cli, capsys):
    deps, calls = request_cli
    assert cli.main(["resume", "rq_" + "a" * 32, "--answer", "The amount column"]) == 3
    assert calls == [("answer", "rq_" + "a" * 32, "The amount column", "terminal")]
    assert json.loads(capsys.readouterr().out)["status"] == "waiting"
    assert cli.main(["resume", "rq_" + "a" * 32]) == 0


def test_requests_and_artifacts_print_lists(request_cli, capsys):
    from datetime import datetime, timezone

    from vis_agent.requests.models import ArtifactSummary, RequestSummary

    deps, _calls = request_cli
    moment = datetime.now(timezone.utc)
    deps.requests.summaries = [RequestSummary(request_id="rq_" + "a" * 32, type="new", dataset_id="ds_" + "1" * 32,
                                              question="q", status="done", created_at=moment, updated_at=moment)]
    deps.requests.artifacts = [ArtifactSummary(artifact_id="art_" + "b" * 32, request_id="rq_" + "a" * 32,
                                               dataset_id="ds_" + "1" * 32, version=1, question="q", created_at=moment)]
    assert cli.main(["requests"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["request_id"] == "rq_" + "a" * 32
    assert cli.main(["artifacts", "ds_" + "1" * 32]) == 0
    assert json.loads(capsys.readouterr().out)[0]["artifact_id"] == "art_" + "b" * 32


def test_suggest_runs_the_lead_once(monkeypatch, capsys):
    from types import SimpleNamespace

    seen = {}

    class Lead:
        async def run(self, prompt, deps=None, usage_limits=None):
            seen["prompt"], seen["deps"], seen["limits"] = prompt, deps, usage_limits
            return SimpleNamespace(output="1. Total by region, because the amounts vary.")

    from vis_agent.deps import AppDeps

    deps = AppDeps(store=None, profiler=None, analyst=None, designer=None)
    monkeypatch.setattr(cli, "resources", lambda: (Lead(), deps, None, None, None, None))
    assert cli.main(["suggest", "ds_" + "1" * 32]) == 0
    assert "ds_" + "1" * 32 in seen["prompt"] and "three to five" in seen["prompt"]
    assert seen["deps"].caller_kind == "terminal" and seen["limits"].request_limit == 40
    assert "Total by region" in capsys.readouterr().out


def test_request_errors_print_json_and_exit_two(request_cli, monkeypatch, capsys):
    def failing(deps_arg, **kwargs):
        raise ValueError("The request needs a question or a change.")

    monkeypatch.setattr(cli, "create_request", failing)
    assert cli.main(["draw", "ds_" + "1" * 32, "  "]) == 2
    assert "question" in json.loads(capsys.readouterr().out)["error"]
