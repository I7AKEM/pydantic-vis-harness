# evals/reviewer/export_verdicts.py
"""Copy every reviewed artifact's verdict out of the store as a labelling candidate.

Usage: uv run python -m evals.reviewer.export_verdicts [--data DATA_DIRECTORY] [--out evals/reviewer/verdicts]
"""

import argparse
import json
import os
from pathlib import Path

from vis_agent.requests.store import RequestStore
from vis_agent.store import DatasetStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(os.getenv("DATA_DIRECTORY", "data")))
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("verdicts"))
    args = parser.parse_args()
    store = RequestStore(DatasetStore(args.data))
    args.out.mkdir(parents=True, exist_ok=True)
    count = 0
    for summary in store.list_artifacts(limit=10_000):
        artifact = store.get_artifact(summary.artifact_id)
        if not artifact.review or artifact.review.get("status") != "reviewed" or artifact.design is None:
            continue
        (args.out / f"{artifact.artifact_id}.json").write_text(json.dumps({
            "artifact_id": artifact.artifact_id, "question": artifact.question, "language": artifact.report.language,
            "spec": artifact.design.spec, "png": str(args.data / "renders" / artifact.render_id / "chart.png") if artifact.render_id else None,
            "review": artifact.review, "human": None,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        count += 1
    print(f"{count} reviewed artifacts written to {args.out}")


if __name__ == "__main__":
    main()
