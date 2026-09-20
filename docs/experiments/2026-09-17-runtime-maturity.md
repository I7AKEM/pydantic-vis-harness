# Harness maturity: correct selection, efficient execution, honest evidence

The user's priority is the deployed agent's behavior, not winning a model
comparison. Preserve the existing model/environment defaults and improve
demonstrated harness defects first. This continuation made no external model
calls, changed no production model default, and adopted no optimized prompt.

## Implemented runtime fixes

1. **Label/legend enable switches preserve package defaults.** `labels on` no
   longer replaces existing placement, offsets or collision handling with a
   generic label definition; generic enabling remains for default-off marks.
   `legend on` retains existing layout. Explicit off still works. The exact
   retained donut spec/data was rendered again, both original switches still
   enabled, and the PNG was independently viewed: both outside labels are
   readable. Only resulting G2 labels/legend changed. See the
   [write-once replay and evidence](../../evals/lead/labels-on-probe/enabled-fix-v1/README.md).
2. **Supported repairs are not blocked by reviewer attribution.** An explicit
   designer- or renderer-owned error permits the same single presentation
   repair. Warnings do not authorize repair. No-progress detection, invalidation
   before external calls, shared usage limits, and the repair limit remain.
3. **Publication cannot reset this run's repair budget.** The publication run ID
   is persisted. `revise` rejects reopening an artifact just published in that
   same lead run; a later user turn can revise normally. Idempotent publication
   preserves its original marker. The lead still selects tools; no fixed runner,
   automatic specialist handoff or repair loop was added.

The one contradictory lead instruction about designer-only errors was corrected
to match the supported repair gate. This is not a learned prompt replacement.

## Reliable measurement before optimization

The numeric evaluator now ignores digits embedded in exact known column names
(e.g. `count_under_30`) without forgiving invented standalone values. An explicit
semantic contract catches unsupported F/M meanings in prose/specs while honoring
actual source definitions and approved labels. This is a narrow tested contract,
not a universal semantic truth detector.

New fail-closed helpers require the applicable case gates, final image delivery,
persisted source signature, matching PNG evidence, current review, substantive
reply and measured SLA. Unknown request/time measurements remain unknown rather
than becoming misleading zeros. Historical raw results are not overwritten.

**Machine-contract pass is not verified chart correctness.** The independent
[selection audit](2026-09-17-selection-metric-audit.md) found insufficient choice,
role and rendered-value checks. Reviewer false verdicts remain unresolved; a
bounded repair loop does not make those verdicts correct. No claim of improved
real-model choice accuracy or end-to-end latency is justified by local tests.

## DSPy integration and safety boundaries

`evals/lead/optimize_runtime.py` uses the supported native GEPA adapter interface
with actual DSPy examples and a DSPy proposer. Every evaluated task uses the
real Pydantic AI team through final delivery, including tools, failures, source
checks and saved PNGs. Candidate lead instructions are instance-local; capability
instructions and production globals are preserved. There is no optimizer on the
production request path.

All proposed instructions and completed rollouts are saved, with model/settings,
effective-contract, source and code hashes. A separate optimization fingerprint
includes the optimizer, case-bank adapter, overlays and splits without redefining
historical runtime fingerprints. Output paths are write-once. Budget exhaustion
does not count unexecuted cases as failures; failures that actually execute stay
in the record. Reflection receives bounded task/reply/diagnostic summaries, not
raw CSV files, images or old verdicts as gold answers.

GEPA catches proposer exceptions internally: just raising at the reflection cap
would still spend runtime rollouts. An explicit stop callback now stops after
the proposal/model-call cap and reserves enough budget for full next-candidate
validation. Tests use the actual installed engine and verify normal termination
retains the best validated candidate without adopting it.

External optimization is **blocked on purpose** until selection/semantic
contracts and the visual metric are validated. `check` reports these blockers
without network calls. Diagnostic `baseline` runs still require explicit
external model/data permission. The bank contains35 train/15 validation source
groups, no blind holdout; all50 are development cases, not unseen proof.

## Verification

- Final full local suite, including optimizer safety additions: **1898 passed**
  in141.03s (one existing Starlette/AnyIO deprecation warning).
- Final focused adapter/case-bank/metric/provider tests: **127 passed**.
- Deterministic designer evaluation: **40/40**.
- Real Pydantic AI tools + local Node renderer with fake models: actual PNG
  produced and linked in the final response. No manually constructed RunContext.
- Retained donut replay: real2400×1350 PNG independently inspected; original
  checkpoints/PNG/config hashes unchanged. This is render-only evidence, not a
  new model trial or an end-to-end latency benchmark.
- All50 CSV hashes and retained evidence associations verified;30 new cases
  remain unexecuted by real models. No50/50 chart-success claim.
- `git diff --check` passed. No raw evidence deletion, commits, `.env` edits or
  automatic production prompt adoption.

## Next acceptance work

1. Use the bank's explicit briefs to audit allowed representations and semantic
   roles, accepting multiple valid designs. Check direct render-value fidelity,
   not only unchanged saved source rows.
2. Calibrate the scoped visual inspector against image-hash-linked independent
   judgments, distinguishing scrollable table viewports from actual lost data
   and clipped glyphs. Keep first-render false rejections and unnecessary repairs
   visible as failures, not useful activity.
3. Once external data transfer is explicitly authorized, run the current
   production configuration against the regression/discovery cases. Measure
   choice accuracy, delivery, repair counts, model requests and p50/p95 latency
   separately. No renewed model-comparison experiment is required.
4. Only then consider offline prompt optimization. Promote a candidate only
   after non-regression on correctness and a measured execution benefit, plus
   fresh-source verification; never adopt it from its scalar reward alone.
