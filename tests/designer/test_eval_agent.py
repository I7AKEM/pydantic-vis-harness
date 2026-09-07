import asyncio
import json
from html import escape
from pathlib import Path
from typing import get_args

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_evals import Dataset

from evals.designer.agent import run
from vis_agent.analyst.models import AnalysisReport
from vis_agent.designer.agent import create_designer
from vis_agent.designer.catalogue import CATALOGUE
from vis_agent.designer.models import Design, DesignReport
from vis_agent.models import Intent


def gender_report():
    source = AnalysisReport.model_validate_json((run.CASES_PATH.parent / "reports/deaths_by_gender.json").read_text())
    return DesignReport(
        dataset_id=source.dataset_id, question=source.question, language=source.language,
        design=Design(
            spec="vis donut\ntitle Deaths by gender\ndescription Deaths by gender\nlanguage en\nbind\n  category gender_label\n  value total_deaths\n",
            chart="donut", intent="compare", explanation="Deaths by gender. The donut shows two parts of the total.",
            considered=["donut"], compromises=[],
        ),
        requests=1, check_calls=1, seconds=1, created_at=source.created_at,
    )


def score(case, output, evaluators=None):
    dataset = Dataset(name="test-designer", cases=[case], evaluators=evaluators or run.build_dataset().evaluators)
    return asyncio.run(dataset.evaluate(lambda inputs: output)).cases[0]


def test_dataset_builds_without_a_model():
    dataset = run.build_dataset()
    assert len(dataset.cases) == 31
    assert len({case.name for case in dataset.cases}) == 31
    assert [type(e).__name__ for e in dataset.evaluators] == [
        "Delivered", "Passed", "ChartAccepted", "LanguageRight", "BindingRight", "Metrics",
    ]
    names = {entry.name for entry in CATALOGUE.entries}
    for case in dataset.cases:
        report = AnalysisReport.model_validate_json(Path(case.inputs["report"]).read_text())
        assert report.analysis is not None and report.result is not None
        assert bool(report.result.rows) == (case.name != "empty_result")
        assert set(case.expected_output["charts"]) <= names
        assert case.expected_output["language"] in {"ar", "en"}
        assert set(case.expected_output["bind"].values()) <= set(report.result.columns)
        assert case.inputs["question"] == report.question
        assert "columns" in case.inputs["result_description"]


def test_cases_cover_the_design():
    cases = {case.name: case for case in run.load_cases()}
    assert set(get_args(Intent)) <= {case.inputs["brief"]["intent"] for case in cases.values()}
    for language in ("ar", "en"):
        assert sum(case.expected_output["language"] == language for case in cases.values()) >= 14
    assert {
        "deaths_per_month", "married_share_by_gender", "orders_by_status", "deaths_by_gender",
        "paid_share_by_year_since_2020", "violations_by_district_many", "citizens_by_trip_year",
        "actual_fine_distribution", "salary_vs_birth_year", "orders_and_average_price_by_status",
        "discounted_percentage", "unpaid_share_overall", "violation_type_share",
        "deaths_by_year_and_gender", "nationality_share_within_region", "empty_result",
    } <= cases.keys()
    assert cases["deaths_per_month"].inputs["brief"]["suggested_chart_type"] == "line"
    assert cases["married_share_by_gender"].inputs["brief"]["suggested_chart_type"] == "line"
    assert cases["orders_by_status"].inputs["brief"]["brand_colors"] == ["#1F4E79", "#C0504D"]


def test_evaluators_score_a_hand_built_report():
    case = next(case for case in run.load_cases() if case.name == "deaths_by_gender")
    output = gender_report()
    scored = score(case, output)
    assert not scored.evaluator_failures
    assert all(result.value == 1.0 for result in scored.scores.values())
    case.expected_output["language"] = "ar"
    output.design.spec = output.design.spec.replace("language en", "language ar")
    assert score(case, output).scores["LanguageRight"].value == 0
    output.design.spec = output.design.spec.replace("category gender_label", "category gender")
    assert score(case, output).scores["BindingRight"].value == 0
    case.expected_output["emphasis"] = "Female"
    output.design.spec = gender_report().design.spec
    assert score(case, output).scores["BindingRight"].value == 0
    output.design.spec += "emphasis\n  - Female\n"
    assert score(case, output).scores["BindingRight"].value == 1


@pytest.mark.parametrize("chart,share,exists,expected", [
    ("table", 0.0, True, 1), ("table", 0.019, True, 1), ("table", 0.1, False, 0),
    ("donut", 0.019, True, 0), ("donut", 0.02, True, 1), ("donut", 0.1, False, 0),
])
def test_rendered_table_only_requires_png_but_charts_keep_pixel_floor(chart, share, exists, expected, tmp_path, monkeypatch):
    from vis_agent.render.base import Rendered

    case = next(case for case in run.load_cases() if case.name == "deaths_by_gender")
    output = gender_report()
    output.design.chart = chart
    png = tmp_path / "chart.png"
    if exists:
        png.write_bytes(b"fake PNG")
    rendered = Rendered(png=png, html=tmp_path / "chart.html", config=tmp_path / "config.json",
                        width=600, height=400, seconds=0, non_background_share=share,
                        compromises=[], drawn_rows=2, folded_rows=0, dropped_rows=0)
    monkeypatch.setitem(run.render_results, case.inputs["name"], {id(output): rendered})
    scored = score(case, output, evaluators=[run.Rendered()])
    assert not scored.evaluator_failures
    assert scored.scores["Rendered"].value == expected


def test_empty_case_short_circuits():
    case = next(case for case in run.load_cases() if case.name == "empty_result")
    designer = create_designer("test")

    def unexpected_model(messages, info):
        pytest.fail("Empty cases must not call a model")

    with designer.override(model=FunctionModel(unexpected_model)):
        output = asyncio.run(run.make_task(designer)(case.inputs))
    assert output.clarification is not None and output.requests == 0
    scored = score(case, output)
    for name in ("Delivered", "Passed", "ChartAccepted", "LanguageRight", "BindingRight"):
        assert scored.scores[name].value == 1


def test_review_page_and_judgment_summary(tmp_path):
    entries = [{
        "name": "gender", "question": "Deaths by gender?", "language": "en", "chart": "donut",
        "image": "gender/chart.png", "spec": gender_report().design.spec,
        "explanation": "A donut.", "compromises": [], "scores": {"Passed": 1}, "model": "test",
    }, {
        "name": "<empty>", "question": "<script>bad()</script>", "language": "en", "chart": None,
        "image": None, "spec": "</script><script>bad()</script>", "explanation": "No rows.",
        "compromises": [], "scores": {}, "model": "test",
    }]
    path = run.write_review_page(tmp_path, entries)
    page = path.read_text()
    for entry in entries:
        assert escape(entry["name"]) in page
        assert escape(entry["spec"]) in page
        if entry["image"]:
            assert entry["image"] in page
    assert "<script>bad()</script>" not in page
    assert "Copy judgments JSON" in page
    for criterion in run.RUBRIC:
        assert f'name="{criterion}"' in page
    judgments = {"one": {"verdict": "pass", "failed": []}, "two": {"verdict": "pass", "failed": []},
                 "three": {"verdict": "fail", "failed": ["title"]}}
    assert run.judgment_summary(judgments) == {
        "judged": 3, "correct": 2, "share": 2 / 3, "failed_by_criterion": {"title": 1},
    }
    assert run.judgment_summary({})["share"] == 0
    saved = json.loads(run.CASES_PATH.with_name("judgments.json").read_text())
    assert saved["rubric"] == run.RUBRIC
    assert isinstance(saved["judgments"], dict)


def test_acceptance_provenance_and_empty_copy():
    from vis_agent.designer.check import check_spec
    from vis_agent.designer.recommend import recommend_charts

    decisions = json.loads(run.CASES_PATH.with_name("decisions.json").read_text())["cases"]
    for case in run.load_cases():
        source = AnalysisReport.model_validate_json(Path(case.inputs["report"]).read_text())
        ranking = recommend_charts(source.analysis.columns, source.result, intent=case.inputs["brief"]["intent"])
        nearby = {candidate.name for candidate in ranking.candidates
                  if candidate.score >= ranking.candidates[0].score - 1 and candidate.score >= 0}
        assert nearby <= set(case.expected_output["charts"])
        assert set(decisions[case.name]["controller_charts"]) <= set(case.expected_output["charts"])
        if case.name == "orders_by_status":
            spec = "vis column\ntitle Orders by status\ndescription Orders by status\nbind\n  category status\n  value order_count\npalette\n  - #1F4E79\n  - #C0504D\n"
            assert check_spec(spec, source.analysis.columns, source.result).ok
    original = json.loads((run.CASES_PATH.parent / "reports/deaths_by_gender.json").read_text())
    empty = json.loads((run.CASES_PATH.parent / "reports/empty_result.json").read_text())
    original["result"].update(rows=[], row_count=0)
    assert empty == original


def test_malformed_and_missing_designs_fail_scores():
    case = next(case for case in run.load_cases() if case.name == "deaths_by_gender")
    output = gender_report()
    output.design.spec = "not a spec"
    scored = score(case, output)
    assert not scored.evaluator_failures
    for name in ("Passed", "LanguageRight", "BindingRight"):
        assert scored.scores[name].value == 0
    output.design = None
    scored = score(case, output)
    assert scored.scores["Passed"].value == 1
    for name in ("Delivered", "ChartAccepted", "LanguageRight", "BindingRight"):
        assert scored.scores[name].value == 0


def test_task_render_repeats_keep_their_own_results(tmp_path, monkeypatch):
    from vis_agent.render.base import Rendered, RenderFailed

    case = next(case for case in run.load_cases() if case.name == "deaths_by_gender")
    for cache in (run.outputs, run.renders, run.render_results):
        cache.clear()
    calls = []

    async def fake_design(source, designer, brief):
        calls.append((source, brief))
        return gender_report()

    def fake_render(source, design, directory):
        # Reverse completion order; the evaluator must use this output's render.
        import time
        number = int(directory.name.removeprefix("repeat-")) if directory.name.startswith("repeat-") else 1
        if number == 1:
            time.sleep(0.03)
        if number == 3:
            raise RenderFailed("fixture renderer failed")
        (directory / "chart.png").write_bytes(b"fake PNG")
        return Rendered(png=directory / "chart.png", html=directory / "chart.html", config=directory / "config.json",
                        width=600, height=400, seconds=0, non_background_share=0.02 if number == 1 else 0.019,
                        compromises=[], drawn_rows=2, folded_rows=0, dropped_rows=0)

    monkeypatch.setattr(run, "design_chart", fake_design)
    monkeypatch.setattr(run, "render_design", fake_render)
    dataset = Dataset(name="test-repeats", cases=[case], evaluators=[run.Rendered()])
    report = asyncio.run(dataset.evaluate(run.make_task(create_designer("test"), tmp_path), max_concurrency=3, repeat=3))
    assert len(report.cases) == 3 and not report.failures
    assert len(calls) == 3 and all(brief.intent == "compare" for _, brief in calls)
    entries = run._review_entries(report, "test", tmp_path)
    assert len({entry["name"] for entry in entries}) == 3
    assert sorted(case.scores["Rendered"].value for case in report.cases) == [0, 0, 1]
    for case in report.cases:
        assert not case.evaluator_failures
        directory = run.renders[case.inputs["name"]][id(case.output)]
        assert (directory / "spec.txt").read_text() == case.output.design.spec
        assert (directory / "explanation.txt").read_text() == case.output.design.explanation
    assert {entry["image"] for entry in entries} == {
        "deaths_by_gender/chart.png", "deaths_by_gender/repeat-2/chart.png", None,
    }
    assert any(entry["error"] == "fixture renderer failed" for entry in entries)


def test_optional_judge_and_agreement_without_model_calls():
    from pydantic_evals.evaluators import Evaluator, LLMJudge

    dataset = run.build_dataset(judge="test")
    judge = dataset.evaluators[-1]
    assert isinstance(judge, LLMJudge) and judge.model == "test" and judge.include_input
    assert judge.rubric == "\n".join(run.RUBRIC.values()) + "\nJudge the design against the question and the result description."

    class FixedJudge(Evaluator):
        def evaluate(self, ctx):
            return {"LLMJudge": True}

    dataset.cases = [case for case in dataset.cases if case.name == "deaths_by_gender"]
    dataset.evaluators = [FixedJudge()]
    output = gender_report()
    report = asyncio.run(dataset.evaluate(lambda inputs: output))
    human = {"deaths_by_gender": {"verdict": "pass", "failed": [], "model": "test", "spec": output.design.spec}}
    assert run.judge_agreement(report, human, "test") == {"compared": 1, "agreement": 1}
    human["deaths_by_gender"]["verdict"] = "fail"
    assert run.judge_agreement(report, human, "test")["agreement"] == 0
    human["deaths_by_gender"]["spec"] = "a different saved design"
    assert run.judge_agreement(report, human, "test") == {"compared": 0, "agreement": None}


def test_main_judgments_never_constructs_a_model(tmp_path, monkeypatch, capsys):
    cases_path = tmp_path / "cases.json"
    cases = json.loads(run.CASES_PATH.read_text())
    for case in cases:
        case["report"] = str(run.CASES_PATH.parent / case["report"])
    cases_path.write_text(json.dumps(cases))
    spec = gender_report().design.spec
    judgments = {"deaths_by_gender [1/2]": {"verdict": "pass", "failed": [], "spec": spec},
                 "deaths_by_gender [2/2]": {"verdict": "fail", "failed": ["title"], "spec": "bad"}}
    cases_path.with_name("judgments.json").write_text(json.dumps({"rubric": run.RUBRIC, "judgments": judgments}))
    monkeypatch.setattr("sys.argv", ["designer-eval", "--cases", str(cases_path), "--judgments"])
    monkeypatch.setattr(run, "create_designer", lambda *args: pytest.fail("Judgments must not construct a model"))
    run.main()
    printed = capsys.readouterr().out
    assert '"correct": 1' in printed and '"share": 0.5' in printed
    assert run.saved_spec_summary(cases_path, judgments) == {"delivered_specs": 2, "passed": 1, "share": 0.5}


def test_main_runs_offline_with_fake_designer(tmp_path, monkeypatch, capsys):
    cases_path = tmp_path / "cases.json"
    case = next(case for case in json.loads(run.CASES_PATH.read_text()) if case["name"] == "deaths_by_gender")
    case["report"] = str(run.CASES_PATH.parent / case["report"])
    cases_path.write_text(json.dumps([case]))
    created = []

    def fake_designer(model):
        created.append(model)
        return create_designer("test")

    async def fake_design(source, designer, brief):
        output = gender_report()
        output.design.spec = output.design.spec.replace("category gender_label", "category gender")
        return output

    monkeypatch.setattr(run, "create_designer", fake_designer)
    monkeypatch.setattr(run, "design_chart", fake_design)
    monkeypatch.setattr(run, "load_dotenv", lambda: None)
    monkeypatch.setenv("PYDANTIC_AI_DESIGNER_MODEL", "test")
    monkeypatch.setattr("sys.argv", ["designer-eval", "--cases", str(cases_path), "--repeat", "2",
                                    "--max-concurrency", "2", "--mismatches"])
    run.main()
    printed = capsys.readouterr().out
    assert created == ["test"] and "model: test" in printed
    assert "deaths_by_gender [1/2]: BindingRight" in printed and "vis donut" in printed
