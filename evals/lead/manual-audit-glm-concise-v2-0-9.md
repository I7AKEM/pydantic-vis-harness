# Manual PNG audit: GLM concise v2, cases 0–9

All ten actual PNGs below were opened with `view_image`, compared with saved
complete rows, specs, required columns, and data-agent briefs. Current CSV
hashes match saved source hashes. This audits the original
`results-parallel20-glm-concise-v2-rescored.json`, not re-renders or new model
runs. Case 6 has no final PNG, so its last attempt was inspected. No network,
runtime, evaluator, source, or score changes were made.

| Index | Dataset suffix | Manual disposition | Existing complete-run disposition |
| --- | --- | --- | --- |
| 0 | 46dad75ae7fa7b62 | Pass | Pass |
| 1 | 6eff7ae46ebb4edf | Visually acceptable; exact amounts need config evidence | Fail: final review |
| 2 | 70ea08202f57d58f | Warning: correct 100, percentage unit not explicit | Pass; warning is not a rescore |
| 3 | 97280400c00748a7 | Pass | Pass |
| 4 | 3b62e4047e2cb455 | Pass | Pass |
| 5 | 2177430e3e44a9a3 | Pass | Pass |
| 6 | ba0187c944a3f829 | Fail: clipped attempt, no final PNG | Fail: fallback/delivery/review/render/columns/repetition |
| 7 | e07c573241abdb02 | Pass | Pass |
| 8 | 9e75e9ae40758227 | Pass visually | Fail: 66.17s exceeds 60s SLA |
| 9 | 85830f71807a6905 | Pass | Pass |

Eight images have no observed numeric/binding/clipping defect, one has a
unit-clarity warning, and one is a clipped failed attempt. This is **not eight
pipeline passes**: existing complete-run gates pass 7/10 of this subset.
No numeric corruption or invented source value was found.

## Per-case evidence

**0 — 46dad75ae7fa7b62.** [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/lead/results-parallel20-glm-concise-v2-assets/corpus-vizcsv-46dad75ae7fa7b62/renders/da7b5f119a0b/chart.png).
Shows **0%**, **2** returners, **370,783** postgraduates, matching
`[370783,2,0.0]`. Every required column and label fits. Description preserves
the source-rounded zero. No recomputation; 0 versus 0.0 is not a changed value.
High confidence.

**1 — 6eff7ae46ebb4edf.** [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/lead/results-parallel20-glm-concise-v2-assets/corpus-vizcsv-6eff7ae46ebb4edf/renders/37ce9557ef22/chart.png).
Complete near-equal donut slices; readable legend **blue = وافد**, **teal =
مواطن**. Final config correctly binds them to **375,161** and **373,877**.
`labels off` removes exact counts from the PNG; both occur in the final answer.
No ring/legend clipping or color mismatch. Legend order/RTL preference is not
a binding defect. High visual-layout confidence, limited pixel-only numeric
precision for unlabeled arcs. Recorded final-review failure remains a failure.

**2 — 70ea08202f57d58f.** [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/lead/results-parallel20-glm-concise-v2-assets/corpus-vizcsv-70ea08202f57d58f/renders/83ce535a3146/chart.png).
Shows **100**, matching `percentage_saudi=100.0`, without scaling or clipping.
Warning: **no % or explicit percentage unit** in the PNG; metadata has
`unit=null`. «النسبة السعودية» and the field name provide context, so this is
unit-clarity feedback, not a false conversion or newly imposed scoring failure.
High confidence in the omission, moderate confidence about practical ambiguity.

**3 — 97280400c00748a7.** [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/lead/results-parallel20-glm-concise-v2-assets/corpus-vizcsv-97280400c00748a7/renders/2205da5bea28/chart.png).
**Male count — 0** matches the sole source count. No invented female
denominator, ratio, percentage, or clipped text. English despite the Arabic
brief is a language-consistency note, not numeric corruption; no explicit
language gate applies here. High confidence.

**4 — 3b62e4047e2cb455.** [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/lead/results-parallel20-glm-concise-v2-assets/corpus-vizcsv-3b62e4047e2cb455/renders/48a96b712af7/chart.png).
**26.11%** exactly matches the prepared percentage without 100× scaling.
Complete label/description and explicit unit, no clipping. English is the same
consistency note as case 3, not a numeric failure. High confidence.

**5 — 2177430e3e44a9a3.** [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/lead/results-parallel20-glm-concise-v2-assets/corpus-vizcsv-2177430e3e44a9a3/renders/b61a85485871/chart.png).
All eight regions and 16 labels are legible. Blue F/orange M pairs are
49.79/50.21, 51.73/48.27, 51.83/48.17, 51.12/48.88, 49.71/50.29,
49.11/50.89, 48.31/51.69, 50.21/49.79, correctly mapped to source regions.
`Percentage (%)` gives the unit; F/M codes remain uninterpreted. Required
region/gender/percentage columns are visible; other source count columns are
not required in this comparison image. High confidence.

**6 — ba0187c944a3f829.** [Last attempted PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/lead/results-parallel20-glm-concise-v2-assets/corpus-vizcsv-ba0187c944a3f829/renders/c02bc2fd4062/chart.png).
No final PNG published. Attempt shows 13 full rows and part of row 14 plus a
nonfunctional scrollbar; **جدة، مكة المكرمة، نجران** are absent. It fails the
complete-17-row request. Headers actually match their data: swapped-header
review finding is false, but clipping is real. Complete HTML/answer rows do
not make the PNG complete. Later patched replay receives no retroactive
credit. Confirmed failure, high confidence.

**7 — e07c573241abdb02.** [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/lead/results-parallel20-glm-concise-v2-assets/corpus-vizcsv-e07c573241abdb02/renders/556d4fa63741/chart.png).
Arabic population card shows the supplied **0**, with complete label and
source-preservation description. No geometry-derived estimate or invented
number. WKT is explicitly out of scope, not a missing visible column.
High confidence.

**8 — 9e75e9ae40758227.** [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/lead/results-parallel20-glm-concise-v2-assets/corpus-vizcsv-9e75e9ae40758227/renders/4b5c61a48d34/chart.png).
All five ages/both series visible. Blue Saudi **863,556,492,461,378**, teal
Alien/non-Saudi **935,586,467,430,397** match all ten pairs. Count axis, legend,
ranges, and labels fit. LTR/RTL progression alone is not a binding defect.
Visually correct, high confidence; **66.17s still fails the 60s SLA**.

**9 — 85830f71807a6905.** [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/lead/results-parallel20-glm-concise-v2-assets/corpus-vizcsv-85830f71807a6905/renders/566963905a06/chart.png).
Complete small table: **المدينة** header, sole value **نجران**, matching
`city=نجران`. No invented count, percentage, or clipped row. High confidence.

## Limits

Manual image inspection is not a proof for other sizes/fonts/future runs.
Visible labeled values are stronger evidence than unlabeled donut arcs.
HTML/text alternatives were not accepted as proof of PNG completeness.
Language/unit-clarity notes remain separate from hard fidelity errors;
existing review/timing failures remain failures. Audited JSON SHA-256:
`1ed1cc5ff6509fa6b30127ee32fc38201b5b82d69b2f154e852f634711b14c2a`.
