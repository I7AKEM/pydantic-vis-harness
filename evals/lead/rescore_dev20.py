"""Offline rescore of stored original twenty runs under explicit visual-delivery gates.

This is a stricter acceptance standard, NOT a retroactive claim that every plain
question originally required a chart. Use the explicit handoff suite for that.
No model, network, credential, or runtime configuration changes are involved.
"""

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

from pydantic_ai.messages import ModelMessagesTypeAdapter

from evals.lead.dev20 import cases
from evals.lead.run import score_turn, source_signature
from vis_agent.analyst.source import load_csv_report
from vis_agent.store import DatasetStore


def rescore(path: Path) -> dict:
    expected = {case["name"]: case for case in cases("original")}
    record = json.loads(path.read_text())
    failure_counts = Counter()
    checked = []
    for case in record["cases"]:
        wanted = expected[case["name"]]
        old = case["turns"][0]
        turn = wanted["turns"][0]
        scored = score_turn(turn, ModelMessagesTypeAdapter.validate_python(old["messages"]), old.get("reply"))
        artifact = next((item for item in case.get("artifacts", [])
                         if item["artifact_id"] == scored.get("artifact_id")), {})
        if turn.get("strict_source"):
            with tempfile.TemporaryDirectory(prefix="vis-rescore-") as directory:
                store = DatasetStore(Path(directory))
                csv = Path(wanted["csv"])
                uploaded = store.save_upload(csv.name, csv.read_bytes())
                source = load_csv_report(store, uploaded.dataset_id, turn["message"])
                original = source_signature(source.result.columns, source.result.rows)
            table = (artifact.get("report") or {}).get("result") or {}
            scored["source_fidelity_ok"] = source_signature(table.get("columns", []), table.get("rows", [])) == original
            url = artifact.get("png_url") or ""
            root = (path.parent / (path.stem + "-assets") / case["name"]).resolve()
            png = root / url.lstrip("/")
            content = png.read_bytes() if url and png.resolve().is_relative_to(root) and png.is_file() else b""
            scored["render_evidence_ok"] = len(content) >= 24 and content.startswith(b"\x89PNG\r\n\x1a\n")
        scored["latency_ok"] = old.get("seconds", float("inf")) <= turn.get("max_seconds", float("inf"))
        failures = [key for key, value in scored.items() if key.endswith("_ok") and value is False]
        if old.get("error"):
            failures.append("runtime_error")
        failure_counts.update(failures)
        checked.append({"name": case["name"], "disposition": turn["disposition"],
                        "seconds": old.get("seconds"), "requests": (old.get("usage") or {}).get("requests"),
                        "png_url": artifact.get("png_url"),
                        "chart": ((artifact.get("design") or {}).get("chart")),
                        "passed": not failures, "failed_gates": failures})
    return {
        "source_result": str(path),
        "interpretation": "Conformance to stricter visual-delivery acceptance, not original-question accuracy. "
                          "Correct table/text answers to plain numeric questions can fail the new chart gate. "
                          "The source CSV is assumed unchanged where old results lack a source hash. "
                          "Automated inspector approval is not independent manual image verification.",
        "cases": len(checked), "passed": sum(case["passed"] for case in checked),
        "rendered_passed": sum(case["passed"] and case["disposition"] == "chart" for case in checked),
        "missing_usage": sum(case["requests"] is None for case in checked),
        "failure_counts": dict(failure_counts), "case_checks": checked,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args()
    print(json.dumps([rescore(path) for path in args.results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
