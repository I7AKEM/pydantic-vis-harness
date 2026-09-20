# GLM versus Claude: fifty-case continuation protocol

The user explicitly approved GLM/Claude OpenRouter experiments, then increased
the requested size while the first twenty cases per arm were running. Those
twenty are retained unchanged as segment one. Segment two adds thirty distinct
CSV handoffs, identically for both arms. There are no substitutions, dropped
failures, or retries out of the denominator. These are development cases,
not an unseen/held-out generalization benchmark.

## Fixed treatment

- Both arms: GLM 5.3 lead/profiler/analyst; production lead instructions;
  Gemma 4 31B Nitro visual inspector; existing provider routing and resource limits.
- GLM arm: GLM 5.3 designer and fallback.
- Claude arm: Claude Sonnet 4.5 designer and fallback.
- Model-specific factory settings stay unchanged (GLM low reasoning;
  Claude designer thinking off; both temperature zero).
- Concurrency one per arm; arms run concurrently. Per-case watchdog 120 seconds,
  success SLA 60 seconds. Slow publication/final-answer turns count toward latency.
- No app, prompt, evaluator, provider/default, or environment-file edits during
  either segment. The new input-builder/tests/reports do not modify the evaluator.

Application: `096451ded74efcdae3058d3a635924fbc66b41c4796c978706078037f91755a6`.
Evaluator: `5914d8a0037305557f9a822879261902b4c00172c58289717cdf62478c848403`.
Production lead prompt: `f8b393a809120ba5a8fbb41be12e7d9577fc6c8da1b5be37afdd0212f8d25efd`.
Initial twenty: `8541cb0af6a7f19a8acde058cef7f785e00f16799f45d0cee1492d6102eeb477`.
Supplement thirty: `eaa0510a99c6ba5cca3e76ee1b4dde58de766c558b982cfd0557fe1421f624f7`.

## Supplement selection and acceptance

`prepare_supplement30.py` reuses the existing coverage-first corpus selector,
then its seeded shuffle (20260917). Model outcomes are not inputs to selection.
Existing twenty IDs, duplicate canonical tables, and individual-record identifier
datasets are excluded before selection. Source files are unchanged. Selection,
source CSV hashes, exact briefs, and expectation hashes are frozen in
`supplement30-v3-manifest.json` and `supplement30-v3-cases.json` before segment-two calls.

Coverage includes seven single-row results, temporal series, negative growth,
nulls, long Arabic categories, multiple measures/units, unknown codes, and six
row-count buckets. Units are supplied only for unambiguous percentage-named
fields; no invented codebook, currency or denominator. This deliberately tests
prepared-data presentation, not the unrelated original research question.

The supplement contains **28 requested rendered presentations and two technical
boundary cases**: a 22,208-row source exceeding the existing 10,000-row direct
limit, and 1,000 categorical app-name rows that must stay a complete source table
rather than be silently counted, sampled or forced into a static PNG. The latter
must preserve all available source rows. Across both segments the denominator
is fifty tasks, including **48 rendered presentations and two boundary tasks**;
successful boundary handling is never reported as a verified chart.

## Scroll and independent visual review

Clipping at a working scrollable table's viewport is not inherently wrong.
We distinguish true meaning-bearing glyph/label clipping, static-PNG coverage,
and complete accessible HTML/source-table delivery. A screenshot of a scrollbar
is not itself interactive. Existing first-segment scores are preserved; manual
findings document these distinctions rather than retroactively changing gates.

The frozen automated score is not sole ground truth. Known reviewer false
positives, contradictory findings, numerical-checker false positives, nonnumeric
unsupported claims, and real visual defects are audited separately from raw
scores. Any later evaluator correction must retain the raw JSON and produce a
separately documented rescore. No result-dependent runtime repair occurs within
this comparison. Model request totals mean completed framework usage; timed-out
in-flight calls may require a separate attempted-call count from saved evidence.

Segment-one files: `results-parallel20-{glm,claude}-production-v3.json`.
Segment-two files: `results-supplement30-{glm,claude}-production-v3.json`.
Each keeps its own adjacent images/checkpoints; a combined summary must retain
both source-run identities and verify their shared hashes before combining.
