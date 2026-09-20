"""DSPy reflection + GEPA against the real Pydantic AI tool/runtime evaluator.

Unlike the historical first-action proxy, each rollout runs through final delivery.
GEPA's supported adapter API bridges the non-DSPy runtime; DSPy supplies examples
and the instruction proposer. No prompt is automatically installed in production.
"""

import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from time import perf_counter

from evals.lead.case_bank import BANK, ROOT, digest, dspy_examples, load_bank, summary

CONTRACTS = Path(__file__).with_name("runtime-contracts-v1.json")


class BudgetExhausted(RuntimeError):
    """Hard external-work limit; never turn skipped tasks into evaluated failures."""


def load_examples(split: str, directory: Path = BANK) -> list:
    examples = dspy_examples(split, directory)
    overlays = json.loads(CONTRACTS.read_text(encoding="utf-8"))
    if overlays["version"] != 1:
        raise ValueError("Unsupported runtime contract version")
    for example in examples:
        overlay = overlays["cases"].get(example.case_id, {})
        for expectation in example.expectations:
            expectation.update(deepcopy(overlay))
    return examples


def runtime_case(example) -> dict:
    """Acceptance criteria go to the scorer, not to the model's task inputs."""
    inputs = deepcopy(example.case_input)
    messages = inputs.pop("messages")
    if len(messages) != len(example.expectations) or not messages:
        raise ValueError("Every message requires an explicit acceptance contract")
    return {"name": example.case_id, **inputs,
            "turns": [{**deepcopy(expected), "message": message}
                      for message, expected in zip(messages, example.expectations, strict=True)]}


def optimization_blockers(examples: list) -> list[str]:
    """Machine-contract success is not independently verified chart quality."""
    blockers = []
    rendered = [expected for example in examples for expected in example.expectations
                if expected.get("require_render_evidence")]
    missing_choices = sum(not expected.get("charts") for expected in rendered)
    if missing_choices:
        blockers.append(f"{missing_choices} rendered tasks have no audited chart-choice contract.")
    readiness = json.loads(CONTRACTS.read_text(encoding="utf-8")).get("optimization_readiness", {})
    if readiness.get("selection_and_semantic_contracts_audited") is not True:
        blockers.append("Chart bindings and semantic acceptance contracts need an independent audit.")
    if readiness.get("visual_quality_metric_validated") is not True:
        blockers.append("The online inspector has known false verdicts; its pass is not a validated quality reward.")
    return blockers


def score_record(record: dict, case: dict) -> dict:
    from evals.lead.run import turn_diagnostics, turn_passes

    turns = record.get("turns", [])
    complete = len(turns) == len(case["turns"]) and bool(turns)
    quality = complete and not any(record.get(k) for k in ("error", "evaluation_error", "records_error"))
    strict = quality
    diagnostics = []
    if not complete:
        diagnostics.append("incomplete_conversation")
    for turn, expected in zip(turns, case["turns"]):
        quality = quality and turn_passes(turn, expected=expected, include_latency=False)
        strict = strict and turn_passes(turn, expected=expected)
        diagnostics.extend(turn_diagnostics(turn, expected=expected))
    for key in ("error", "evaluation_error", "records_error"):
        if record.get(key):
            diagnostics.append(f"{key}: {record[key]}")
    # Speed cannot compensate for a quality/delivery failure. This search reward
    # is not a pass percentage; the binary strict flag is reported separately.
    def measurements(key):
        values = [turn.get(key) for turn in turns]
        known = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)
                 and math.isfinite(v) and v >= 0]
        missing = len(values) - len(known)
        return (sum(known) if values and not missing else None), missing
    seconds, missing_time = measurements("seconds")
    requests, missing_requests = measurements("requests_used")
    return {"score": 1.0 if strict else 0.5 if quality else 0.0,
            "contract_pass": bool(quality), "strict_pass": bool(strict),
            "diagnostics": diagnostics,
            "seconds": seconds, "requests": requests,
            "unmeasured_turns": missing_time, "unknown_request_turns": missing_requests,
            "execution_seconds": record.get("execution_seconds")}


def _bounded_text(value: object, limit: int = 3000) -> str:
    text = str(value or "")
    text = re.sub(r"data:image/[^\s)]+", "[image omitted]", text)
    # Source geometry is not suitable context for either the runtime or reflection.
    text = re.sub(r"\b(?:MULTI)?(?:POLYGON|LINESTRING|POINT)\s*(?:Z\s*)?\(.*", "[geometry omitted]", text,
                  flags=re.I | re.S)
    return text[:limit]


def configured_team(store, requests, instructions):
    from vis_agent.providers import teams_from_env
    return teams_from_env(store, requests, lead_instructions=instructions)[0]


def optimization_fingerprint() -> str:
    """Extend, never redefine, the hash used by historical runtime experiments."""
    from evals.lead.run import runtime_fingerprint
    files = [Path(__file__), Path(__file__).with_name("case_bank.py"), CONTRACTS,
             *(BANK / name for name in ("cases.json", "manifest.json", "findings.json"))]
    return digest({"runtime": runtime_fingerprint(), "optimization_files": {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}})


class RuntimeAdapter:
    """Serial, bounded offline rollouts; the lead still chooses all runtime tools."""

    # GEPA checks this optional protocol member before its custom proposer.
    propose_new_texts = None

    def __init__(self, out: Path, *, max_rollouts: int = 60, turn_timeout: float = 120,
                 team_factory=configured_team, runner=None):
        if max_rollouts < 1 or not math.isfinite(turn_timeout) or turn_timeout <= 0:
            raise ValueError("Positive rollout budget and finite timeout required")
        from evals.lead.run import run_case
        self.out = Path(out)
        self.max_rollouts, self.turn_timeout = max_rollouts, turn_timeout
        self.team_factory, self.runner = team_factory, runner or run_case
        self.calls = 0
        self.fingerprint = optimization_fingerprint()
        self.out.mkdir(parents=True, exist_ok=False)

    def evaluate(self, batch: list, candidate: dict[str, str], capture_traces: bool = False):
        from gepa.core.adapter import EvaluationBatch
        if set(candidate) != {"lead"} or not isinstance(candidate["lead"], str) or not candidate["lead"].strip():
            raise ValueError("Only one nonempty lead instruction component is supported")
        if self.calls + len(batch) > self.max_rollouts:
            raise BudgetExhausted("Not starting a batch that would exceed the hard rollout budget")
        if optimization_fingerprint() != self.fingerprint:
            raise RuntimeError("Application/evaluator/contracts changed during the optimization")
        outputs = asyncio.run(self._evaluate(batch, candidate))
        if optimization_fingerprint() != self.fingerprint:
            raise RuntimeError("Application/evaluator/contracts changed during the optimization")
        return EvaluationBatch(outputs=outputs, scores=[o["score"] for o in outputs],
                               trajectories=deepcopy(outputs) if capture_traces else None,
                               num_metric_calls=len(outputs))

    async def _evaluate(self, batch, candidate):
        from evals.lead.run import code_fingerprint, code_paths, failed_score, save_checkpoint
        from vis_agent.requests.store import RequestStore
        from vis_agent.store import DatasetStore

        outputs = []
        with tempfile.TemporaryDirectory(prefix="vis-runtime-opt-team-") as directory:
            store = DatasetStore(Path(directory))
            team = self.team_factory(store, RequestStore(store), candidate["lead"])
            agents = {"lead": team.lead, **{role: getattr(team.deps, role, None)
                      for role in ("profiler", "analyst", "designer", "designer_fallback", "reviewer")}}
            models = {role: agent.model if isinstance(agent.model, str) else agent.model.model_id
                      for role, agent in agents.items() if agent is not None and agent.model is not None}
            app, evaluator = code_paths()
            configuration = {"models": models, "provider": team.label, "concurrency": 1,
                             "model_settings": {role: {k: v for k, v in (agent.model_settings or {}).items()
                                 if k in {"openrouter_reasoning", "openrouter_provider", "temperature",
                                          "thinking", "max_tokens", "timeout"}}
                                 for role, agent in agents.items() if agent is not None},
                             "turn_timeout_seconds": self.turn_timeout,
                             "application_code_sha256": code_fingerprint(app),
                             "evaluation_code_sha256": code_fingerprint(evaluator),
                             "lead_instructions_sha256": hashlib.sha256(candidate["lead"].encode()).hexdigest(),
                             "optimization_sha256": self.fingerprint,
                             "runtime_contracts_sha256": hashlib.sha256(CONTRACTS.read_bytes()).hexdigest()}
            for example in batch:
                case = runtime_case(example)
                source = Path(case["csv"])
                if hashlib.sha256(source.read_bytes()).hexdigest() != example.source["csv_sha256"]:
                    raise ValueError(f"Source CSV changed: {example.case_id}")
                self.calls += 1
                output_dir = self.out / f"rollout-{self.calls:04d}"
                output_dir.mkdir()
                (output_dir / "candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2))
                started = perf_counter()
                try:
                    record = await self.runner(case, team.lead, team.deps.profiler, team.deps.analyst,
                                               team.deps.designer, team.deps.designer_fallback,
                                               output_dir, team.deps.reviewer, turn_timeout=self.turn_timeout)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    record = {"name": case["name"], "evaluation_error": error,
                              "turns": [{**failed_score(error), "expected": turn, "reply": None}
                                        for turn in case["turns"]]}
                record["execution_seconds"] = perf_counter() - started
                record["run_configuration"] = {**configuration, "effective_contract_sha256": digest(case["turns"])}
                save_checkpoint(record, output_dir)
                result = {"case_id": example.case_id, **score_record(record, case),
                          "evidence": str(output_dir / case["name"] / "case.json"),
                          "inputs": {"messages": [_bounded_text(t["message"]) for t in case["turns"]]},
                          "generated": {"replies": [_bounded_text(t.get("reply")) for t in record["turns"]],
                                        "tool_names": [t.get("tools_called", []) for t in record["turns"]]}}
                (output_dir / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
                outputs.append(result)
        return outputs

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        if components_to_update != ["lead"] or set(candidate) != {"lead"}:
            raise ValueError("Reflection is scoped to the lead")
        if eval_batch.trajectories is None or len(eval_batch.trajectories) != len(eval_batch.outputs):
            raise ValueError("Reflection requires complete matching runtime trajectories")
        return {"lead": [{"Inputs": trace["inputs"], "Generated Outputs": trace["generated"],
                           "Feedback": {**{k: trace[k] for k in
                                           ("score", "contract_pass", "strict_pass", "seconds", "requests",
                                            "execution_seconds", "unmeasured_turns", "unknown_request_turns")},
                                        "diagnostics": [_bounded_text(d, 500) for d in trace["diagnostics"][:20]]}}
                          for trace in eval_batch.trajectories]}


def make_dspy_proposer(lm, *, max_reflections: int = 2, max_chars: int = 9000):
    """Actual DSPy signature, called only for offline instruction proposals."""
    import dspy
    if max_reflections < 1 or max_chars < 1:
        raise ValueError("Positive reflection and instruction limits required")

    class Reflect(dspy.Signature):
        """Improve the visualization lead instructions using full-runtime feedback.

        Keep the lead in charge; no mandatory workflow or automatic handoffs. Preserve
        source values, supported API use, final artifact delivery and framework limits.
        Do not invent code meanings, memorize case IDs/answers, weaken checks, or add
        proxy action/state JSON. Reviewer assertions are fallible, not ground truth.
        Improve the reusable instructions concisely, not a response to one case.
        """
        current_instructions: str = dspy.InputField()
        runtime_feedback: list[dict] = dspy.InputField()
        proposed_instructions: str = dspy.OutputField()

    predict = dspy.Predict(Reflect)
    calls = 0

    def propose(candidate, reflective_dataset, components_to_update):
        nonlocal calls
        if components_to_update != ["lead"] or set(candidate) != {"lead"}:
            raise ValueError("Reflection is scoped to the lead")
        if calls >= max_reflections:
            raise BudgetExhausted("Reflection proposal cap reached")
        calls += 1
        with dspy.context(lm=lm):
            result = predict(current_instructions=candidate["lead"], runtime_feedback=reflective_dataset["lead"])
        text = result.proposed_instructions.strip()
        if not text or len(text) > max_chars or re.search(r"(?:corpus-)?vizcsv-[0-9a-f]{16}", text):
            raise ValueError("Rejected empty, oversized or case-memorizing instruction proposal")
        return {"lead": text}

    # GEPA catches proposer exceptions and may otherwise keep evaluating parent
    # programs after the reflection budget is exhausted. Stop between iterations.
    propose.budget_exhausted = lambda _state: calls >= max_reflections or bool(
        getattr(lm, "request_budget_exhausted", False)
    )
    return propose


def reflection_lm(model: str, *, max_calls: int):
    """Count DSPy adapter fallback calls too, not only logical proposals."""
    import dspy

    class LimitedLM(dspy.LM):
        calls = 0

        @property
        def request_budget_exhausted(self):
            return self.calls >= max_calls

        def forward(self, *args, **kwargs):
            if self.calls >= max_calls:
                raise BudgetExhausted("Reflection LM request cap reached")
            self.calls += 1
            return super().forward(*args, **kwargs)

    if max_calls < 1:
        raise ValueError("Positive reflection model request cap required")
    return LimitedLM(f"openrouter/{model.removeprefix('openrouter:').removeprefix('openrouter/')}",
                     api_key=os.environ["OPENROUTER_API_KEY"], temperature=0.5,
                     max_tokens=6000, timeout=60, num_retries=0, cache=False)


def optimization_stopper(adapter, proposer, *, minibatch_size: int, validation_size: int):
    # Finish via GEPA's normal result path, retaining the best fully validated
    # candidate, instead of exhausting a budget halfway through its validation.
    next_iteration = 2 * minibatch_size + validation_size
    return lambda state: (proposer.budget_exhausted(state)
                          or adapter.max_rollouts - adapter.calls < next_iteration)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "baseline", "optimize"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--allow-external", action="store_true",
                        help="Operator acknowledgement only; actual model/data permission is still required")
    parser.add_argument("--max-rollouts", type=int, default=60)
    parser.add_argument("--max-reflections", type=int, default=2)
    parser.add_argument("--turn-timeout", type=float, default=120)
    parser.add_argument("--reflection-model", default="anthropic/claude-sonnet-4.5")
    args = parser.parse_args()
    bank = load_bank(verify_sources=True)
    train, validation = load_examples("train"), load_examples("validation")
    blockers = optimization_blockers(train + validation)
    if args.mode == "check":
        print(json.dumps({**summary(bank), "adapter": "real-runtime", "train": len(train),
                          "validation": len(validation), "optimization_blockers": blockers,
                          "contract_overlay": digest(json.loads(CONTRACTS.read_text()))},
                         ensure_ascii=False, indent=2))
        return
    if args.mode == "optimize" and blockers:
        parser.error("Optimization is not ready: " + " ".join(blockers))
    if not args.allow_external or args.out is None:
        parser.error("External runs require --allow-external and a new --out directory")
    if args.max_reflections < 1 or args.max_rollouts < (50 if args.mode == "baseline" else len(validation)):
        parser.error("Budget must cover the full initial baseline/validation; reflections must be positive")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from vis_agent.lead import LEAD_INSTRUCTIONS
    adapter = RuntimeAdapter(args.out, max_rollouts=args.max_rollouts, turn_timeout=args.turn_timeout)
    seed = {"lead": LEAD_INSTRUCTIONS}
    (args.out / "protocol.json").write_text(json.dumps({
        "mode": args.mode, "bank_sha256": bank["manifest"]["cases_sha256"],
        "splits": bank["manifest"]["splits"], "max_rollouts": args.max_rollouts,
        "max_reflections": args.max_reflections, "turn_timeout": args.turn_timeout,
        "reflection_model": args.reflection_model, "automatic_adoption": False,
        "optimization_sha256": adapter.fingerprint,
        "blind_holdout": False, "seed": seed,
    }, ensure_ascii=False, indent=2))
    try:
        if args.mode == "baseline":
            # Original bank order is retained, not train-then-validation order.
            by_name = {e.case_id: e for e in train + validation}
            batch = [by_name[c["name"]] for c in bank["cases"]]
            evaluated = adapter.evaluate(batch, seed)
            payload = {"cases": evaluated.outputs,
                       "strict_passes": sum(o["strict_pass"] for o in evaluated.outputs),
                       "contract_passes": sum(o["contract_pass"] for o in evaluated.outputs),
                       "quality_verified": False, "optimization_blockers": blockers}
        else:
            from gepa import optimize
            lm = reflection_lm(args.reflection_model, max_calls=args.max_reflections)
            proposer = make_dspy_proposer(lm, max_reflections=args.max_reflections)
            result = optimize(seed_candidate=seed, trainset=train, valset=validation, adapter=adapter,
                              custom_candidate_proposer=proposer,
                              stop_callbacks=optimization_stopper(adapter, proposer,
                                                                  minibatch_size=3, validation_size=len(validation)),
                              max_metric_calls=args.max_rollouts, reflection_minibatch_size=3,
                              use_merge=False, run_dir=str(args.out / "gepa"), seed=20260917,
                              raise_on_exception=True, track_best_outputs=True)
            payload = {"optimization": result.to_dict(), "candidate_not_adopted": result.best_candidate}
    except BudgetExhausted as exc:
        payload = {"status": "budget_exhausted", "reason": str(exc),
                   "candidate_not_adopted": None, "note": "All completed rollouts retained; no missing tasks scored."}
    (args.out / "result.json").write_text(json.dumps({**payload, "rollouts": adapter.calls}, ensure_ascii=False, indent=2))
    print(json.dumps({"out": str(args.out), "rollouts": adapter.calls, "automatic_adoption": False}))


if __name__ == "__main__":
    main()
