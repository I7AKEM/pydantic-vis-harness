# evals/analyst/run.py
"""Run an analyst evaluation set against a real model. Requires OPENROUTER_API_KEY.

    uv run python -m evals.analyst.run                    # evals/analyst/cases
    uv run python -m evals.analyst.run --model openrouter:openai/gpt-5.4-mini --mismatches

Scores: whether every expected column appears in the result with the same values, rows aligned (numbers rounded to
four significant digits, column names ignored, extra columns allowed), whether a clarification came back when one was expected, whether no error-level
check remained, and seconds per question.
"""

import argparse
import asyncio
import itertools
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from vis_agent.analyst.agent import DEFAULT_ANALYST_MODEL, analyze_dataset, create_analyst
from vis_agent.analyst.models import AnalysisReport
from vis_agent.models import DataBrief
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, create_profiler
from vis_agent.store import DatasetStore

CASES_DIR = Path(__file__).with_name("cases")


DATE_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]00:00:00(?:\.0+)?(?:Z|[+-]\d{2}:\d{2})?$")
MONTH_START = re.compile(r"^(\d{4}-\d{2})-01$")
YEAR_START = re.compile(r"^(\d{4})-01$")


def _normal(value):
    """Four significant digits for numbers; midnight timestamps become dates; first-of-month dates become months."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        if value == 0 or not math.isfinite(value):
            return float(value)
        number = float(round(value, 3 - int(math.floor(math.log10(abs(value))))))
        # A whole number that looks like a year compares equal to a year bucket written as a date.
        return str(int(number)) if number.is_integer() and 1000 <= number <= 3000 else number
    text = str(value).strip()
    if match := DATE_MIDNIGHT.match(text):
        text = match[1]
    if match := MONTH_START.match(text):
        text = match[1]
    if match := YEAR_START.match(text):
        text = match[1]
    return text


def _key(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def tables_match(expected: dict, actual: dict) -> float:
    """1.0 when every expected column appears in the actual table with the same values and the rows line up.

    Column names are ignored, extra actual columns are allowed, row order is ignored.
    """
    if len(expected["rows"]) != len(actual["rows"]):
        return 0.0
    expected_columns = [[_normal(row[i]) for row in expected["rows"]] for i in range(len(expected["columns"]))]
    actual_columns = [[_normal(row[i]) for row in actual["rows"]] for i in range(len(actual["columns"]))]
    # A share may come back as a fraction or a percentage; both count.
    variants = list(enumerate(actual_columns))
    for j, column in enumerate(actual_columns) if not expected.get("strict_scale") else []:
        if column and all(isinstance(v, float) and 0 <= v <= 1 for v in column):
            variants.append((j, [_normal(v * 100) for v in column]))
    candidates = [[(j, column) for j, column in variants if sorted(map(_key, column)) == sorted(map(_key, wanted))]
                  for wanted in expected_columns]
    if any(not choice for choice in candidates):
        return 0.0
    expected_rows = sorted(_key(list(row)) for row in zip(*expected_columns))
    for choice in itertools.product(*candidates):
        if len({j for j, _ in choice}) != len(choice):
            continue
        rows = sorted(_key([column[r] for _, column in choice]) for r in range(len(actual["rows"])))
        if rows == expected_rows:
            return 1.0
    return 0.0


@dataclass
class TableMatches(Evaluator[dict, AnalysisReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, AnalysisReport, dict]) -> float:
        if ctx.expected_output["expect"] != "table":
            return 1.0 if ctx.output.clarification is not None else 0.0
        if ctx.output.result is None:
            return 0.0
        return tables_match(ctx.expected_output, {"columns": ctx.output.result.columns, "rows": ctx.output.result.rows})


@dataclass
class ChecksClean(Evaluator[dict, AnalysisReport, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, AnalysisReport, dict]) -> bool:
        return all(c.passed or c.severity != "error" for c in ctx.output.checks)


def load_cases(cases_dir: Path = CASES_DIR) -> list[Case]:
    specs = json.loads((cases_dir / "cases.json").read_text(encoding="utf-8"))
    expected = json.loads((cases_dir / "expected.json").read_text(encoding="utf-8")) if (cases_dir / "expected.json").exists() else {}
    cases = []
    for spec in specs:
        table = expected.get(spec["name"], {"columns": [], "rows": []})
        cases.append(Case(
            name=spec["name"],
            inputs={"csv": str((cases_dir / spec["csv"]).resolve()), "question": spec["question"], "brief": spec.get("brief")},
            expected_output={"expect": spec["expect"], "columns": table["columns"], "rows": table["rows"],
                             **({"strict_scale": True} if spec.get("strict_scale") else {})},
        ))
    return cases


def build_dataset(cases_dir: Path = CASES_DIR) -> Dataset:
    return Dataset(name=f"analyst-{cases_dir.name}", cases=load_cases(cases_dir), evaluators=[TableMatches(), ChecksClean()])


def write_evidence(path: Path, report, cases_dir: Path, models: dict[str, str]) -> None:
    """Preserve complete results and failed checks, even when table values matched gold."""
    from evals.evidence import provenance
    evidence = {
        "provenance": provenance(cases_dir / "cases.json", models),
        "cases": [{"name": case.name, "inputs": case.inputs, "expected": case.expected_output,
                   "output": case.output.model_dump(mode="json"),
                   "scores": {name: score.value for name, score in case.scores.items()},
                   "assertions": {name: assertion.value for name, assertion in case.assertions.items()},
                   "evaluator_failures": [str(failure) for failure in case.evaluator_failures]}
                  for case in report.cases],
        "failures": [str(failure) for failure in report.failures],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_mismatch(case: Case, output: AnalysisReport) -> None:
    """Print failed error checks as well as incorrect tables or missing clarification."""
    failed = [check for check in output.checks if not check.passed and check.severity == "error"]
    mismatch = False
    if case.expected_output["expect"] == "clarification":
        if output.clarification is None:
            mismatch = True
            print(f"{case.name}: expected a clarification, got a table")
    else:
        got = {"columns": output.result.columns, "rows": output.result.rows} if output.result else None
        if got is None or tables_match(case.expected_output, got) < 1.0:
            mismatch = True
            print(f"{case.name}: expected {case.expected_output['rows'][:3]}, got "
                  f"{got['rows'][:3] if got else output.warnings or output.clarification}")
    for check in failed:
        print(f"{case.name}: {check.check} [{check.column or 'result'}]: {check.message}")
    if (mismatch or failed) and output.analysis:
        print(f"    sql: {output.analysis.sql}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default="cases", help="directory under evals/analyst holding cases.json")
    parser.add_argument("--model", default=None, help="OpenRouter model for the analyst")
    parser.add_argument("--profiler-model", default=None)
    parser.add_argument("--max-concurrency", type=int, default=4)
    parser.add_argument("--mismatches", action="store_true", help="print differing tables and failed error checks")
    parser.add_argument("--out", type=Path, help="Save full outputs, scores, assertions, and run provenance")
    args = parser.parse_args()
    load_dotenv()
    model = args.model or os.getenv("PYDANTIC_AI_ANALYST_MODEL") or DEFAULT_ANALYST_MODEL
    profiler_model = args.profiler_model or os.getenv("PYDANTIC_AI_PROFILER_MODEL") or DEFAULT_PROFILER_MODEL
    profiler = create_profiler(profiler_model)
    analyst = create_analyst(model)
    cases_dir = Path(__file__).parent / args.cases
    dataset = build_dataset(cases_dir)
    outputs: dict[str, AnalysisReport] = {}

    with tempfile.TemporaryDirectory() as tmp:
        store = DatasetStore(Path(tmp))

        async def task(inputs: dict) -> AnalysisReport:
            brief = DataBrief.model_validate(inputs["brief"]) if inputs["brief"] else None
            source = await asyncio.to_thread(store.save_upload, Path(inputs["csv"]).name, Path(inputs["csv"]).read_bytes(), brief)
            report = await analyze_dataset(store, profiler, analyst, source.dataset_id, inputs["question"])
            outputs[inputs["question"]] = report
            return report

        report = asyncio.run(dataset.evaluate(task, max_concurrency=args.max_concurrency))
    report.print(include_input=False, include_output=False)
    print(f"model: {model}")
    if args.out:
        write_evidence(args.out, report, cases_dir, {"analyst": model, "profiler": profiler_model})
    if args.mismatches:
        for case in dataset.cases:
            out = outputs.get(case.inputs["question"])
            if out is None:
                continue
            print_mismatch(case, out)


if __name__ == "__main__":
    main()
