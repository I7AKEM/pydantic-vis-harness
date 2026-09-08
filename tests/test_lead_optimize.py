import hashlib
import json
import subprocess
import sys

import dspy

from evals.lead.proxy_cases import build
from evals.lead.run import corpus_cases
from evals.lead.optimize_instructions import Action, score_and_feedback


def _dataset_id(example: dspy.Example) -> str:
    return json.loads(example.state)["datasets"][0]["dataset_id"]


def _gold(**overrides) -> dspy.Example:
    values = {
        "name": "draw",
        "message": "Show sales by month.",
        "state": "{}",
        "tool": "draw",
        "question_as_written": "Show sales by month.",
        "redo_analysis": None,
        "answer_expected": None,
        "must_not_ask": True,
    }
    values.update(overrides)
    return dspy.Example(**values).with_inputs("message", "state")


def _prediction(**overrides) -> dspy.Prediction:
    values = {"tool": "draw", "question": "Show sales by month.", "reply": ""}
    values.update(overrides)
    return dspy.Prediction(action=Action(**values))


def test_build_makes_disjoint_grouped_examples_outside_runtime_sample():
    train, dev = build(7)

    assert train
    assert dev
    train_ids = {_dataset_id(example) for example in train}
    dev_ids = {_dataset_id(example) for example in dev}
    heldout_ids = {
        "ds_" + hashlib.md5(case["name"].removeprefix("corpus-").encode()).hexdigest()
        for case in corpus_cases()
    }
    assert train_ids.isdisjoint(dev_ids)
    assert (train_ids | dev_ids).isdisjoint(heldout_ids)
    assert len(train_ids) == 30
    assert len(dev_ids) == 10
    assert len(train) == 30 * 12
    assert len(dev) == 10 * 12
    assert all(sum(_dataset_id(item) == dataset_id for item in train + dev) == 12
               for dataset_id in train_ids | dev_ids)

    expected_tools = {
        tool
        for example in train + dev
        for tool in (example.tool if isinstance(example.tool, list) else [example.tool])
    }
    assert expected_tools == {
        "profile_csv", "draw", "answer_question", "revise", "resume",
        "find_dataset", "find_artifact", "none",
    }


def test_right_draw_scores_one():
    assert score_and_feedback(_gold(), _prediction()) == (1.0, "All right.")


def test_rephrased_question_loses_argument_credit():
    score, feedback = score_and_feedback(
        _gold(),
        _prediction(question="Monthly sales."),
    )

    assert score == 0.75
    assert "as the user wrote it" in feedback


def test_wrong_tool_scores_at_most_half_and_names_expected_tool():
    score, feedback = score_and_feedback(
        _gold(tool="answer_question", must_not_ask=False),
        _prediction(tool="draw"),
    )

    assert score <= 0.5
    assert "answer_question" in feedback


def test_preasking_loses_no_preasking_credit():
    score, feedback = score_and_feedback(
        _gold(),
        _prediction(reply="Which column?"),
    )

    assert score == 0.75
    assert "Never ask" in feedback


def test_invalid_action_scores_zero():
    assert score_and_feedback(_gold(), dspy.Prediction()) == (
        0.0,
        "Return one action: the tool and its arguments, or none with the reply.",
    )


def test_help_needs_no_credentials():
    result = subprocess.run(
        [sys.executable, "-m", "evals.lead.optimize_instructions", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
