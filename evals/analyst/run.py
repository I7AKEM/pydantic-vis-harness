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


def _normal(value):
    """Four significant digits for numbers; midnight timestamps become dates; first-of-month dates become months."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        if value == 0 or not math.isfinite(value):
            return float(value)
        return float(round(value, 3 - int(math.floor(math.log10(abs(value))))))
    text = str(value).strip()
    if match := DATE_MIDNIGHT.match(text):
        text = match[1]
    if match := MONTH_START.match(text):
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
    candidates = [[j for j, column in enumerate(actual_columns) if sorted(map(_key, column)) == sorted(map(_key, wanted))]
                  for wanted in expected_columns]
    if any(not choice for choice in candidates):
        return 0.0
    expected_rows = sorted(_key(list(row)) for row in zip(*expected_columns))
    for choice in itertools.product(*candidates):
        if len(set(choice)) != len(choice):
            continue
        rows = sorted(_key([actual_columns[j][r] for j in choice]) for r in range(len(actual["rows"])))
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
            expected_output={"expect": spec["expect"], "columns": table["columns"], "rows": table["rows"]},
        ))
    return cases


def build_dataset(cases_dir: Path = CASES_DIR) -> Dataset:
    return Dataset(name=f"analyst-{cases_dir.name}", cases=load_cases(cases_dir), evaluators=[TableMatches(), ChecksClean()])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default="cases", help="directory under evals/analyst holding cases.json")
    parser.add_argument("--model", default=None, help="OpenRouter model for the analyst")
    parser.add_argument("--profiler-model", default=None)
    parser.add_argument("--max-concurrency", type=int, default=4)
    parser.add_argument("--mismatches", action="store_true", help="print each case whose table differs")
    args = parser.parse_args()
    load_dotenv()
    model = args.model or os.getenv("PYDANTIC_AI_ANALYST_MODEL") or DEFAULT_ANALYST_MODEL
    profiler = create_profiler(args.profiler_model or os.getenv("PYDANTIC_AI_PROFILER_MODEL") or DEFAULT_PROFILER_MODEL)
    analyst = create_analyst(model)
    dataset = build_dataset(Path(__file__).with_name(args.cases))
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
    if args.mismatches:
        for case in dataset.cases:
            out = outputs.get(case.inputs["question"])
            if out is None:
                continue
            if case.expected_output["expect"] == "clarification":
                if out.clarification is None:
                    print(f"{case.name}: expected a clarification, got a table")
                continue
            got = {"columns": out.result.columns, "rows": out.result.rows} if out.result else None
            if got is None or tables_match(case.expected_output, got) < 1.0:
                print(f"{case.name}: expected {case.expected_output['rows'][:3]}, got {got['rows'][:3] if got else out.warnings or out.clarification}")
                if out.analysis:
                    print(f"    sql: {out.analysis.sql}")


if __name__ == "__main__":
    main()
