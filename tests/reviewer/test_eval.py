# tests/reviewer/test_eval.py
import asyncio
import json
from datetime import datetime, timezone

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from evals.reviewer.build_labelled import build_labelled
from evals.reviewer.run import evaluate, load_labelled
from vis_agent.analyst.models import Analysis, AnalysisReport
from vis_agent.reviewer.agent import create_reviewer
from tests.designer.conftest import cities

SPEC = "vis bar\ntitle Violations by city\ndescription d\nbind\n  category city\n  value violations\nsort value desc\n"


def team_case(name, agree=True):
    columns, result = cities()
    report = AnalysisReport(dataset_id="ds", question="Top cities", language="en",
                            analysis=Analysis(sql="x", columns=columns, summary="s"), result=result,
                            seconds=0, created_at=datetime.now(timezone.utc))
    return {"case": {"case_id": name, "question": "Top cities", "language": "en"},
            "harness": {"png_path": f"png/{name}.png"},
            "stages": {"analyst": {"status": "judged", "output": json.loads(report.model_dump_json())},
                       "designer": {"status": "judged",
                                    "output": {"spec": SPEC, "chart": "bar", "intent": "rank", "explanation": "e",
                                               "considered": [], "compromises": []},
                                    "a": {"verdict": "fail", "reasoning_en": "Bars sorted wrongly."},
                                    "b": {"verdict": "fail" if agree else "pass", "reasoning_en": "Fine." if not agree else "Wrong sort."},
                                    "consensus": {"consensus": "fail" if agree else "split", "agree": agree}}}}


def test_build_labelled_keeps_agreed_designer_cases_with_their_pictures(tmp_path):
    run = tmp_path / "run"
    (run / "cases").mkdir(parents=True)
    (run / "png").mkdir()
    for name, agree in (("one", True), ("two", False)):
        (run / "cases" / f"{name}.json").write_text(json.dumps(team_case(name, agree)), encoding="utf-8")
        (run / "png" / f"{name}.png").write_bytes(b"png")
    out = tmp_path / "labelled"
    cases = build_labelled(run, out)
    assert [c["name"] for c in cases] == ["one"] and (out / "png" / "one.png").read_bytes() == b"png"
    assert cases[0]["judges"]["a"]["verdict"] == "fail" and cases[0]["design"]["chart"] == "bar"
    assert json.loads((out / "cases.json").read_text(encoding="utf-8"))[0]["png"] == "png/one.png"


def test_evaluate_scores_agreement_with_the_human_verdicts(tmp_path):
    run = tmp_path / "run"
    (run / "cases").mkdir(parents=True)
    (run / "png").mkdir()
    for name in ("one", "two"):
        (run / "cases" / f"{name}.json").write_text(json.dumps(team_case(name)), encoding="utf-8")
        (run / "png" / f"{name}.png").write_bytes(b"png")
    out = tmp_path / "labelled"
    build_labelled(run, out)
    (out / "human.json").write_text(json.dumps({"one": {"verdict": "fail"}, "two": {"verdict": "pass"}}), encoding="utf-8")
    cases, human = load_labelled(out)

    def always_revise(messages, info):
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_review", args={"summary": "Wrong sort.", "findings": [
            {"rule": "R-5", "level": "error", "owner": "designer", "message": "Sorted ascending."}]})])

    reviewer = create_reviewer("test")
    with reviewer.override(model=FunctionModel(always_revise)):
        result = asyncio.run(evaluate(cases, human, reviewer, out))
    assert result["compared"] == 2 and result["agreement"] == 0.5
    assert result["confusion"] == {"fail/revise": 1, "pass/revise": 1} and result["rules"] == {"R-5": 2}
    assert [d["name"] for d in result["disagreements"]] == ["two"]
