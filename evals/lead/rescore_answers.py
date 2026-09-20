"""Recompute only answer numeric fidelity from a saved run, without model calls.

Keep the run's original case expectations, gates, raw messages and assets. This
does not replace the cohort or independently certify chart/image correctness.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from evals.lead import run


def rescore(record: dict) -> dict:
    result = deepcopy(record)
    changes = []
    for case in result["cases"]:
        artifacts = {artifact["artifact_id"]: artifact for artifact in case.get("artifacts", [])}
        for index, turn in enumerate(case["turns"], 1):
            previous = turn.get("answer_fidelity_ok")
            if previous is None:
                continue
            artifact = artifacts.get(turn.get("artifact_id"))
            table = ((artifact or {}).get("report") or {}).get("result")
            if not isinstance(table, dict) or not isinstance(table.get("rows"), list):
                raise ValueError(f"{case['name']} turn {index}: full persisted artifact rows are required")
            if table.get("row_count") != len(table["rows"]):
                raise ValueError(f"{case['name']} turn {index}: persisted artifact rows are incomplete")
            public = deepcopy(((turn.get("tool_return") or {}).get("artifact") or {}))
            public["rows"] = table["rows"]
            public["row_count"] = table["row_count"]
            current = run.answer_numbers_match(turn.get("reply"), public, turn["expected"]["message"])
            turn["answer_fidelity_ok"] = current
            if current != previous:
                changes.append({"case": case["name"], "turn": index, "before": previous, "after": current})
    result["summary"] = run.summarize(result["cases"])
    result["offline_rescore"] = {
        "scope": "answer_fidelity_ok only; original expectations and all other turn fields are unchanged",
        "reason": "Exclude raw render URLs and URL-shaped Markdown labels from numeric claims.",
        "raw_summary": deepcopy(record["summary"]),
        "changed_turns": changes,
        "scorer_sha256": hashlib.sha256(Path(run.__file__).read_bytes()).hexdigest(),
        "rescore_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    source = args.results.resolve()
    output = (args.out or source.with_name(source.stem + "-rescored.json")).resolve()
    if output == source:
        parser.error("The original result must not be overwritten; choose a distinct output.")
    raw = source.read_bytes()
    result = rescore(json.loads(raw))
    result["offline_rescore"].update(
        source_result=str(source), source_sha256=hashlib.sha256(raw).hexdigest(),
        source_assets_directory=str(source.with_name(source.stem + "-assets")),
    )
    # Exclusive creation prevents accidentally overwriting prior raw/rescored evidence.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    if source.read_bytes() != raw:
        raise RuntimeError("The source results changed while rescoring")
    print(f"Wrote {output}; raw {record_count(result['offline_rescore']['raw_summary'])}, "
          f"rescored {record_count(result['summary'])}")


def record_count(summary: dict) -> str:
    return f"{summary['cases_ok']}/{summary['cases']}"


if __name__ == "__main__":
    main()
