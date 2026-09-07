import asyncio
import json
from pathlib import Path

import pytest
from pydantic_evals import Dataset

from evals.designer.agent import run
from vis_agent.analyst.models import AnalysisReport
from vis_agent.designer.models import Candidate, Recommendation, Rejection
from vis_agent.designer.recommend import recommend_charts

from .conftest import gender_share
from .test_eval_agent import gender_report


def share_report():
    report = AnalysisReport.model_validate_json(
        (run.CASES_PATH.parent / "reports/deaths_by_gender.json").read_text()
    )
    report.analysis.columns, report.result = gender_share()
    return report


@pytest.fixture
def scale_cases(tmp_path):
    original = next(case for case in json.loads(run.CASES_PATH.read_text())
                    if case["name"] == "deaths_by_gender")
    original["report"] = str(run.CASES_PATH.parent / original["report"])
    cases = [dict(original, name=split, charts=None, split=split, seeded=split == "dev",
                  metadata={"task": "comparison", "insightor_chart": "scatter"})
             for split in ("train", "dev", "heldout")]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases))
    return path


def score(case, output, evaluator):
    report = asyncio.run(Dataset(name="scale-test", cases=[case], evaluators=[evaluator]).evaluate(lambda inputs: output))
    assert not report.failures and not report.cases[0].evaluator_failures
    return report.cases[0].scores[type(evaluator).__name__].value


def test_reference_charts_uses_all_nearby_nonnegative_candidates():
    report = share_report()
    charts = run.reference_charts(report, "share")
    assert {"donut", "pie", "bar", "column", "table"} <= set(charts)
    # The design's score threshold also includes treemap, despite the brief's shorter example.
    ranking = recommend_charts(report.analysis.columns, report.result, intent="share")
    assert set(charts) == {c.name for c in ranking.candidates if c.score >= 0}
    assert len(charts) == len(set(charts))
    report.result.rows = []
    report.result.row_count = 0
    assert run.reference_charts(report, "share") == []


@pytest.mark.parametrize("first,swap", [
    ("bar", "column"), ("grouped_bar", "grouped_column"),
    ("stacked_column", "stacked_bar"), ("donut", "pie"),
])
@pytest.mark.parametrize("swap_score", [0, -1, None])
def test_reference_swaps_can_cross_threshold_but_not_negative_or_rejected(monkeypatch, first, swap, swap_score):
    candidates = [Candidate(name=first, score=4, binding={}, breakdown=[])]
    if swap_score is not None:
        candidates.append(Candidate(name=swap, score=swap_score, binding={}, breakdown=[]))
    ranking = Recommendation(candidates=candidates, rejected=[
        Rejection(name=swap, rule="H1", explanation="Rejected")
    ] if swap_score is None else [])
    monkeypatch.setattr(run, "recommend_charts", lambda *args, **kwargs: ranking)
    assert set(run.reference_charts(share_report(), None)) == ({first, swap} if swap_score == 0 else {first})


def test_chart_acceptance_uses_designer_intent_and_preserves_explicit_labels(scale_cases, monkeypatch):
    case = run.load_cases(scale_cases)[0]
    output = gender_report()
    output.design.intent = "share"
    seen = []

    def reference(report, intent):
        assert isinstance(report, AnalysisReport)
        seen.append(intent)
        return ["donut"]

    monkeypatch.setattr(run, "reference_charts", reference)
    assert score(case, output, run.ChartAccepted()) == 1
    output.design.chart = "scatter"  # Insightor metadata is not an acceptable-chart label.
    assert score(case, output, run.ChartAccepted()) == 0
    assert seen == ["share", "share"]
    case.expected_output["charts"] = ["scatter"]
    assert score(case, output, run.ChartAccepted()) == 1
    case.expected_output["charts"] = []
    assert score(case, output, run.ChartAccepted()) == 0
    assert len(seen) == 2
    output.design = None
    case.expected_output["charts"] = None
    assert score(case, output, run.ChartAccepted()) == 0


@pytest.mark.parametrize("task,intent", [
    ("single_value", "share"), ("comparison", "compare"), ("ranking", "rank"),
    ("composition", "composition"), ("distribution", "distribution"),
])
def test_intent_plausible_task_mapping(scale_cases, task, intent):
    case = run.load_cases(scale_cases)[0]
    case.metadata["task"] = task
    output = gender_report()
    output.design.intent = intent
    assert score(case, output, run.IntentPlausible()) == 1
    output.design.intent = "trend"
    assert score(case, output, run.IntentPlausible()) == 0
    output.design = None
    assert score(case, output, run.IntentPlausible()) == 0


@pytest.mark.parametrize("task", [None, "table", "unrecognized"])
def test_intent_without_a_mapped_task_is_neutral(scale_cases, task):
    case = run.load_cases(scale_cases)[0]
    case.metadata = {} if task is None else {"task": task}
    output = gender_report()
    assert score(case, output, run.IntentPlausible()) == 1


def test_load_split_keeps_metadata_and_filters_before_reading_reports(scale_cases):
    cases = json.loads(scale_cases.read_text())
    cases[0]["report"] = "does-not-exist.json"
    scale_cases.write_text(json.dumps(cases))
    selected = run.load_cases(scale_cases, split="dev")
    assert [case.name for case in selected] == ["dev"]
    assert selected[0].metadata == {
        "why": cases[1]["why"], "split": "dev", "seeded": True,
        "task": "comparison", "insightor_chart": "scatter",
    }
    assert "task" not in selected[0].inputs
    dataset = run.build_dataset(scale_cases, split="dev", judge="test")
    assert [type(e).__name__ for e in dataset.evaluators][-2:] == ["IntentPlausible", "LLMJudge"]
    assert len(run.build_dataset().evaluators) == 6


def test_judgment_summary_separates_seeded_and_unseeded():
    summary = run.judgment_summary({
        "seed": {"verdict": "fail", "failed": ["title", "title"], "seeded": True},
        "real": {"verdict": "pass", "failed": [], "seeded": False},
        "legacy": {"verdict": "pass", "failed": ["units"]},
        "pending": {"seeded": True},
    })
    assert summary == {
        "judged": 3, "correct": 1, "share": 1 / 3,
        "failed_by_criterion": {"title": 1, "units": 1},
        "seeded": {"judged": 1, "correct": 0, "share": 0},
        "unseeded": {"judged": 2, "correct": 1, "share": 0.5},
    }
    assert run.judgment_summary({"seed": {"verdict": "pass", "seeded": True}})["unseeded"]["share"] == 0


def test_review_page_groups_splits_and_exports_provenance(tmp_path):
    entries = [{"name": name, "split": split, "seeded": seeded, "spec": "<unsafe>"}
               for name, split, seeded in [("h", "heldout", False), ("d", "dev", True), ("t", "train", False)]]
    page = run.write_review_page(tmp_path, entries).read_text()
    assert page.index('data-name="t"') < page.index('data-name="d"') < page.index('data-name="h"')
    assert 'data-split="dev"' in page and 'data-seeded="true"' in page
    assert "Seeded" in page and "&lt;unsafe&gt;" in page
    assert "section.dataset.split" in page and "section.dataset.seeded" in page


def test_main_judgments_filters_repeats_and_enriches_seeded_metadata(scale_cases, monkeypatch, capsys):
    judgments = {f"{split} [1/2]": {"verdict": "pass", "spec": gender_report().design.spec}
                 for split in ("train", "dev", "heldout")}
    scale_cases.with_name("judgments.json").write_text(json.dumps({"judgments": judgments}))
    monkeypatch.setattr("sys.argv", ["eval", "--cases", str(scale_cases), "--split", "dev", "--judgments"])
    monkeypatch.setattr(run, "create_designer", lambda *args: pytest.fail("No model for judgments"))
    run.main()
    printed = capsys.readouterr().out
    assert '"judged": 1' in printed and '"delivered_specs": 1' in printed
    assert '"seeded": {' in printed and '"unseeded": {' in printed
    assert "cases: 1; seeded: 1; unseeded: 0" in printed


def test_main_scale_repeat_render_and_mismatches(scale_cases, tmp_path, monkeypatch, capsys):
    from vis_agent.designer.agent import create_designer
    from vis_agent.render.base import RenderFailed

    async def fake_design(report, designer, brief):
        output = gender_report()
        output.design.intent = "trend"
        return output

    def failed_render(*args):
        raise RenderFailed("offline fixture")

    monkeypatch.setattr(run, "create_designer", lambda *args: create_designer("test"))
    monkeypatch.setattr(run, "design_chart", fake_design)
    monkeypatch.setattr(run, "render_design", failed_render)
    monkeypatch.setattr(run, "load_dotenv", lambda: None)
    monkeypatch.setattr("sys.argv", ["eval", "--cases", str(scale_cases), "--split", "dev", "--model", "test",
                                    "--repeat", "2", "--render", "--mismatches"])
    run.main()
    printed = capsys.readouterr().out
    assert "IntentPlausible" in printed and "dev [1/2]" in printed
    assert "train [" not in printed and "heldout [" not in printed
    page_path = Path(next(line.removeprefix("review page: ") for line in printed.splitlines()
                          if line.startswith("review page: ")))
    assert page_path.is_relative_to(scale_cases.parent)
    page = page_path.read_text()
    assert page.count('data-split="dev"') == 2 and page.count('data-seeded="true"') == 2
    assert "offline fixture" in page
