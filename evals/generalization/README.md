# Blinded synthetic transfer/challenge bank

`transfer24-v1` contains 24 newly authored synthetic tasks in six held-out
intent families. Each family has two goal contracts, each paired with a
meaning-preserving variant (renamed columns with explicit definitions, reordered
columns and rows). Eighteen pair assertions check semantic preservation and
goal-sensitive choices. Some goals legitimately permit the same chart type;
neither changed pixels nor changed chart type is a universal success criterion.

## Separation and provenance

- Runtime implementers receive the taxonomy and frozen bank hash, not individual
  requests, contracts, images or outcomes until runtime freeze.
- No old development CSV, screenshot or failed rollout is copied into this bank.
  The author read public data contracts and the existing run adapter, not old50
  cases or production instructions. These are independently constructed synthetic
  tasks, **not human-labelled gold**.
- All six families are held out from this round of prompt/code tuning; there is no
  training split in this bank. Assets are independent. Abstract capabilities may
  overlap previous tasks: calling the set provably disjoint from every prior
  corpus, or a population generalization estimate, would be unsupported.
- `freeze.json` hashes the exact bank bytes, canonical semantics and authoring
  code before either runtime is evaluated. Do not edit frozen inputs after seeing
  results. A discovered oracle defect needs a separately versioned correction,
  with original scores retained.
- Source bytes have per-case hashes. Synthetic equipment, materials and process
  observations are fictitious and are not claims about real organizations.

## What this evaluation establishes

Deterministic checks cover full persisted data, units in saved metadata,
executable type/bindings, measure selection, literal identifiers, requested sort,
no hidden limit, real retained PNG headers and a delivered final link. The
online review is retained but is **not** the correctness oracle. Complete source
observations are compared, never the lead's bounded preview.

Every first/repair PNG and config copied by the existing lead adapter is retained
beside the full case record (messages, tool attempts, request snapshots and
artifacts). `score.json` explicitly leaves visual quality unverified. An independent
audit must inspect images against the case rubric, including scale/units,
correspondence, goal relevance and display-size legibility. Prose semantics and
visual usability are not proved by source fidelity or successful rendering.

Runtime errors, cancellation and 120-second timeouts stay in the denominator.
Framework usage can omit a currently cancelled provider request; it is not called
a complete provider-attempt count. Each attempt is journaled before execution,
so an externally interrupted process leaves `status: started`, not a vanished
case. There are no automatic eval retries. The median/p95 retain censored timeout
durations and flag that censoring.

## Frozen-arm execution

Validate without credentials or network calls:

```bash
uv run python -m evals.generalization.run
uv run pytest -q tests/test_generalization_eval.py
```

From the repository working directory, select an extracted baseline package
explicitly. `--runtime-root` points to a directory containing `vis_agent/`:

```bash
uv run python -m evals.generalization.run --run --arm baseline \
  --runtime-root /private/tmp/vis-generalization-baseline.3SEChZ \
  --out evals/generalization/results-baseline --concurrency 1

uv run python -m evals.generalization.run --run --arm candidate \
  --runtime-root /Users/muhammad/Documents/NACI/pydantic-vis-harness \
  --out evals/generalization/results-candidate --concurrency 1
```

The selected `vis_agent` package is imported before the shared `evals.lead.run`
adapter. Its actual files are fingerprinted, rather than assuming that the
repository's current code is the imported runtime. A mid-run runtime change
invalidates the arm. Output directories must be fresh; earlier attempts are not
overwritten. The same runner/scorer hash must appear in both arms.

Both arms pin all text roles (including fallback) to `z-ai/glm-5.3`, low
reasoning; visual inspection uses `google/gemma-4-31b-it:nitro` with the
runtime's thinking-disabled settings. All actual model IDs/settings are captured.
Environment overrides exist only in the process. The shared limits are 18 model
requests and 16 tool calls; watchdog 120 seconds, reporting SLA 60 seconds.

One serial process per arm can run concurrently for total case concurrency two,
using the same deterministic shuffled case order. Record provider contention as
a limitation; this is a paired engineering comparison, not a stable-provider
latency benchmark. Two full arms have at most 864 framework model requests
(432 each), excluding any provider-level retries/cancelled in-flight requests.
Launch only after coordination and authorization for the external model calls.

## Interpreting changes

Report per-family and per-pair results and all failures, not only one aggregate.
Do not tune on this bank after the reveal and then call a rerun a held-out test.
If a new failure informs a later implementation, promote it to regression and
author a new hidden family bank for the next assessment. One run per case cannot
establish stochastic reliability; future repetitions must be preregistered, keep
the same denominator and preserve every attempt.
