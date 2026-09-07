import json
from datetime import datetime, timezone

import dspy
import pytest

from evals.designer.agent import optimize_instructions as optimizer
from vis_agent.analyst.models import Analysis, AnalysisReport
from vis_agent.designer.agent import build_prompt, instructions
from vis_agent.designer.models import Candidate, Recommendation
from vis_agent.models import DataBrief

from .conftest import gender_share


DONUT = "vis donut\ntitle Gender share\ndescription Share by gender\nbind\n  category label\n  value share\n"
EXPLANATION = "The chart shows the share by gender. A donut compares the parts of the whole."


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("Loading and scoring must never construct or call a model")

    monkeypatch.setattr(dspy, "LM", forbidden)
    monkeypatch.setattr(dspy.Predict, "forward", forbidden)


@pytest.fixture
def scale(tmp_path):
    columns, result = gender_share()
    cases = []
    for name, split, language, question in (
        ("train_share", "train", "English", "Share by gender?"),
        ("dev_share", "dev", "Arabic", "ما الحصة حسب الجنس؟"),
    ):
        report = AnalysisReport(
            dataset_id=name, question=question, language=language,
            analysis=Analysis(sql="SELECT 1", columns=columns, summary="A mistaken 99% claim."),
            result=result, seconds=0, created_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
        )
        (tmp_path / f"{name}.json").write_text(report.model_dump_json(), encoding="utf-8")
        cases.append({
            "name": name, "report": f"{name}.json", "split": split,
            "brief": {"intent": "share"}, "language": "ar" if language == "Arabic" else "en",
            "expect": "design", "charts": None, "bind": {}, "emphasis": None,
            "metadata": {"task": "composition", "chosen_chart": "scatter"},
        })
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    return path


def prediction(spec=DONUT, explanation=EXPLANATION):
    return dspy.Prediction(design=optimizer.DesignOut(spec=spec, explanation=explanation))


def test_valid_donut_and_metric_feedback(scale):
    gold = optimizer.load(scale, "train")[0]
    assert optimizer.score_and_feedback(gold, prediction()) == (1.0, "All checks passed.")
    result = optimizer.metric(gold, prediction(), trace=[], pred_name="predict", pred_trace=[])
    assert result.score == 1.0
    assert result.feedback == "All checks passed."
    assert optimizer.plain_metric(gold, prediction()) == 1.0


def test_c2_feedback_includes_line_rule_and_fix(scale):
    score, feedback = optimizer.score_and_feedback(
        optimizer.load(scale, "train")[0], prediction(DONUT.replace("value share", "value missing")),
    )
    assert score == 0.75
    assert "line 1: C2:" in feedback
    assert "Bind 'value' to a column in the result" in feedback


@pytest.mark.parametrize("spec", [DONUT, DONUT + "language ar\n"])
def test_english_title_fails_arabic_language_part(scale, spec):
    score, feedback = optimizer.score_and_feedback(optimizer.load(scale, "dev")[0], prediction(spec))
    assert score == 0.75
    assert "LanguageRight" in feedback
    assert "Arabic" in feedback


def test_arabic_title_and_language_pass(scale):
    spec = DONUT.replace("Gender share", "الحصة حسب الجنس") + "language ar\n"
    assert optimizer.score_and_feedback(optimizer.load(scale, "dev")[0], prediction(spec))[0] == 1.0


@pytest.mark.parametrize("title", ["123", "الحصة", "Gender الحصة"])
def test_english_case_requires_latin_title_without_arabic(scale, title):
    score, feedback = optimizer.score_and_feedback(
        optimizer.load(scale, "train")[0], prediction(DONUT.replace("Gender share", title)),
    )
    assert score < 1.0
    assert "LanguageRight" in feedback


@pytest.mark.parametrize("number", ["99%", "٩٩%"])
def test_invented_explanation_number_fails_even_when_in_summary(scale, number):
    score, feedback = optimizer.score_and_feedback(
        optimizer.load(scale, "train")[0], prediction(explanation=f"The share is {number}."),
    )
    assert score == 0.75
    assert "summary_numbers_exist" in feedback
    assert "Use only numbers from the result" in feedback


def test_supported_explanation_numbers_pass(scale):
    assert optimizer.score_and_feedback(
        optimizer.load(scale, "train")[0], prediction(explanation="Female: 60%. Male: 40%."),
    ) == (1.0, "All checks passed.")


def test_syntax_error_has_actionable_feedback(scale):
    score, feedback = optimizer.score_and_feedback(
        optimizer.load(scale, "train")[0], prediction("vis nonexistent\n"),
    )
    assert score == 0.0
    assert "line 1: syntax:" in feedback
    assert "Correct the syntax on this line" in feedback


def test_missing_design_fails_without_crashing(scale):
    score, feedback = optimizer.score_and_feedback(optimizer.load(scale, "train")[0], dspy.Prediction())
    assert score == 0.0
    assert "spec" in feedback and "explanation" in feedback


def test_valid_but_unaccepted_chart_loses_one_component(scale):
    gold = optimizer.load(scale, "train")[0]
    gold.intent = "rank"
    score, feedback = optimizer.score_and_feedback(
        gold, prediction(),
    )
    assert score == 0.75
    assert "ChartAccepted" in feedback
    assert "bar" in feedback


def test_load_uses_runtime_prompt_and_carries_only_gold_context(scale):
    for split, name, language in (("train", "train_share", "en"), ("dev", "dev_share", "ar")):
        examples = optimizer.load(scale, split)
        assert len(examples) == 1
        gold = examples[0]
        assert gold.name == name
        assert gold.report == str(scale.parent / f"{name}.json")
        assert gold.language == language
        assert gold.intent == "share"
        assert gold.task == "composition"
        report = AnalysisReport.model_validate_json((scale.parent / f"{name}.json").read_text())
        assert gold.prompt == build_prompt(report, DataBrief(intent="share")).model_dump_json()
        assert dict(gold.inputs()) == {"prompt": gold.prompt}
        assert "chosen_chart" not in gold


def test_seed_instructions_are_runtime_instructions():
    assert optimizer.seed_instructions() == instructions()
    assert optimizer.Designer().predict.signature.instructions == instructions()


def test_heldout_reports_are_never_read(scale):
    cases = json.loads(scale.read_text())
    cases.append({"name": "held_out", "split": "heldout", "report": "does-not-exist.json"})
    scale.write_text(json.dumps(cases), encoding="utf-8")
    assert len(optimizer.load(scale, "train")) == 1
    assert len(optimizer.load(scale, "dev")) == 1
    with pytest.raises(ValueError, match="never heldout"):
        optimizer.load(scale, "heldout")


def test_optional_brief_and_task_do_not_become_labels(scale):
    cases = json.loads(scale.read_text())
    cases[0]["brief"] = None
    cases[0].pop("metadata")
    scale.write_text(json.dumps(cases), encoding="utf-8")
    gold = optimizer.load(scale, "train")[0]
    assert gold.intent is None
    assert gold.task is None
    assert json.loads(gold.prompt)["intent"] is None
    score, feedback = optimizer.score_and_feedback(gold, prediction())
    assert score == 0.75
    assert "ChartAccepted" in feedback


def test_reference_threshold_and_swaps(monkeypatch):
    columns, result = gender_share()
    report = AnalysisReport(
        dataset_id="ds", question="Share?", language="English",
        analysis=Analysis(sql="SELECT 1", columns=columns, summary=""), result=result,
        seconds=0, created_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
    )
    candidates = [Candidate(name=name, score=score, binding={}, breakdown=[]) for name, score in (
        ("column", 3), ("grouped_column", 2), ("stacked_bar", 2), ("pie", 2),
        ("line", 1), ("table", -1),
    )]
    import evals.designer.agent.run as runner
    monkeypatch.setattr(runner, "recommend_charts", lambda *args, **kwargs: Recommendation(
        candidates=candidates, rejected=[],
    ))
    # Swap partners count only when the rules listed them as non-negative candidates.
    assert set(optimizer.reference_charts(report, "share")) == {"column", "grouped_column", "stacked_bar", "pie"}
    candidates[:] = [Candidate(name="table", score=-1, binding={}, breakdown=[])]
    assert optimizer.reference_charts(report, None) == []
    candidates.clear()
    assert optimizer.reference_charts(report, None) == []
