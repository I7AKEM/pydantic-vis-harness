# Synthetic reviewer probe

This newly authored probe contains 12 rendered images: six clean and six proposed defective variants.
All PNGs were inspected before any model calls. One proposed defect (scatter-axis swapping) was excluded:
the pinned renderer relabelled its axes consistently, so it is not an unambiguous misleading chart.
The frozen evaluation denominator is **11: six clean, five defective**.

The labels come from synthetic construction plus an agent's visual inspection, **not human gold**.
This is a small capability probe, not a replacement for the full labelled reviewer set and not evidence
of broad reliability. No old user CSVs or hidden transfer cases are used.

The normal `review_chart` path receives each expected report/spec/brief and the same frozen PNG in both
runtime arms. Defects are made by changing renderer inputs, never by pixel editing. The renderer may
also repair or normalize an attempted corruption, which is why pre-model visual verification matters.

`fixtures/manifest.json` hashes every model input and PNG. `fixtures/audit.json` binds visual eligibility
to that manifest hash and records all exclusions before testing. Do not change either after calls begin.
The runner preserves completed partial results, provider response IDs, usage, retry feedback, timings,
runtime-source hashes and input/image hashes. Failed cases remain in the fixed denominator; no failed
trial is rerun implicitly. Verdict agreement alone does not prove the reviewer identified the real defect:
read and adjudicate its finding against the visible construction.

Verify inputs without network:

```bash
.venv/bin/python evals/generalization_reviewer/run.py \
  --runtime-root /path/to/frozen/runtime --output /tmp/unused-probe-output.json --verify-only
```

Run one authorized real-model arm:

```bash
.venv/bin/python evals/generalization_reviewer/run.py \
  --runtime-root /path/to/frozen/runtime \
  --output evals/generalization_reviewer/results/arm.json \
  --env-file .env \
  --contention-note "Two reviewer arms ran alongside the two GLM/Gemma transfer-evaluation arms."
```

The default model is `openrouter:google/gemma-4-31b-it:nitro`. Each arm is serial; running two arms in
parallel allows at most two extra simultaneous reviewer calls. The API key is read through the normal
environment and is never printed or stored in the report. No browser/UI workflow is used.
