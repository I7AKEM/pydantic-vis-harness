"""Fixed, audited versions of the seeded development twenty; never a held-out set.

`original` preserves the source questions, including unsupported/mismatched requests.
`handoff` explicitly changes intent to present the supplied table. It is a separate
experiment, not evidence that the original user request was answered correctly.
"""

import json
from pathlib import Path

from evals.designer.agent.corpus_tools.select import CORPUS, read_manifest


def cases(mode: str, corpus: Path = CORPUS) -> list[dict]:
    if mode not in {"original", "handoff", "renderable"}:
        raise ValueError("dev20 mode must be original, handoff, or renderable")
    gold = json.loads(Path(__file__).with_name("dev20-expectations.json").read_text())
    if mode == "renderable":
        # The unsupported original is retained in both original/handoff suites;
        # this explicitly different cohort contains twenty renderer-supported
        # source presentations, including two categorical rendered tables.
        gold = [entry for entry in gold if entry["id"] != "vizcsv-839d109a0db9ce25"]
        gold.append(json.loads(Path(__file__).with_name("dev20-additional.json").read_text()))
    manifest = {row["dataset_id"]: row for row in read_manifest(corpus / "manifest.jsonl")}
    result = []
    for entry in gold:
        row = manifest[entry["id"]]
        path = corpus / row["csv_path"]
        question = row["occurrences"][0]["question"]
        expectation = {**entry["handoff" if mode == "renderable" else mode]}
        disposition = expectation.setdefault("disposition", "chart")
        message = expectation.pop("message", question)
        rendered = disposition == "chart"
        turn = {
            "tool": "draw" if rendered else ["draw", "answer_question", "none"],
            "outcome": "artifact" if rendered else "handled",
            "strict_source": rendered,
            "require_delivery": rendered,
            "require_render_evidence": rendered,
            "review_required": rendered,
            "review_pass_required": rendered,
            "forbid_questions": True,
            "max_tool_calls": {"draw": 1, "design_visualization": 2, "render_visualization": 2,
                               "review_visualization": 2, "publish_visualization": 1},
            "max_seconds": 60,
            **expectation,
        }
        if rendered:
            turn["prepared_csv"] = True
        turn["message"] = message + "\n\nAttached CSV: [" + path.name + "](/datasets/{dataset_id}/profile)"
        case = {"name": "corpus-" + entry["id"], "csv": str(path), "turns": [turn],
                "evaluation_mode": mode, "audit": entry["audit"], "original_question": question}
        if mode in {"handoff", "renderable"}:
            # Exact column names are the only definitions available. No units, code
            # meanings, currency, national completeness, or inferred denominator.
            case["brief"] = {"producer_agent": "data-agent", "raw_question": message,
                             "caveats": ["The CSV is authoritative. Present supplied values without recomputing them."]}
            case["caller_kind"] = "agent"
            case["caller_identity"] = "eval-data-agent"
        result.append(case)
    return result
