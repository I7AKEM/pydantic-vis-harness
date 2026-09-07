"""Optimize the designer's instructions with DSPy GEPA; Pydantic AI stays the runtime.

    uv run python -m evals.designer.agent.optimize_instructions check
    uv run python -m evals.designer.agent.optimize_instructions run light OUT_DIR --split train

Only main constructs models or reads credentials. It uses OPENROUTER_API_KEY,
PYDANTIC_AI_DESIGNER_MODEL (default Gemma), and OPTIMIZE_REFLECTION_MODEL
(default anthropic/claude-sonnet-4.6), following the profiler optimizer.
The saved instructions include grammar and catalogue; adoption into rulebook.md
requires controller review and evaluation with the runtime agent and its tools.
"""

import argparse
import json
import os
import random
import re
import tempfile
import time
from pathlib import Path

import dspy
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from vis_agent.analyst.agent import ARABIC
from vis_agent.analyst.checks import summary_numbers_exist
from vis_agent.analyst.models import AnalysisReport
from vis_agent.designer.agent import DEFAULT_DESIGNER_MODEL, build_prompt, instructions
from vis_agent.designer.check import check_spec
from vis_agent.designer.models import SpecError
from vis_agent.designer.recommend import recommend_charts
from vis_agent.designer.syntax import parse
from vis_agent.models import DataBrief, Intent

from .run import reference_charts

CASES_PATH = Path(__file__).parent / "scale" / "cases.json"


class DesignOut(BaseModel):
    spec: str
    explanation: str


class DesignSig(dspy.Signature):
    prompt: str = dspy.InputField(
        desc="the designer's prompt JSON: question, language, brief, columns, facts, preview",
    )
    design: DesignOut = dspy.OutputField(
        desc="the chart spec text in the grammar and a two-sentence explanation",
    )


def seed_instructions() -> str:
    return instructions()


class Designer(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(DesignSig.with_instructions(seed_instructions()))

    def forward(self, prompt):
        return self.predict(prompt=prompt)


def load(cases_path: Path, split: str) -> list[dspy.Example]:
    """Read fixed reports and the exact runtime prompt without model access.

    Split membership is the inline field written by capture.py. The optimizer
    only consumes train and dev; held-out data belongs to the runtime evaluation.
    """
    if split not in {"train", "dev"}:
        raise ValueError("The optimizer only loads train or dev, never heldout.")
    cases_path = Path(cases_path)
    examples = []
    for case in json.loads(cases_path.read_text(encoding="utf-8")):
        if case.get("split") != split:
            continue
        path = (cases_path.parent / case["report"]).resolve()
        report = AnalysisReport.model_validate_json(path.read_text(encoding="utf-8"))
        if report.analysis is None or report.result is None:
            continue  # the analyst asked a question instead; the runner lists such cases, the optimizer skips them
        brief = DataBrief.model_validate(case["brief"]) if case.get("brief") else None
        examples.append(dspy.Example(
            name=case["name"], prompt=build_prompt(report, brief).model_dump_json(),
            report=str(path), language=case["language"], intent=brief.intent if brief else None,
            task=(case.get("metadata") or {}).get("task"),
        ).with_inputs("prompt"))
    return examples



def score_and_feedback(gold, pred) -> tuple[float, str]:
    """Four deterministic components; explanation evidence is part of Passed.

    BindingRight has empty expectations in scale cases, so any parsed spec
    satisfies it. Actual invalid bindings still fail check_spec (Passed).
    """
    try:
        design = DesignOut.model_validate(pred.design)
    except (AttributeError, TypeError, ValidationError):
        return 0.0, "Return a design with spec text in the grammar and a two-sentence explanation."

    report = AnalysisReport.model_validate_json(Path(gold.report).read_text(encoding="utf-8"))
    check = check_spec(design.spec, report.analysis.columns, report.result)
    lines = [f"line {v.line or 1}: {v.rule}: {v.message}. {v.fix}" for v in check.violations]
    context = " ".join([report.question, *report.result.columns])
    numbers = summary_numbers_exist(design.explanation, report.result, context)
    if not numbers.passed:
        lines.append(f"summary_numbers_exist: {numbers.message}")

    passed = check.ok and numbers.passed
    try:
        spec = parse(design.spec)
    except SpecError:
        return float(passed) / 4, "\n".join(lines)

    # Neither the spec grammar nor DesignOut declares intent. Use the gold
    # brief's intent for this single-shot proxy; the runtime uses design.intent.
    accepted = reference_charts(report, gold.intent)
    chart_accepted = spec.type in accepted
    if not chart_accepted:
        choices = ", ".join(accepted) or "(none; the result cannot support a chart)"
        lines.append(f"ChartAccepted: {spec.type} is outside the reference charts for intent {gold.intent!r}. "
                     f"Choose from: {choices}.")

    title = spec.title or ""
    arabic_title = bool(ARABIC.search(title))
    script_right = arabic_title if gold.language == "ar" else (
        bool(re.search(r"[A-Za-z]", title)) and not arabic_title
    )
    language_right = spec.language == gold.language and script_right
    if not language_right:
        language = "Arabic" if gold.language == "ar" else "English"
        lines.append(f"LanguageRight: Write the title in {language} and set language {gold.language}.")

    binding_right = True  # Scale cases have no expected bindings or emphasis.
    score = sum((passed, chart_accepted, language_right, binding_right)) / 4
    return score, "\n".join(lines) if lines else "All checks passed."


def metric(gold, pred, trace=None, pred_name=None, pred_trace=None) -> dspy.Prediction:
    score, feedback = score_and_feedback(gold, pred)
    return dspy.Prediction(score=score, feedback=feedback)


def plain_metric(gold, pred, trace=None):
    return score_and_feedback(gold, pred)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "run"))
    parser.add_argument("budget", nargs="?", choices=("light", "medium"), default="light")
    parser.add_argument("out_dir", nargs="?", type=Path)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--split", choices=("train",), default="train")
    args = parser.parse_args()
    train = load(args.cases, args.split)
    dev = load(args.cases, "dev") if args.mode == "run" else []
    if not train or (args.mode == "run" and not dev):
        parser.error("check needs nonempty train cases; run needs nonempty train and dev cases")

    load_dotenv(Path.cwd() / ".env")
    key = os.environ["OPENROUTER_API_KEY"]
    task_model = (os.getenv("PYDANTIC_AI_DESIGNER_MODEL") or DEFAULT_DESIGNER_MODEL).removeprefix("openrouter:")
    reflection_model = os.getenv("OPTIMIZE_REFLECTION_MODEL", "anthropic/claude-sonnet-4.6")
    task_lm = dspy.LM(f"openrouter/{task_model}", api_key=key, temperature=0.0, max_tokens=6000,
                      extra_body={"reasoning": {"effort": "none"}})
    reflection_lm = dspy.LM(f"openrouter/{reflection_model}", api_key=key, temperature=1.0, max_tokens=16000)
    dspy.configure(lm=task_lm)
    prog = Designer()
    if args.mode == "check":
        for example in train[:4]:
            started = time.perf_counter()
            pred = prog(prompt=example.prompt)
            score, feedback = score_and_feedback(example, pred)
            print(f"{example.name}: score {score:.2f} in {time.perf_counter() - started:.1f}s | {feedback[:200]}")
        return

    out = args.out_dir or Path(tempfile.mkdtemp(prefix="optimized-"))
    out.mkdir(parents=True, exist_ok=True)
    random.Random(7).shuffle(train)
    print(f"train {len(train)} dev {len(dev)} budget {args.budget}", flush=True)
    base = dspy.Evaluate(devset=dev, metric=plain_metric, num_threads=8, display_progress=False)(prog)
    print("seed instructions on dev:", base, flush=True)
    gepa = dspy.GEPA(metric=metric, auto=args.budget, reflection_lm=reflection_lm, num_threads=8,
                     track_stats=True, reflection_minibatch_size=4)
    optimized = gepa.compile(prog, trainset=train, valset=dev)
    after = dspy.Evaluate(devset=dev, metric=plain_metric, num_threads=8, display_progress=False)(optimized)
    print("optimized instructions on dev:", after, flush=True)
    optimized.save(str(out / f"optimized-{args.budget}.json"))
    path = out / f"instructions-{args.budget}.txt"
    path.write_text(optimized.predict.signature.instructions, encoding="utf-8")
    print("saved", path)


if __name__ == "__main__":
    main()
