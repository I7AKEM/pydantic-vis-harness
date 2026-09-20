# evals/reviewer/run.py
"""Measure the reviewer against human verdicts on the labelled set.

Usage: uv run python -m evals.reviewer.run [--model MODEL] [--labelled DIR] [--out results.json]
MODEL is a Pydantic AI model name (openrouter:...) or litellm:<proxy model name>; the default is
PYDANTIC_AI_REVIEWER_MODEL, else the reviewer's default. A human verdict of pass agrees with a reviewer verdict of
pass; fail agrees with revise. Cases without a human verdict are skipped.
"""

import argparse
import asyncio
import json
import os
import statistics
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from vis_agent.analyst.models import AnalysisReport
from vis_agent.designer.models import Compromise, Design
from vis_agent.reviewer.agent import DEFAULT_REVIEWER_MODEL, create_reviewer, review_chart

from .build_labelled import LABELLED

EXPECTED = {"pass": "pass", "fail": "revise"}


def load_labelled(out: Path = LABELLED) -> tuple[list[dict], dict]:
    cases = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    human_path = out / "human.json"
    human = json.loads(human_path.read_text(encoding="utf-8")) if human_path.is_file() else {}
    return cases, human


def reviewer_for(model: str):
    if model.startswith("litellm:"):
        from vis_agent.providers import litellm_model
        return create_reviewer(litellm_model(model.removeprefix("litellm:")))
    return create_reviewer(model)


async def evaluate(cases: list[dict], human: dict, reviewer, out: Path = LABELLED, concurrency: int = 3) -> dict:
    labelled = [case for case in cases if human.get(case["name"], {}).get("verdict") in EXPECTED]
    gate = asyncio.Semaphore(concurrency)

    async def one(case):
        report = AnalysisReport.model_validate(case["analyst"])
        design = Design.model_validate(case["design"])
        async with gate:
            reviewed = await review_chart(report, design, out / case["png"], reviewer,
                                          compromises=[Compromise.model_validate(c) for c in case["design"].get("compromises", [])])
        return case, reviewed

    results = await asyncio.gather(*(one(case) for case in labelled))
    confusion: Counter = Counter()
    rules: Counter = Counter()
    disagreements = []
    outcomes = []
    agreed = 0
    for case, reviewed in results:
        expected = human[case["name"]]["verdict"]
        got = reviewed.review.verdict if reviewed.review else "unreviewed"
        confusion[f"{expected}/{got}"] += 1
        outcomes.append({"name": case["name"], "human": expected, "reviewer": got,
                         "summary": reviewed.review.summary if reviewed.review else None,
                         "findings": [f.model_dump() for f in reviewed.review.findings] if reviewed.review else [],
                         "evidence": [f.model_dump() for f in reviewed.review.evidence] if reviewed.review else [],
                         "uncertainties": reviewed.review.uncertainties if reviewed.review else [],
                         "image_id": reviewed.review.image_id if reviewed.review else None,
                         "warnings": reviewed.warnings, "requests": reviewed.requests, "seconds": reviewed.seconds})
        if reviewed.review:
            rules.update(finding.rule for finding in reviewed.review.findings)
        if EXPECTED[expected] == got:
            agreed += 1
        else:
            disagreements.append({"name": case["name"], "human": expected, "reviewer": got,
                                  "summary": reviewed.review.summary if reviewed.review else "; ".join(reviewed.warnings),
                                  "findings": [f.model_dump() for f in reviewed.review.findings] if reviewed.review else []})
    compared = len(results)
    clean = sum(human[c["name"]]["verdict"] == "pass" for c, _ in results)
    defective = compared - clean
    times = sorted(r.seconds for _, r in results)
    return {"compared": compared, "agreement": agreed / compared if compared else None, "confusion": dict(confusion),
            "rules": dict(rules), "disagreements": disagreements,
            "clean_cases": clean, "defective_cases": defective,
            "clean_acceptance": confusion["pass/pass"] / clean if clean else None,
            "clean_false_rejection": confusion["pass/revise"] / clean if clean else None,
            "defect_rejection_rate": confusion["fail/revise"] / defective if defective else None,
            "defect_rejection_note": "Verdict agreement only; matching the actual defect needs evidence adjudication.",
            "uncertain": sum(r.review is not None and r.review.verdict == "uncertain" for _, r in results),
            "unreviewed": sum(r.review is None for _, r in results), "outcomes": outcomes,
            "median_seconds": statistics.median(times) if times else None,
            "p95_seconds": times[max(0, (95 * len(times) + 99) // 100 - 1)] if times else None,
            "request_count_scope": "Framework-reported requests; provider calls cancelled before accounting may be absent.",
            "seconds": sum(r.seconds for _, r in results), "requests": sum(r.requests for _, r in results)}


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("PYDANTIC_AI_REVIEWER_MODEL") or DEFAULT_REVIEWER_MODEL)
    parser.add_argument("--labelled", type=Path, default=LABELLED)
    parser.add_argument("--out", type=Path, default=Path("reviewer-results.json"))
    args = parser.parse_args()
    cases, human = load_labelled(args.labelled)
    result = asyncio.run(evaluate(cases, human, reviewer_for(args.model), args.labelled))
    result["model"] = args.model
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("model", "compared", "agreement", "confusion", "rules")}, ensure_ascii=False))
    for item in result["disagreements"]:
        print(f"- {item['name']}: human {item['human']}, reviewer {item['reviewer']}: {item['summary']}")


if __name__ == "__main__":
    main()
