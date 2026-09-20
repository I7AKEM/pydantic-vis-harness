# Why false visual findings become unnecessary redesigns

## Conclusion

The saved evidence supports a failure chain, not the claim that every designer
output is bad or that a single model swap solves the harness:

**Correct first render → unsupported reviewer error → lead requests a repair →
text-only designer follows the alleged defect → extra work, false repair claims,
or lost delivery.**

There are also real design/configuration defects. They must be scored separately
from reviewer false alarms. Real50 completed all 50 cases with a frozen
configuration; this diagnosis changes documentation only. The independent audits
found 11 cases with false/overstrict reviewer errors and 7 with unnecessary
repair attempts. These are case-level agent judgments, not human gold or a
per-call model-accuracy estimate. See `2026-09-17-maturity50-real.md` for denominators,
uncertainties, genuine defects and latency results.

## Reproducible examples from Real50

Evidence root: `evals/lead/results-maturity50-glm-gemma-20260917-v1/`.
Each rollout retains `score.json`, its case checkpoint, and every rendered PNG.
The independent audit reports record image hashes and uncertainty. These are
agent visual judgments, not newly established human gold labels.

| Rollout / case | What the retained first image shows | What went wrong afterward |
|---|---|---|
| 0002 / `6eff7ae46ebb4edf` | Donut legend and slices agree: blue وافد 375,161, green مواطن 373,877. | Reviewer alleges swapped colours; lead requests a needless redesign; final prose claims a mapping error was repaired. |
| 0007 / `ba0187c944a3f829` | All 17 region/city rows are visible under the correct headers. | Reviewer alleges a swap based on column order, then alleges the contents are swapped. Repair PNG is byte-identical. Lead ultimately publishes no image and regroups the 17 source rows into eight textual rows while describing them as unchanged; city names are retained. |
| 0023 / `03384a96e9fe5870` | Complete, readable 51-row airport/destination table, faithful to the saved source. | Reviewer alleges extra Tunisia, Albania and Chad rows. Tunisia is real source row 31, outside its first-30-row reference excerpt; Albania and Chad appear in neither source nor image. A no-op redesign follows, and the final answer omits the image URL. |

Case23's deterministic reconstructed reviewer input has `rows_are_partial=true`,
`row_count=51`, and 30 reference rows. Its reconstruction is not a wire capture.
Thus a correct visible row absent from the excerpt was classified as an error;
partial context is a supported contributing hypothesis, not proof of the
model's internal reasoning or an isolated causal experiment. The two other
country names are unsupported visual assertions. Neither should
be generalized into an accusation that the designer fabricated rows.

Case21 provides a different cause: indicator `height 220` was accepted by the
design tool but rejected by the renderer's minimum280 constraint. The lead's
height-only correction succeeds. That is an executable preflight/contract gap,
not evidence of a reviewer hallucination.

Case25 is an important counterexample: the first dual-axis render actually drops
2016 because its growth measure is null, also reported as `dropped_rows=1` by the
renderer. The reviewer correctly identifies the omission; a complete ten-row
table repairs it. Do not disable defect detection or classify every repair as
waste merely because several other reviews are false alarms.

Rollout0046 (`a723f837bb1cd6a9`) demonstrates a different reviewer failure: its
summary says the table exactly matches the data, and its finding repeatedly
compares identical observed/expected numbers and concludes that all values
match. The same finding is nevertheless `level="error", owner="designer"`, so
the generated verdict is `revise`. The lead publishes the correct table without
a redesign. This is a directly visible structured-output inconsistency, not
proof that every reviewer objection compels the lead to run a repair.

## What the actual instructions and code do

1. **Scope restrictions exist, but do not establish perception accuracy.**
   `vis_agent/reviewer/rulebook.md:16` already forbids inferring a swapped mapping
   from RTL reading order. Line26 requires evidence and says uncertainty is not
   an error. The current failures violate those instructions; merely repeating
   the prohibition is not a demonstrated fix.
2. **The reviewer contract has conflicting and overly broad cues.**
   Rulebook lines19–24 and the `deliver_review` tool description still mention
   additional rule IDs and analyst/user ownership, although runtime validation
   permits only R-1…R-5 and designer/renderer/none: definite inconsistencies.
   R-3 covers the visible presentation explicitly requested by the question,
   and shared label instructions contain imperative localization work alongside
   a reviewer-specific comparison restriction. These are potential scope cues,
   not proof the prompt authorizes general critique. Their individual causal
   contribution is unmeasured.
3. **Reference context is incomplete and positionally encoded.**
   `vis_agent/reviewer/agent.py:75` supplies at most30 rows as arrays, alongside
   separate column metadata, with string cells cut to40 characters. The partial
   flag is present, but the model still treats unseen data as invalid in case23.
   The harness must not present a partial reference as proof of source-wide
   absence; no complete source values should be silently truncated or rewritten.
4. **A structured error is treated as grounds for repair, not independently
   established fact.** `deliver_review` validates rule/owner and derives
   `revise` from the model's `level="error"` (`reviewer/agent.py:54`). It does not
   verify the observation. `lead.py:62` tells the lead to repair such findings,
   and `material_design_review` makes them eligible. Code does not automatically
   invoke the designer: the lead remains in control. Its instructions nevertheless
   pressure it to treat the inspector's claim as grounds for repair.
5. **The designer is not an independent second visual witness.**
   `designer/agent.py:357` runs on JSON, not image bytes. The review rulebook calls
   findings “expert feedback”; revision instructions say to follow the latest
   change. They do allow disagreement, but a text-only designer cannot itself
   confirm whether a claimed clipped glyph or colour swap exists in the PNG.
   Claiming a visual fix is therefore stronger than its evidence supports.
6. **Repair limits bound cost; they do not make findings true.**
   The current no-op guard compares a hash of the spec plus serialized report,
   not PNG bytes. Existing no-op and one-repair guards bound redesign, but a spec
   change can produce a byte-identical image, and a false rejection can still
   consume the repair allowance or cause the lead to discard a useful preview.

### A separate designer/constraint-propagation example

Rollout0030 (`1240bc417714a3e6`) requests literal source codes with no invented
meanings. The lead abbreviates the question in `draw`, dropping that explicit
wording. The abbreviated `report.question` reaches the designer; `brief.raw_question`
does not. The designer nevertheless receives the caveat “no recomputation or
invented code meanings”, empty `code_meanings`, empty approved display mappings,
all five required columns and the supplied percent unit. It would therefore be
incorrect to say the designer receives no constraint at all.

The lead's `PreviousDesign.change` mentions `gender (M/F)` and Arabic headings,
but not literal preservation. The designer adds M→ذكور and F→إناث. The reviewer
receives the abbreviated question and that spec, but neither `raw_question` nor
`brief.caveats`. All16 rows are in its reference: this is not partial-row loss.
The review passes, and the lead endorses the expansion despite having the
original complete request.

`labels.py:14` allows translation of an established meaning from clear column
context; `designer/agent.py:207` explicitly demonstrates M→ذكور. These are plausible
cues toward conventional expansion, not a proven isolated cause. Approved
display mappings are merged as an overlay (`labels.py:68`), not enforced as an
allowlist, so model-created mappings remain when approved mappings are empty.
Unchanged CSV cells do not prove literal displayed-code fidelity.

This finding comes from saved inputs and deterministic prompt construction, not
a provider wire capture. Preserve explicit caller constraints across delegation;
do not broaden visual QA into an upstream semantic/codebook authority to patch
this gap.

## Latency is a separate axis

Logfire MCP trace `01a0acf10fe010a792ba9775eaa2a33a` links to rollout0041 via
lead run ID `01a0acf1-0fdf-7637-b817-0dc52ea32bc1`. The source-faithful table was
designed, rendered, reviewed and published once, with no repair. The turn still
hit its120s watchdog before returning a final answer.

The first two lead-model requests took27.826s and73.915s. The designer request
took3.024s, rendering0.620s and the reviewer request1.137s. Publication took0.037s;
the final model request occupied the remaining7.032s before cancellation. Most
of that case's delay therefore predates the design, not a reviewer loop or a
slow final paragraph. Model-request spans do not reveal how much was downstream
queueing, inference, transport or internal retries. Keep this independent of
perceptual quality and prompt-scope diagnosis.

## What the previous controlled experiment establishes

See `evals/reviewer/scope-fixed20-report.md`. On the same20 fixed PNGs, changing
only the reference rows from positional arrays to named objects improved Gemma
verdict agreement from12/20 to15/20. That is evidence that the input contract
matters, not only model choice. It is a small selected set, not a production
accuracy estimate.

Changing only the model in the named-input arm to Claude accepted all10 clean
images but passed5/10 defective ones; only4 of its5 rejections identified the
actual defect. The best aggregate arm, grounded Gemma with
low thinking, reached17/20 verdict agreement but correctly identified only4 of
the10 actual labelled defects. A reject verdict with a fabricated reason is not
a successful diagnosis. No tested configuration establishes a reliable sole
arbiter of chart correctness, and none of these experiments was silently adopted
as a production change.

## Proposed bounded remedy, not implemented by this diagnosis

- Keep executable source/binding/configuration checks in code. Give visual QA a
  narrow, explicit evidence contract: location, observed content, expected
  reference and reference coverage; distinguish unknown from wrong.
- Do not use absence from a partial excerpt to allege fabricated rows. Use named
  reference fields and make known/unknown coverage explicit without sending WKT
  or oversized cells into model context.
- Remove conflicting reviewer ownership/task-critique instructions. The designer
  should be able to return “finding not established” or “no supported change”
  without manufacturing a fix explanation. A structured finding alone still
  cannot prove perception correctness.
- Preserve the prior preview on an unproven/no-op repair and report unresolved
  review honestly. Compare rendered bytes as evidence of visual no-progress,
  without treating identical bytes as proof the original picture was correct.
- Re-test both clean images and genuine defects, scoring actual defect
  identification, source/role fidelity, delivery, avoidable repairs and latency
  separately. Do not optimize only reviewer agreement or final publish status.

No extra planner, automatic specialist loop, or runtime aesthetic policy engine
is needed. The lead should retain decision authority. Any code/prompt change
requires a new versioned run following this completed frozen baseline.
