"""Recompute timing-only evidence from the saved Logfire MCP export; no API calls."""

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).with_name("2026-09-17-transfer24-logfire.json")


def timestamp(value):
    return datetime.fromisoformat(value)


def main():
    rows = json.loads(EVIDENCE.read_text())["rows"]
    assert len(rows) == len({(r["trace_id"], r["span_id"]) for r in rows})
    output = {"metadata_only": True, "provider_calls": 0, "arms": {}}
    for arm in ("baseline", "candidate"):
        directory = ROOT / "evals/generalization" / f"results-{arm}"
        result = json.loads((directory / "result.json").read_text())
        calls = [dict(r, seconds=(timestamp(r["end_timestamp"]) - timestamp(r["start_timestamp"])).total_seconds())
                 for r in rows if r["service_name"] == f"vis-transfer24-{arm}"]
        traces = defaultdict(list)
        for call in calls:
            traces[call["trace_id"]].append(call)
        matches = {}
        for score in result["scores"]:
            attempt = json.loads((directory / score["id"] / "attempt.json").read_text())
            start, end = timestamp(attempt["started_at"]), timestamp(attempt["finished_at"])
            found = [trace_id for trace_id, spans in traces.items()
                     if start <= min(timestamp(s["start_timestamp"]) for s in spans) <= end]
            assert len(found) == 1, (arm, score["id"], found)
            trace = found[0]
            spans = sorted(traces[trace], key=lambda s: s["start_timestamp"])
            assert all(timestamp(a["end_timestamp"]) <= timestamp(b["start_timestamp"])
                       for a, b in zip(spans, spans[1:])), "Do not sum overlapping model spans"
            matches[score["id"]] = {"trace_id": trace, "seconds": score["seconds"],
                                     "model_seconds": sum(s["seconds"] for s in spans),
                                     "model_attempts": len(spans)}
        roles = {}
        for role in sorted({c["agent"] for c in calls}):
            subset = [c for c in calls if c["agent"] == role]
            times = sorted(c["seconds"] for c in subset)
            roles[role] = {"model_attempts": len(subset), "seconds": sum(times),
                           "median_seconds": statistics.median(times),
                           "p95_nearest_rank_seconds": times[math.ceil(.95 * len(times)) - 1],
                           "max_seconds": max(times),
                           "missing_usage": sum(c["input_tokens"] is None for c in subset)}
        case_seconds = sum(s["seconds"] for s in result["scores"])
        model_seconds = sum(c["seconds"] for c in calls)
        output["arms"][arm] = {"trace_count": len(traces), "model_attempts": len(calls),
                                "framework_requests": sum(s["framework_requests"] or 0 for s in result["scores"]),
                                "case_seconds": case_seconds, "model_seconds": model_seconds,
                                "model_fraction": model_seconds / case_seconds,
                                "roles": roles, "cases": matches}
    output["limitations"] = [
        "Counts are observed nonoverlapping chat spans, not provider billing or internal endpoint retries.",
        "Model-span duration combines network, provider scheduling, and inference; these components are not separated.",
        "Parallel arms and briefly concurrent synthetic reviewer probes shared the provider; one trial cannot isolate routing/cache variance.",
        "Cancelled calls with absent usage remain attempts and timeouts; they are not discarded.",
    ]
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
