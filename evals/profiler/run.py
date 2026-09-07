"""Run a profiler evaluation set against a real model. Requires OPENROUTER_API_KEY.

    uv run python -m evals.profiler.run                       # the twelve hand-made cases
    uv run python -m evals.profiler.run --cases corpus_cases  # the fifty corpus cases
    uv run python -m evals.profiler.run --model openrouter:mistralai/mistral-small-2603 --mismatches

Scores: role and unit accuracy per case, whether every expected failed check was flagged, and cost.
`--mismatches` prints every column whose role differs from the expectation.
"""

import argparse
import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from vis_agent.store import DatasetStore
from vis_agent.models import DataBrief
from vis_agent.profiler.models import DatasetProfile
from vis_agent.profiler.review import failed_checks
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, create_profiler, profile_dataset

CASES_DIR = Path(__file__).with_name("cases")


@dataclass
class RoleAccuracy(Evaluator[dict, DatasetProfile, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DatasetProfile, dict]) -> float:
        wanted = ctx.expected_output["roles"]
        if ctx.output.semantic is None:
            return 0.0
        got = {c.name: c.role for c in ctx.output.semantic.columns}
        return sum(got.get(name) == role for name, role in wanted.items()) / len(wanted)


@dataclass
class UnitAccuracy(Evaluator[dict, DatasetProfile, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DatasetProfile, dict]) -> float:
        wanted = ctx.expected_output.get("units", {})
        if not wanted:
            return 1.0
        if ctx.output.semantic is None:
            return 0.0
        got = {c.name: (c.unit or "").strip().casefold() for c in ctx.output.semantic.columns}
        return sum(got.get(name) == unit.casefold() for name, unit in wanted.items()) / len(wanted)


@dataclass
class ExpectedChecksFlagged(Evaluator[dict, DatasetProfile, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, DatasetProfile, dict]) -> bool:
        if ctx.output.semantic is None:
            return False
        flagged = {c.check for c in failed_checks(ctx.output.review)}
        return set(ctx.expected_output["failed_checks"]) <= flagged


def load_cases(cases_dir: Path = CASES_DIR) -> list[Case]:
    expected = json.loads((cases_dir / "expected.json").read_text(encoding="utf-8"))
    cases = []
    for name, expectation in expected.items():
        brief_path = cases_dir / f"{name}.brief.json"
        cases.append(Case(
            name=name,
            inputs={"csv": str(cases_dir / f"{name}.csv"),
                    "brief": brief_path.read_text(encoding="utf-8") if brief_path.exists() else None},
            expected_output=expectation,
        ))
    return cases


def build_dataset(cases_dir: Path = CASES_DIR) -> Dataset:
    name = "profiler-phase-1" if cases_dir == CASES_DIR else f"profiler-{cases_dir.name}"
    return Dataset(name=name, cases=load_cases(cases_dir), evaluators=[RoleAccuracy(), ExpectedChecksFlagged(), UnitAccuracy()])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default="cases", help="directory under evals/profiler holding the cases")
    parser.add_argument("--model", default=None, help="OpenRouter model, e.g. openrouter:openai/gpt-5.4-mini")
    parser.add_argument("--max-concurrency", type=int, default=6)
    parser.add_argument("--mismatches", action="store_true", help="print each column whose role differs from the expectation")
    args = parser.parse_args()
    load_dotenv()
    model = args.model or os.getenv("PYDANTIC_AI_PROFILER_MODEL") or DEFAULT_PROFILER_MODEL
    profiler = create_profiler(model)
    workdir = Path(tempfile.mkdtemp(prefix="profiler-evals-"))
    store = DatasetStore(workdir)

    async def task(inputs: dict) -> DatasetProfile:
        path = Path(inputs["csv"])
        brief = DataBrief.model_validate_json(inputs["brief"]) if inputs["brief"] else None
        dataset = store.save_upload(path.name, path.read_bytes(), brief)
        return await profile_dataset(store, profiler, dataset.dataset_id)

    dataset = build_dataset(Path(__file__).with_name(args.cases))
    report = asyncio.run(dataset.evaluate(task, max_concurrency=args.max_concurrency))
    report.print(include_input=False, include_output=False)
    print(f"model: {model}")
    if args.mismatches:
        for case in report.cases:
            got = {c.name: c.role for c in case.output.semantic.columns} if case.output.semantic else {}
            misses = [f"{name}: expected {role}, got {got.get(name)}" for name, role in case.expected_output["roles"].items() if got.get(name) != role]
            if misses:
                print(f"{case.name}: " + "; ".join(misses))


if __name__ == "__main__":
    main()
