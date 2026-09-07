import json
import subprocess
import sys

import pytest
from pydantic import TypeAdapter

from evals.designer.run import evaluate, load_cases
from vis_agent.designer.catalogue import CATALOGUE
from vis_agent.models import Intent


def test_recommendation_eval_meets_threshold():
    score, failures = evaluate(load_cases())
    assert score >= 0.9, json.dumps(failures, ensure_ascii=False, indent=2)


def test_cases_cover_catalogue_with_explicit_bounded_rows():
    cases = load_cases()
    assert len(cases) >= 30
    assert len({case["name"] for case in cases}) == len(cases)
    names = {entry.name for entry in CATALOGUE.entries}
    assert {case["expected"][0] for case in cases if case["expected"]} == names
    for case in cases:
        assert set(case) == {"name", "columns", "rows", "intent", "suggested", "expected", "why"}
        assert len(case["rows"]) <= 60
        assert set(case["expected"]) <= names
        assert case["why"]
        TypeAdapter(Intent | None).validate_python(case["intent"])


def test_evaluate_scores_only_top_rank_and_accepts_alternatives():
    case = next(case for case in load_cases() if case["name"] == "district_fines_compare")
    # Bar is an eligible runner-up; membership below first place must not pass.
    wrong_top = dict(case, expected=["bar"])
    score, failures = evaluate([wrong_top])
    assert score == 0.0
    failure = failures[0]
    assert failure["name"] == case["name"]
    assert failure["expected"] == ["bar"]
    assert len(failure["top_three"]) == 3
    assert failure["top_three"][0]["name"] == "column"
    for candidate in failure["top_three"]:
        assert candidate["score"] == sum(rule["score"] for rule in candidate["breakdown"])
    assert evaluate([dict(case, expected=["bar", "column"])]) == (1.0, [])
    assert evaluate([case, wrong_top])[0] == 0.5


def test_empty_result_requires_empty_expectation():
    empty = next(case for case in load_cases() if case["name"] == "empty_result")
    assert evaluate([empty]) == (1.0, [])
    score, failures = evaluate([dict(empty, expected=["table"])])
    assert score == 0.0
    assert failures[0]["top_three"] == []
    assert failures[0]["rejected"][0]["rule"] == "H12"
    scalar = next(case for case in load_cases() if case["name"] == "one_number")
    assert evaluate([dict(scalar, expected=[])])[0] == 0.0
    with pytest.raises(ValueError, match="at least one case"):
        evaluate([])


def test_runner_custom_file_reports_failures_and_exits_zero(tmp_path):
    scalar = next(case for case in load_cases() if case["name"] == "one_number")
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([dict(scalar, expected=["pie"])]), encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-m", "evals.designer.run", "--cases", str(path)],
        capture_output=True, text=True, check=True,
    )
    lines = run.stdout.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("one_number: expected ['pie']; top three:")
    assert '"breakdown"' in lines[0]
    assert '"rule": "S13"' in lines[0]
    assert lines[1] == "score: 0/1"
