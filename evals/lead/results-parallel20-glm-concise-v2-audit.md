# GLM concise v2: unchanged-run numeric rescore and image audit

This is the fixed `renderable20` **data-agent handoff** cohort, not a retrospective
rescore against the original questions. The saved run used GLM5.3 lead/designer,
Gemma4 31B image review, concurrency 1 and a 60-second per-case pass SLA.

## Evaluation correction only

- Raw evidence: `results-parallel20-glm-concise-v2.json`, **10/20** overall.
- Separate result: `results-parallel20-glm-concise-v2-rescored.json`, **16/20** overall.
- Raw SHA-256: `a0ea17073a5781bccb81a27a726307d21968ae93ee1051bc0d0a4a455808ee2b`.
- The raw result and its adjacent `-assets` directory were not changed. The
  rescore records that original asset directory explicitly; no images were moved.
- Only `answer_fidelity_ok` was recomputed, using complete persisted artifact rows.
  The summary was then recalculated. Original expected gates, case IDs, replies,
  messages, models, latency, source signatures, asset evidence and other gate
  results remain byte-equivalent after JSON parsing. No model was rerun.

The numeric checker removed Markdown link destinations but interpreted digits
inside bare render paths and URL-shaped link labels as claims about the data.
The fix excludes those URL tokens, while still checking ordinary visible numeric
link labels and values elsewhere in the answer. Regression tests retain rejection
of fabricated adjacent values and the real precision error described below.

Seven numeric gates change from false to true: `46dad75ae7fa7b62`,
`97280400c00748a7`, `3b62e4047e2cb455`, `e07c573241abdb02`,
`9e75e9ae40758227`, `ae315d3da67a2d11`, `8b3fd04765e40d3a`.
Only **six overall cases** become passing: `9e75e9ae40758227` still exceeds the
60-second SLA, so its corrected numerical score does not make the case pass.

All 20 source tables match their source signatures. Nineteen delivered rendered
artifacts; one delivered an explicitly labelled source-table fallback. Numeric
fidelity is now 19/20, final reviewer approval 18/20, and latency 19/20. Median
latency is 10.36s, p95 28.17s, maximum 66.17s; total model requests remain 181.
These deterministic gates do not independently certify all pixels in every image.

## Four remaining failures, with local image inspection

1. **Donut, `6eff7ae46ebb4edf`: reviewer gate remains failed.** First render
   `47b3b42836a9` genuinely clips its inside labels, even with valid `innerRadius
   0.6`. Repair `37ce9557ef22` hides the clipped labels and shows a legible legend.
   Gemma then rejects the correct blue=وافد/larger sector mapping because legend
   order differs from source-row order; its own finding states the blue category
   and larger value agree. This second rejection is a false mapping alarm, but
   the saved review failure has not been manually overwritten.
2. **Region/city table, `ba0187c944a3f829`: fallback and repetition failures remain.**
   Both `e708adfc20a4` and `c02bc2fd4062` visibly put region values beneath المنطقة
   and city values beneath المدينة. The swapped-header findings are false.
   However, both PNGs genuinely clip the final rows below a scroll viewport;
   at least the last three rows are absent from the static image. The reviewer
   missed this separate completeness problem. The final source-table fallback
   preserves all 17 rows but is not counted as a verified rendered table.
3. **Age groups, `9e75e9ae40758227`: latency remains failed at 66.17s.** Initial
   `9e6702815f09` maps every category to the correct numbers, with progression
   right-to-left. Gemma calls this wrong mapping while admitting the numbers
   match. Direction-only redesign to `4b5c61a48d34` takes 36.65s, versus 15.08s
   for initial design. The numeric URL correction does not remove this SLA miss.
4. **Gender percentages, `2571f37808cda8e2`: genuine answer error remains.** The
   chart `9f9b7c03580b` correctly displays 49.56% for M. The final answer instead
   gives **49.5571768707483%**, followed by correct **49.5578231292517%** in
   parentheses. The former is not a source value; the checker correctly fails it.

Reproduce the local-only rescore with a new, non-existing output filename:

```bash
.venv/bin/python -m evals.lead.rescore_answers \
  evals/lead/results-parallel20-glm-concise-v2.json \
  --out evals/lead/results-parallel20-glm-concise-v2-rescored.json
```

The utility refuses overwriting either the raw result or an existing output and
refuses missing/truncated persisted rows. The evaluator tests pass **103/103**.
Application hash remains `fe222dcea1e46f5287ec3986d8979570133f3de7ff2783f1e5d5b89f6ed7ebe3`;
the new evaluator hash is `5914d8a0037305557f9a822879261902b4c00172c58289717cdf62478c848403`.
