"""Run a frozen synthetic challenge arm through the real lead, as a data agent.

The same runner can target an extracted baseline vis_agent package or the working
runtime. No UI, corpus selection, prompt tuning, implicit retries or model changes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import random
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from evals.generalization.bank import HERE, load_bank
from evals.generalization.scoring import SCORER_VERSION, score_case, summarize

REPO = HERE.parents[1]
TEXT_MODEL = "openrouter:z-ai/glm-5.3"
REVIEWER_MODEL = "openrouter:google/gemma-4-31b-it:nitro"


def runtime_fingerprint(package: Path) -> dict:
    """Hash the actually imported runtime, including local renderer contracts."""
    allowed = {".py", ".md", ".json", ".js", ".mjs", ".cjs", ".ts", ".txt", ".toml", ".lark", ".yaml", ".yml"}
    files = {}
    for directory, subdirectories, names in os.walk(package):
        subdirectories[:] = sorted(name for name in subdirectories if name not in {"node_modules", "__pycache__", ".git", ".venv"})
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix in allowed:
                files[str(path.relative_to(package))] = hashlib.sha256(path.read_bytes()).hexdigest()
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"package_root": str(package.resolve()), "sha256": hashlib.sha256(canonical).hexdigest(), "files": files}


def evaluator_fingerprint() -> dict:
    """Freeze shared adapter/scoring dependencies, not just this new runner."""
    # Separate probe suites are not dependencies of this experiment. Keep their
    # independent construction from invalidating a frozen, running arm.
    roots = (HERE, REPO / "evals" / "lead", REPO / "evals" / "analyst", REPO / "evals" / "designer")
    files = {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
             for directory in roots for path in sorted(directory.rglob("*.py"))
             if "__pycache__" not in path.parts and "node_modules" not in path.parts}
    return {"sha256": hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "files": files}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def case_adapter(case: dict) -> dict:
    """Only request/CSV/brief enter the lead; expected contracts stay offline."""
    return {"name": case["id"], "heldout": True, "evaluation_mode": "blinded_synthetic_transfer",
            "filename": case["filename"], "csv_text": case["csv_text"], "brief": case["brief"],
            "caller_kind": "agent", "caller_identity": "independent-synthetic-eval-data-agent",
            "turns": [{"message": case["request"] + f"\n\nAttached CSV: [{case['filename']}](/datasets/{{dataset_id}}/profile)",
                       "tool": ["draw", "answer_question"], "outcome": "artifact", "max_seconds": 60}]}


def _select_runtime(root: Path | None) -> Path:
    if root is not None:
        root = root.resolve()
        if not (root / "vis_agent" / "__init__.py").is_file():
            raise ValueError("--runtime-root must contain the selected vis_agent package")
        if any(name == "vis_agent" or name.startswith("vis_agent.") for name in sys.modules):
            raise RuntimeError("Select runtime before any vis_agent import")
        sys.path.insert(0, str(root))
    package = importlib.import_module("vis_agent")
    actual = Path(package.__file__).resolve().parent
    if root is not None and actual != root / "vis_agent":
        raise RuntimeError(f"Selected runtime was shadowed: {actual}")
    return actual


async def evaluate(args) -> dict:
    # .env is read solely for credentials; named model settings are then pinned
    # in the process environment, never persisted back to the user's file.
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env", override=False)
    for key in ("MODEL", "PROFILER_MODEL", "ANALYST_MODEL", "DESIGNER_MODEL", "DESIGNER_FALLBACK_MODEL"):
        os.environ[f"PYDANTIC_AI_{key}"] = TEXT_MODEL
    os.environ["PYDANTIC_AI_REVIEWER_MODEL"] = REVIEWER_MODEL
    os.environ["PYDANTIC_AI_LEAD_REASONING_EFFORT"] = "low"
    os.environ.pop("PYDANTIC_AI_ADVISOR_MODEL", None)
    import logfire
    logfire.configure(send_to_logfire="if-token-present", service_name=f"vis-transfer24-{args.arm}",
                      data_dir=REPO / ".logfire", console=False)
    logfire.instrument_pydantic_ai(include_content=False, include_binary_content=False)
    package = _select_runtime(args.runtime_root)
    from evals.lead.run import run_case
    from vis_agent.providers import openrouter_team
    from vis_agent.requests.service import REQUEST_LIMIT, TOOL_LIMIT
    from vis_agent.requests.store import RequestStore
    from vis_agent.store import DatasetStore
    if (REQUEST_LIMIT, TOOL_LIMIT) != (18, 16):
        raise RuntimeError("Experiment requires the frozen shared 18-request / 16-tool budgets")
    bank, freeze = load_bank(args.bank_directory)
    cases = [case for case in bank["cases"] if not args.only or case["id"] in args.only]
    if args.only and len(cases) != len(set(args.only)):
        raise ValueError("Unknown or duplicate --only case identifier")
    random.Random(args.order_seed).shuffle(cases)
    before = runtime_fingerprint(package)
    evaluator_before = evaluator_fingerprint()
    if args.out.exists() and any(args.out.iterdir()):
        raise FileExistsError("Output directory must be empty; do not overwrite earlier attempts")
    args.out.mkdir(parents=True, exist_ok=True)
    scorer_paths = [HERE / name for name in ("run.py", "scoring.py", "bank.py")]
    manifest = {"arm": args.arm, "started_at": datetime.now(timezone.utc).isoformat(), "bank": freeze,
                "scorer_version": SCORER_VERSION, "scorer_files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in scorer_paths},
                "runtime": before, "case_order": [case["id"] for case in cases], "order_seed": args.order_seed,
                "evaluator": evaluator_before,
                "concurrency": args.concurrency, "turn_timeout_seconds": args.turn_timeout,
                "shared_request_limit": REQUEST_LIMIT, "shared_tool_limit": TOOL_LIMIT,
                "credentials_recorded": False, "provider_calls_authorized_by_user": True,
                "telemetry": {"service_name": f"vis-transfer24-{args.arm}",
                              "include_content": False, "include_binary_content": False},
                "synthetic_inputs_only": True, "model_settings": {}, "models": {},
                "scope": "One frozen arm; no retries or tuning after results. Image quality needs independent audit."}
    if not os.getenv("OPENROUTER_API_KEY"):
        raise ValueError("OPENROUTER_API_KEY is required for --run; --dry-run needs no credentials")
    records, scores = [], []
    semaphore = asyncio.Semaphore(args.concurrency)
    with tempfile.TemporaryDirectory(prefix="vis-transfer-team-") as temporary:
        store = DatasetStore(Path(temporary))
        team = openrouter_team(store, RequestStore(store))
        roles = {"lead": team.lead, "profiler": team.deps.profiler, "analyst": team.deps.analyst,
                 "designer": team.deps.designer, "designer_fallback": team.deps.designer_fallback,
                 "reviewer": team.deps.reviewer}
        for role, agent in roles.items():
            if agent is not None:
                manifest["models"][role] = agent.model if isinstance(agent.model, str) else agent.model.model_id
                manifest["model_settings"][role] = agent.model_settings
        _write_json(args.out / "manifest.json", manifest)

        async def one(case):
            async with semaphore:
                attempt = {"id": case["id"], "started_at": datetime.now(timezone.utc).isoformat(),
                           "source_csv_sha256": case["source_csv_sha256"], "status": "started"}
                _write_json(args.out / case["id"] / "attempt.json", attempt)
                try:
                    record = await run_case(case_adapter(case), team.lead, team.deps.profiler, team.deps.analyst,
                                            team.deps.designer, team.deps.designer_fallback, args.out,
                                            team.deps.reviewer, turn_timeout=args.turn_timeout)
                except Exception as exc:
                    record = {"name": case["id"], "evaluation_error": f"{type(exc).__name__}: {exc}", "turns": []}
                _write_json(args.out / case["id"] / "case.json", record)
                try:
                    score = score_case(case, record, args.out)
                except Exception as exc:
                    record["evaluation_error"] = f"Scoring failed: {type(exc).__name__}: {exc}"
                    score = score_case(case, {"evaluation_error": record["evaluation_error"]}, args.out)
                _write_json(args.out / case["id"] / "score.json", score)
                attempt.update(status="completed", finished_at=datetime.now(timezone.utc).isoformat(), error=score["error"])
                _write_json(args.out / case["id"] / "attempt.json", attempt)
                records.append(record)
                scores.append(score)
                print(json.dumps({"arm": args.arm, "completed": len(scores), "total": len(cases), "case": case["id"],
                                  "contract_pass": score["deterministic_contract_pass"], "seconds": score["seconds"], "error": score["error"]}), flush=True)
        await asyncio.gather(*(one(case) for case in cases))
    after = runtime_fingerprint(package)
    evaluator_after = evaluator_fingerprint()
    result = {"manifest": manifest, "finished_at": datetime.now(timezone.utc).isoformat(),
              "runtime_changed_during_run": before != after, "runtime_after": after,
              "evaluator_changed_during_run": evaluator_before != evaluator_after, "evaluator_after": evaluator_after,
              "summary": summarize(bank, scores), "scores": scores}
    _write_json(args.out / "result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", default="candidate")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--bank-directory", type=Path, default=HERE)
    parser.add_argument("--out", type=Path, default=HERE / "results-candidate")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--turn-timeout", type=float, default=120)
    parser.add_argument("--order-seed", type=int, default=1709)
    parser.add_argument("--only", action="append")
    parser.add_argument("--run", action="store_true", help="Explicitly enable paid provider calls; otherwise validate only")
    args = parser.parse_args()
    if args.concurrency < 1 or args.turn_timeout <= 0 or args.turn_timeout > 120:
        parser.error("concurrency must be positive and timeout in (0,120]")
    if not args.run:
        bank, freeze = load_bank(args.bank_directory)
        runtime = runtime_fingerprint(_select_runtime(args.runtime_root)) if args.runtime_root is not None else None
        print(json.dumps({"dry_run": True, "provider_calls": 0, "bank": freeze,
                          "maximum_model_requests_per_arm": len(bank["cases"]) * 18,
                          "maximum_paired_model_requests": len(bank["cases"]) * 36,
                          "runtime": {key: value for key, value in (runtime or {}).items() if key != "files"},
                          "evaluator_sha256": evaluator_fingerprint()["sha256"],
                          "synthetic_inputs_only": True}, indent=2))
        return
    result = asyncio.run(evaluate(args))
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    if result["runtime_changed_during_run"] or result["evaluator_changed_during_run"]:
        raise SystemExit("Runtime or evaluator changed during evaluation: arm is invalid")


if __name__ == "__main__":
    main()
