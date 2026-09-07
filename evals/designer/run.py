"""Evaluate hand-written result shapes without calling a model or renderer.

    uv run python -m evals.designer.run [--cases path/to/cases.json]
"""

import argparse
import json
from pathlib import Path

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.designer.recommend import recommend_charts

CASES_PATH = Path(__file__).with_name("cases.json")


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(cases: list[dict]) -> tuple[float, list[dict]]:
    """Score only the first ranked candidate; an empty expectation requires no candidates."""
    if not cases:
        raise ValueError("The evaluation set must contain at least one case.")
    failures = []
    for case in cases:
        columns = [ResultColumn.model_validate(column) for column in case["columns"]]
        rows = case["rows"]
        if any(len(row) != len(columns) for row in rows):
            raise ValueError(f"{case['name']}: row width does not match columns")
        # SQL and physical types are placeholders: these fixtures are already result tables.
        result = QueryResult(
            sql="", columns=[column.name for column in columns],
            types=["DOUBLE" if column.kind in ("measure", "share") else "VARCHAR" for column in columns],
            rows=rows, row_count=len(rows), seconds=0,
        )
        recommendation = recommend_charts(columns, result, intent=case["intent"], suggested=case["suggested"])
        candidates = recommendation.candidates
        expected = case["expected"]
        passed = candidates[0].name in expected if candidates else not expected
        if not passed:
            failures.append({
                "name": case["name"], "expected": expected,
                "top_three": [candidate.model_dump() for candidate in candidates[:3]],
                "rejected": [rejection.model_dump() for rejection in recommendation.rejected],
            })
    return (len(cases) - len(failures)) / len(cases), failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=CASES_PATH, help="JSON file of recommendation cases")
    cases = load_cases(parser.parse_args().cases)
    _, failures = evaluate(cases)
    for failure in failures:
        print(f"{failure['name']}: expected {failure['expected']}; "
              f"top three: {json.dumps(failure['top_three'], ensure_ascii=False)}")
    print(f"score: {len(cases) - len(failures)}/{len(cases)}")


if __name__ == "__main__":
    main()
