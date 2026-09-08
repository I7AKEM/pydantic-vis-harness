"""Optimize the lead's first-action instructions with DSPy GEPA.

    uv run python -m evals.lead.optimize_instructions check
    uv run python -m evals.lead.optimize_instructions run light OUT_DIR

Pydantic AI stays the runtime. The optimizer trains a proxy, and only main
constructs models or reads credentials.
"""

import argparse
import os
import string
import time
from pathlib import Path
from typing import Literal

import dspy
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from evals.lead.proxy_cases import build
from vis_agent.lead import LEAD_INSTRUCTIONS
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL

PREAMBLE = "You decide the lead's first action for one message. Output the tool and its arguments, or none with the reply."


class Action(BaseModel):
    tool: Literal[
        "profile_csv", "draw", "answer_question", "revise", "resume",
        "find_dataset", "find_artifact", "none",
    ]
    question: str | None = None
    change: str | None = None
    redo_analysis: bool | None = None
    answer: str | None = None
    reply: str = ""


class LeadSig(dspy.Signature):
    message: str = dspy.InputField(desc="the user's message, with the upload line when a CSV is attached")
    state: str = dspy.InputField(desc="JSON: the uploaded datasets with their columns, the request waiting for "
                                      "an answer if any, and the last delivered chart if any")
    action: Action = dspy.OutputField(desc="the first tool the lead calls with its arguments, or none with the reply")


def seed_instructions() -> str:
    return PREAMBLE + "\n\n" + LEAD_INSTRUCTIONS


class Lead(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(LeadSig.with_instructions(seed_instructions()))

    def forward(self, message, state):
        return self.predict(message=message, state=state)


def _tools(gold) -> list[str]:
    return gold.tool if isinstance(gold.tool, list) else [gold.tool]


def _normalized(text: str | None) -> str:
    trailing = string.punctuation + "؟،؛"
    return (text or "").casefold().strip().rstrip(trailing).rstrip()


def _tool_feedback(gold) -> str:
    tools = _tools(gold)
    if tools == ["answer_question"]:
        return "Numbers only is answer_question."
    if "draw" in tools:
        if len(tools) > 1:
            return "A question about attached data is a draw."
        return "A new question about the same data is a draw."
    if tools == ["revise"]:
        kind = "picture" if gold.redo_analysis is False else "numbers"
        value = "false" if gold.redo_analysis is False else "true"
        return f"A change to the {kind} is a revise with redo_analysis {value}."
    if tools == ["resume"]:
        if gold.answer_expected:
            return "The answer to a pending question is a resume with that answer."
        return '"Continue" while waiting is a resume with none.'
    if tools == ["none"]:
        return '"Continue" after a delivered chart is answered in words because resume is not offered.'
    if tools == ["profile_csv"]:
        return "Data attached without a question is profile_csv."
    if tools == ["find_dataset"]:
        return "A file that is not uploaded is find_dataset."
    if tools == ["find_artifact"]:
        return '"What did we make" is find_artifact.'
    return f"Call one of the expected tools: {', '.join(tools)}."


def score_and_feedback(gold, pred) -> tuple[float, str]:
    try:
        action = Action.model_validate(pred.action)
    except (AttributeError, TypeError, ValidationError):
        return 0.0, "Return one action: the tool and its arguments, or none with the reply."

    lines = []
    tools = _tools(gold)
    tool_right = action.tool in tools
    if not tool_right:
        lines.append(_tool_feedback(gold))

    if "draw" in tools or "answer_question" in tools:
        accepted = gold.question_as_written
        accepted = accepted if isinstance(accepted, list) else [accepted]
        arguments_right = _normalized(action.question) in {_normalized(text) for text in accepted}
        if not arguments_right:
            text = accepted[0]
            lines.append(f"Pass the question as the user wrote it: {text!r}.")
    elif tools == ["revise"]:
        arguments_right = action.redo_analysis is gold.redo_analysis
        if not arguments_right:
            feedback = _tool_feedback(gold)
            if feedback not in lines:
                lines.append(feedback)
    elif tools == ["resume"]:
        has_answer = bool((action.answer or "").strip())
        arguments_right = has_answer is gold.answer_expected
        if not arguments_right:
            if gold.answer_expected:
                lines.append("Pass the user's answer to resume.")
            else:
                lines.append('Call resume with no answer for "continue".')
    elif tools == ["none"]:
        arguments_right = bool(action.reply.strip())
        if not arguments_right:
            lines.append("Answer in words with a non-empty reply.")
    else:
        arguments_right = True

    reply = action.reply.lstrip()
    asks = ("?" in reply or "؟" in reply
            or reply.casefold().startswith(("could you", "which", "what", "هل", "ما")))
    no_preasking_right = not gold.must_not_ask or not asks
    if not no_preasking_right:
        expected_tool = action.tool if action.tool in tools else tools[0]
        lines.append(
            f"Never ask which numbers, which column, or which definition before calling {expected_tool}: "
            "the analyst and the designer ask only when they must."
        )

    score = 0.5 * tool_right + 0.25 * arguments_right + 0.25 * no_preasking_right
    return score, "\n".join(lines) if lines else "All right."


def metric(gold, pred, trace=None, pred_name=None, pred_trace=None) -> dspy.Prediction:
    score, feedback = score_and_feedback(gold, pred)
    return dspy.Prediction(score=score, feedback=feedback)


def plain_metric(gold, pred, trace=None):
    return score_and_feedback(gold, pred)[0]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "run"))
    parser.add_argument("budget", nargs="?", choices=("light", "medium"), default="light")
    parser.add_argument("out_dir", nargs="?", type=Path)
    parser.add_argument("--reflection", metavar="MODEL")
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.mode == "run" and args.out_dir is None:
        parser.error("run requires OUT_DIR")
    train, dev = build(7)

    load_dotenv(Path.cwd() / ".env")
    key = os.environ["OPENROUTER_API_KEY"]
    task = (os.getenv("PYDANTIC_AI_MODEL") or DEFAULT_PROFILER_MODEL).removeprefix("openrouter:")
    reflection = (args.reflection or os.getenv("OPTIMIZE_REFLECTION_MODEL")
                  or "openai/gpt-5.6-sol")
    task_lm = dspy.LM(
        f"openrouter/{task}", api_key=key, temperature=0.0, max_tokens=4000,
        extra_body={"reasoning": {"effort": "none"}},
    )
    reflection_lm = dspy.LM(
        f"openrouter/{reflection}", api_key=key, temperature=1.0, max_tokens=16000,
    )
    dspy.configure(lm=task_lm)
    program = Lead()

    if args.mode == "check":
        for example in train[:6]:
            started = time.perf_counter()
            prediction = program(message=example.message, state=example.state)
            score, feedback = score_and_feedback(example, prediction)
            seconds = time.perf_counter() - started
            print(f"{example.name}: score {score:.2f} in {seconds:.1f}s | {feedback[:200]}")
        return

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    print(f"train {len(train)} dev {len(dev)} budget {args.budget}", flush=True)
    seed = dspy.Evaluate(
        devset=dev, metric=plain_metric, num_threads=8, display_progress=False,
    )(program)
    print("seed instructions on dev:", seed, flush=True)
    gepa = dspy.GEPA(
        metric=metric, auto=args.budget, reflection_lm=reflection_lm, num_threads=8,
        track_stats=True, reflection_minibatch_size=4,
    )
    optimized = gepa.compile(program, trainset=train, valset=dev)
    after = dspy.Evaluate(
        devset=dev, metric=plain_metric, num_threads=8, display_progress=False,
    )(optimized)
    print("optimized instructions on dev:", after, flush=True)
    optimized.save(str(out / f"optimized-{args.budget}.json"))
    instructions = out / f"instructions-{args.budget}.txt"
    instructions.write_text(optimized.predict.signature.instructions, encoding="utf-8")
    print("saved", instructions)


if __name__ == "__main__":
    main()
