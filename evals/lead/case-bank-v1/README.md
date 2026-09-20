# Reusable development cases: runtime regressions and DSPy inputs

This freezes the **50 unique CSV handoffs**, not 100 independent examples from
two model arms. It does not run models or change production. Forty saved runs
cover the initial 20 cases (GLM and Claude); the supplementary 30 are still
unexecuted. There are 48 requested rendered presentations and two honest
technical-boundary outcomes, not 50 verified charts.

## What is reusable

- `cases.json`: exact initial20 + supplement30 inputs, briefs, and acceptance
  gates. Compatible with `evals.lead.run --cases`; the two segment hashes are
  preserved. Source CSVs are referenced locally, not copied or uploaded.
- `manifest.json`: CSV hashes, canonical-table groups, frozen splits, raw-run
  hashes, per-case checkpoints, PNG references, and original failed gates.
- `findings.json`: ten documented issues across twelve regression cases. Each
  has an owner, an observation, desired acceptance criteria, and evidence links.
  These are agent-audited diagnostics, not human-adjudicated gold answers and
  not proof that a fix has shipped.
- `evals.lead.case_bank.dspy_examples`: actual `dspy.Example` objects with only
  CSV reference, brief, caller context and messages marked as program inputs.
  Acceptance contracts and diagnostic metadata do **not** enter task inputs.

The JSON snapshot intentionally retains original raw gates, even where their
limitations are known. It is a reproducible regression/discovery suite, not a
new corrected scorer. Never use `raw_failed_gates` as teacher labels. In
particular, `count_under_30` caused a numerical-checker false rejection, while
unsupported F/M meanings passed the numerical checker. Both need separately
tested semantic/evaluator work before these scores can be an optimization reward.

## Local use: no credentials and no model calls

```bash
uv run python -m evals.lead.case_bank --check-sources --check-evidence
```

The check validates all 50 local CSV hashes, raw-result hashes, case/image
associations and evidence paths. Inputs retain the existing development corpus's
absolute CSV paths. Moving the corpus requires an explicit versioned/revalidated
path update; missing evidence fails rather than silently dropping cases.

```python
from evals.lead.case_bank import load_bank, select_cases, dspy_examples

bank = load_bank()
regressions = select_cases(bank, "regression")  # 12 original runtime cases
trainset = dspy_examples("train")              # 35 source groups
valset = dspy_examples("validation")           # 15 different source groups
assert list(trainset[0].inputs().keys()) == ["case_input"]
```

The current runtime runner can consume `cases.json` unchanged when model/data
permissions are in place. No new runner, automatic repair loop, or production
DSPy dependency path is introduced. Loading this bank does not authorize sending
its CSV contents, reference rows or images to any external model.

## Split and promotion rules

Groups are canonical-table fingerprints, sorted by SHA256 of seed `20260917`
and group ID. The first 35 groups are train, the other 15 validation. Both arms
and repeated copies of one source always share membership; byte-identical files
cannot cross the split either. Membership is persisted, not randomized per run.
This prevents exact-source leakage, **not** every possible related-query or
source-family correlation; these are all previously selected development data.

There is deliberately **no blind held-out set**. After tuning, use fresh source
families for final verification. The whole 50 may still be run as a known
regression/discovery benchmark, but its score is no longer an unseen test score.
The GLM/Claude study retains its unchanged 20+30 segment definitions, but the
user has stopped prioritizing that comparison. It remains incomplete; do not
append new-harness results to its old20 and call that a homogeneous50-case run.
These tuning splits neither alter the retained study nor assert tuning has run.

Do not turn every failed trajectory into a few-shot demonstration. Preserve it
as a negative regression with the desired behavior. Only independently checked
successful behavior is a candidate positive demonstration. A reviewer's verdict,
or a chart that looks good but never reached the user, is not sufficient.

## Where DSPy fits (and where it does not)

The repository already used DSPy offline:

1. `evals/lead/optimize_instructions.py` optimizes a **first-action proxy** with
   the old action/state vocabulary. Its historical improvement did not evaluate
   today's render/review/repair/delivery trajectory.
2. `evals/designer/agent/optimize_instructions.py` optimizes single-shot design.
   The historical proxy score improved, but the real runner did not improve;
   that designer prompt was not adopted (see `docs/phase-4b-lessons.md`).
3. The latest production-v3 GLM/Claude comparison did **not** run DSPy optimization.

`evals/lead/optimize_runtime.py` now provides a separate full-runtime bridge:
native GEPA's adapter API evaluates the real Pydantic AI tools through final
delivery; actual DSPy examples and a DSPy signature provide offline instruction
proposals. The old `message,state`/`prompt` proxy signatures are not used.
Local tests exercise GEPA search and budget termination with fake models, and
the real tools produce and deliver an actual PNG. No external optimization,
fine-tuning, prompt adoption, or new real-model50-case run has occurred.

```bash
uv run --group optimize python -m evals.lead.optimize_runtime check
```

The check reports **readiness blockers**, not a success certificate. Paid
optimization currently refuses to start:28 rendered cases lack audited
chart-selection contracts, binding/semantic acceptance needs further audit,
and the online inspector has known false verdicts. Its pass cannot serve as
independent visual truth. The baseline mode can collect diagnostic evidence
after explicit model/data permission, but calls its outcome `contract_pass`,
not verified chart quality. The semantic overlay is versioned separately in
`runtime-contracts-v1.json`; frozen task inputs/results remain unchanged.

Prioritize proven harness fixes and reliable acceptance criteria, then improve
one scoped agent prompt only when the reward is trustworthy. Keep correctness,
delivery, request count and end-to-end latency separate; a search reward is
not a pass rate. Candidates are never automatically adopted. Natural-language
feedback cannot repair renderer code or a broken metric by rewriting a prompt.
Pydantic AI remains the runtime; no optimizer runs on the request path.

See [current implementation and limits](../../../docs/experiments/2026-09-17-runtime-maturity.md)
and [selection metric audit](../../../docs/experiments/2026-09-17-selection-metric-audit.md).

For tables, a functioning scrollable viewport may legitimately crop the visible
window when the entire content remains accessible. Static PNG coverage, actual
glyph clipping, and complete accessible HTML/source data are different checks.
Neither a scrollbar screenshot nor a reviewer's assertion proves interactivity.

## References

- [DSPy Example inputs versus labels](https://dspy.ai/api/primitives/Example/)
  defines the `with_inputs` separation used by this adapter.
- [DSPy GEPA](https://dspy.ai/api/optimizers/GEPA/overview/) supports scored textual
  feedback and separate train/validation data.
- [GEPA adapter API](https://gepa-ai.github.io/gepa/guides/adapters/) supports
  optimization of non-DSPy runtimes without replacing their orchestration.
- [OpenAI evaluation guidance](https://developers.openai.com/cookbook/examples/realtime_eval_guide#43-expand-from-production-failures)
  motivates separate regression, discovery and untouched hold-out evidence.
