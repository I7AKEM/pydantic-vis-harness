"""Run the profiler evaluation set against a real model. Requires OPENROUTER_API_KEY.

    uv run python -m evals.profiler.run

Scores: role and unit accuracy per case, whether every expected failed check was flagged, and cost.
"""

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from dataset_store import DatasetStore
from profile_models import DataBrief, DatasetProfile
from profile_review import failed_checks
from profiler import create_profiler, profile_dataset

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


def load_cases() -> list[Case]:
    expected = json.loads((CASES_DIR / "expected.json").read_text(encoding="utf-8"))
    cases = []
    for name, expectation in expected.items():
        brief_path = CASES_DIR / f"{name}.brief.json"
        cases.append(Case(
            name=name,
            inputs={"csv": str(CASES_DIR / f"{name}.csv"),
                    "brief": brief_path.read_text(encoding="utf-8") if brief_path.exists() else None},
            expected_output=expectation,
        ))
    return cases


def build_dataset() -> Dataset:
    return Dataset(name="profiler-phase-1", cases=load_cases(), evaluators=[RoleAccuracy(), ExpectedChecksFlagged(), UnitAccuracy()])


def main() -> None:
    load_dotenv()
    model = os.getenv("PYDANTIC_AI_PROFILER_MODEL") or os.getenv("PYDANTIC_AI_MODEL", "openrouter:anthropic/claude-sonnet-4.6")
    profiler = create_profiler(model)
    workdir = Path(tempfile.mkdtemp(prefix="profiler-evals-"))
    store = DatasetStore(workdir)

    async def task(inputs: dict) -> DatasetProfile:
        path = Path(inputs["csv"])
        brief = DataBrief.model_validate_json(inputs["brief"]) if inputs["brief"] else None
        dataset = store.save_upload(path.name, path.read_bytes(), brief)
        return await profile_dataset(store, profiler, dataset.dataset_id)

    dataset = build_dataset()
    report = asyncio.run(dataset.evaluate(task))
    report.print(include_input=False, include_output=False)


if __name__ == "__main__":
    main()
