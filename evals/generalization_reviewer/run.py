"""Review a frozen synthetic probe with one selected runtime. Not a human-quality accuracy claim."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time


HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=HERE / "fixtures")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="openrouter:google/gemma-4-31b-it:nitro")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--contention-note", default="Latency may be affected by other experiments sharing the provider.")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = args.fixtures.resolve()
    manifest_path, audit_path = root / "manifest.json", root / "audit.json"
    manifest = json.loads(manifest_path.read_text())
    audit = json.loads(audit_path.read_text())
    if digest(manifest_path) != audit["manifest_sha256"]:
        raise SystemExit("Manifest changed after the visual audit.")
    eligible = []
    for entry in manifest["cases"]:
        for field, hash_field in [("case", "case_sha256"), ("image", "image_sha256")]:
            if digest(root / entry[field]) != entry[hash_field]:
                raise SystemExit(f"Frozen input changed: {entry['id']} {field}")
        if audit["cases"][entry["id"]]["eligible"]:
            eligible.append(entry)
    if not eligible:
        raise SystemExit("No visually verified eligible cases. Complete the pre-model audit first.")
    if args.verify_only:
        print(json.dumps({"eligible": len(eligible), "manifest_sha256": digest(manifest_path),
                          "audit_sha256": digest(audit_path)}))
        return
    if args.output.exists():
        raise SystemExit("Refusing to overwrite a previous evaluation output.")
    runtime = args.runtime_root.resolve()
    if not (runtime / "vis_agent" / "reviewer" / "agent.py").is_file():
        raise SystemExit("runtime-root must contain vis_agent/reviewer/agent.py.")
    sys.path.insert(0, str(runtime))
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    from vis_agent.analyst.models import AnalysisReport
    from vis_agent.designer.models import Design
    from vis_agent.models import DataBrief
    from vis_agent.reviewer.agent import create_reviewer, review_chart
    import vis_agent.reviewer.agent as runtime_reviewer
    from pydantic_ai import capture_run_messages
    from pydantic_ai.messages import ModelResponse, RetryPromptPart, ToolCallPart

    actual_runtime = Path(runtime_reviewer.__file__).resolve()
    if not actual_runtime.is_relative_to(runtime):
        raise SystemExit(f"Wrong runtime imported: {actual_runtime}")

    async def evaluate():
        reviewer = create_reviewer(args.model)
        results = []
        started = time.perf_counter()
        for entry in eligible:
            payload = json.loads((root / entry["case"]).read_text())
            reference = payload["reference"]
            began_at = datetime.now(timezone.utc).isoformat()
            with capture_run_messages() as messages:
                result = await review_chart(AnalysisReport.model_validate(reference["report"]),
                                            Design.model_validate(reference["design"]), root / entry["image"], reviewer,
                                            brief=DataBrief.model_validate(reference["brief"]))
            record = {"id": entry["id"], "expected": entry["proposed_label"],
                      "actual": result.review.verdict if result.review else "failed",
                      "case_sha256": entry["case_sha256"], "image_sha256": entry["image_sha256"],
                      "began_at": began_at, "completed_at": datetime.now(timezone.utc).isoformat(),
                      "review_report": result.model_dump(mode="json"),
                      "responses": [{"model_name": m.model_name, "timestamp": m.timestamp.isoformat(),
                                     "provider_name": m.provider_name, "provider_response_id": m.provider_response_id,
                                     "usage": asdict(m.usage), "state": getattr(m, "state", None),
                                     "tool_calls": [{"name": p.tool_name, "args": p.args} for p in m.parts
                                                    if isinstance(p, ToolCallPart)]}
                                    for m in messages if isinstance(m, ModelResponse)],
                      "retries": [{"tool_name": p.tool_name, "content": p.content, "timestamp": p.timestamp.isoformat()}
                                  for m in messages for p in m.parts if isinstance(p, RetryPromptPart)]}
            results.append(record)
            print(json.dumps({"id": record["id"], "expected": record["expected"], "actual": record["actual"],
                              "seconds": result.seconds, "requests": result.requests}), flush=True)
            # Preserve partial progress if a later process is interrupted. Never change the fixed denominator.
            output = {"model": args.model, "runtime_root": str(runtime), "reviewer_file_sha256": digest(actual_runtime),
                      "manifest_sha256": digest(manifest_path), "audit_sha256": digest(audit_path),
                      "runtime_reviewer_hashes": {p.name: digest(p) for p in sorted(actual_runtime.parent.glob("*"))
                                                  if p.is_file() and p.suffix in {".py", ".md"}},
                      "planned_cases": len(eligible), "completed_cases": len(results), "results": results,
                      "elapsed_seconds": time.perf_counter() - started,
                      "contention_note": args.contention_note,
                      "note": "Verdict agreement is not defect-identification accuracy; findings require independent adjudication."}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n")
        output["verdict_agreement"] = sum(r["actual"] == r["expected"] for r in results) / len(eligible)
        output["clean_passes"] = sum(r["expected"] == r["actual"] == "pass" for r in results)
        output["defect_revisions"] = sum(r["expected"] == r["actual"] == "revise" for r in results)
        output["uncertain"] = sum(r["actual"] == "uncertain" for r in results)
        output["failed"] = sum(r["actual"] == "failed" for r in results)
        output["median_seconds"] = statistics.median(r["review_report"]["seconds"] for r in results)
        output["model_requests"] = sum(r["review_report"]["requests"] for r in results)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n")

    asyncio.run(evaluate())


if __name__ == "__main__":
    main()
