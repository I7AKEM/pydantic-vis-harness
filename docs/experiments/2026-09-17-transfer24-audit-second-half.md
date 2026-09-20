# Transfer24: post-freeze visual audit, second half

Date: 2026-09-17. Scope: the final three families, 12 tasks × 2 arms, **all 25 retained first/repair PNGs inspected**.

## Conclusion

This audit does **not** support “all fixed” or “candidate is generally better.” Both arms pass the machine contract on 9/12 assigned tasks, but the candidate publishes one materially mislabeled boxplot after its reviewer fails to produce a usable response. The candidate also leaves a real time-order defect unrepaired at the 120-second deadline. Baseline has different problems: a pre-designer schema failure, false boxplot allegations, a self-retracting error, and missing final links.

There are genuine successes: both arms correctly choose and label all four opaque-ID ranking variants, preserving leading zeros and the requested measure/direction. Correct boxplots, independent mixed-unit cards, and complete tables are also present. These successes cannot establish universal reliability.

Auditor: the `generalize_reviewer` subagent, which authored candidate reviewer changes. This is **non-blind-to-implementation agent inspection**, not human gold or an independent blinded experiment. The auditor compared task/source/PNG/final reply independently of online verdicts. Hidden cases were read only after runtime freeze; no runtime edits or outcome-informed tuning were made. No external calls or exports were used for this audit.

[Complete per-case evidence, final replies, reviewer records, measurements and SHA-256 hashes](/Users/muhammad/Documents/NACI/pydantic-vis-harness/docs/experiments/2026-09-17-transfer24-audit-second-half.json).

## Observed metrics — this half only

| Metric | Baseline | Candidate |
|---|---:|---:|
| Assigned tasks | 12 | 12 |
| Retained PNGs inspected | 13 | 12 |
| Machine contract pass | 9/12 | 9/12 |
| Final reply includes usable render/artifact URL | 9/12 | 9/12 |
| Median wall-clock seconds, including failed turns | 24.81 | 36.16 |
| Turns ≤60s, including failed turns | 11/12 | 10/12 |
| Delivered URL and ≤60s, **not a quality pass** | 8/12 | 9/12 |
| Recorded framework requests | 109 | 100 |
| Cases with an unnecessary repair attempt | 2 | 0 |
| Known materially wrong **published** image | 0 | 1 |

The candidate's zero observed unnecessary repair attempts is **not** an accuracy gain by itself: one defective image received no usable review, and a real problem timed out before repair. Baseline's ellipsized exact-record header is a separate explicit-label requirement issue, not a corrupted numerical chart.

A single paired run cannot separate prompt/schema/model/provider effects. Both arms ran serially internally, concurrently with each other. Recorded framework requests are not guaranteed to include every provider-side attempt; inspect per-case completeness notes. Lower request count did not produce lower median latency here.

## Material evidence

### 1. Candidate publishes incorrect upper-whisker labels

Case `g04-sample_spreads-original`: [published first/only PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/generalization/results-candidate/g04-sample_spreads-original/renders/dafbb291cb7d/chart.png).

The boxplot geometry and batch associations match the source. The displayed labels do not:

| Batch | Label next to upper whisker | Actual upper whisker/source maximum |
|---|---:|---:|
| Mix Cedar | 5 MPa | 25 MPa |
| Mix Birch | 8 MPa | 21 MPa |
| Mix Maple | 3 MPa | 24 MPa |

Those label values are the respective **minima**, positioned at the upper end of each distribution. This is a directly visible mark/value contradiction, not a style preference.

The spec enables `labels on`; saved G2 config contains a generic `labels: [{text: "value", ...}]`. Raw source rows remain correct. The exact internal renderer cause was not isolated by this audit.

The inspector consumed **3 requests / 18.00s**, then failed because a cited source row was outside the supplied reference. Raw rejected model arguments are not retained, so their visual conclusions cannot be judged. The final reply honestly says there was no independent visual verification and provides the image/source links. Honesty about uncertainty is useful, but does not make the wrong image correct. **All machine-contract checks pass** because they do not inspect rendered label placement/value association.

### 2. True time-order error in both first renders, different recovery

Case `g04-curing_paths-transformed`: both first images connect elapsed times in source order **10, 30, 0, 20, 40**. Both inspectors correctly identify the chronology problem.

- Baseline: [first PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/generalization/results-baseline/g04-curing_paths-transformed/renders/6405acbb31e5/chart.png) → [correct repair](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/generalization/results-baseline/g04-curing_paths-transformed/renders/ac30306b3bdc/chart.png), now ordered 0, 10, 20, 30, 40 with all 15 source values preserved.
- Candidate: [first/last PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/generalization/results-candidate/g04-curing_paths-transformed/renders/dc25dd49b958/chart.png); a correct R-5 finding is saved, but no repair or final reply is delivered before the 120s deadline. Its review took 24.11s; this one pair cannot establish that review schema alone caused the timeout.

Baseline's second review is itself defective: an R-1 error narrative rechecks every value and concludes “All marks match the rows. No R-1 error,” while the stored verdict remains `revise`. The final image is correct; the persisted defect claim is not.

The scorer's `sort: null` does not validate semantic axis chronology. Also, an unpublished candidate score omits the completed inspector summary even though `request.steps.review` contains it. Absence of that score field does not mean the reviewer was never called.

### 3. Baseline invents boxplot association errors

Case `g04-sample_spreads-original`: [first PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/generalization/results-baseline/g04-sample_spreads-original/renders/8205712ef09c/chart.png) and [repair PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/generalization/results-baseline/g04-sample_spreads-original/renders/686ec0a04092/chart.png) have correct category-to-distribution associations.

Reviewer allegations of cyclic mispairing are not supported by either image/source. One allegation treats Cedar's top box edge, Q3=16, as its maximum despite the whisker visibly reaching 25. This triggers an unnecessary redesign/rerender, and the final reply passes false verification doubt to the user.

The designer also promises individual-point overlays in its prose without executable configuration for them. Missing overlays are not a caller defect: the request asks for a distribution display, not points. A reviewer should not elevate invented design prose over the actual user intent.

### 4. Baseline original trajectory fails before the designer runs

Case `g04-curing_paths-original`: no image. The lead supplies `elapsed_min` as `kind=time` with `unit=min`, which conflicts with the schema allowing units only for measure/share. The tool retry budget then ends; stored `design_attempts=0`.

This is a metadata/tool-contract interaction before designer execution, not a visual reviewer or chart-model failure. The second retry's complete diagnostic is not retained, so its specific cause is not inferred.

### 5. Table evidence requires context, not a blanket clipping rule

- Baseline `exact_record-original`: [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/generalization/results-baseline/g05-exact_record-original/renders/9f48a12cec41/chart.png) really shortens a header to “95th-percentile dela…”. The warning is real, and the brief explicitly forbids abbreviation. The final Markdown table supplies full wording and values; the image still has the limitation.
- Baseline `exact_record-transformed`: [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/generalization/results-baseline/g05-exact_record-transformed/renders/2ddac40aef1e/chart.png) shows full headers and correct units. Reviewer error about appending approved unit suffixes is unfounded: no unit conversion or value change occurred. A second design attempt returns the same result; only one image/review was actually generated. Final reply omits a render/artifact URL.
- Candidate `exact_record-original`: [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/generalization/results-candidate/g05-exact_record-original/renders/7be581a1c844/chart.png) shows all five values/units and complete configured headers. `P95 delay` is a conventional but literal abbreviation despite the request, a minor wording caveat rather than missing data or clipping. Final reply gives a complete Markdown row but only an artifact ID, no usable URL.
- Candidate `exact_record-transformed`: [PNG](/Users/muhammad/Documents/NACI/pydantic-vis-harness/evals/generalization/results-candidate/g05-exact_record-transformed/renders/de120696dfe4/chart.png) displays full meaning labels, all values/units, and the final reply links image and source table. No visible defect found.

Wide PNGs alone are not evidence of unusable scroll, clipping, or missing content. No browser, hover, tooltip or responsive layout was tested. Renderer “may shorten” warnings were treated as heuristics until confirmed in the image.

## All task outcomes

“Correct” below means no material visible source/intent mismatch found in the inspected PNG, not human certification.

| Task | Baseline first → final/delivery | Candidate first → final/delivery |
|---|---|---|
| Curing paths, original | No image; pre-designer tool failure | Correct; delivered |
| Curing paths, transformed | Wrong chronology → correct repair; delivered, contradictory final review | Wrong chronology; correct finding, no repair/final reply before timeout |
| Sample spreads, original | Correct → unnecessary repair; delivered with false doubt | Wrong value labels; reviewer unavailable; wrong image delivered |
| Sample spreads, transformed | Correct; final URL missing | Correct; delivered |
| Overview, original | Correct mixed-unit cards; delivered | Correct mixed-unit cards; delivered |
| Overview, transformed | Correct mixed-unit cards; delivered | Correct image; final URL missing |
| Exact record, original | Header ellipsis; complete Markdown supplement, image linked | Correct values, minor P95 abbreviation; final URL missing |
| Exact record, transformed | Correct; false unit complaint; final URL missing | Correct full labels/units; delivered |
| Demand rank, original | Correct rank, kW, leading-zero IDs; delivered | Correct; delivered |
| Demand rank, transformed | Correct rank, kW, leading-zero IDs; delivered | Correct; delivered |
| Efficiency rank, original | Correct low-energy-first rank, Wh/transaction, IDs; delivered | Correct; delivered |
| Efficiency rank, transformed | Correct low-energy-first rank, Wh/transaction, IDs; delivered | Correct; delivered |

In the ranking family, demand order is 0026, 0017, 0091, 0402, 0700; efficiency order is 0091, 0026, 0017, 0700, 0402. Both arms use the requested measure directly, without reciprocal transformations or identifier decoding.

Purpose-appropriate alternatives were accepted: line/series displays for trajectories, boxplots for distributions, independent cards for mixed units, and tables for an exact row. No failure was assigned for palette preference, redundant but interpretable legends, source column order, 185.0 versus 185, or approved unit suffixes.

## Oracle limitations and next decision

Machine checks verify source/config contracts and delivery, not perceptual truth. They can miss a wrong rendered value label, fail to check chronological interpretation, and assume a table column is visible without testing complete label text. Conversely, no artifact makes several checks false even when no source corruption occurred.

This challenge set has no human-gold labels and is not a probability sample of production. The inspection exposes mechanisms to investigate, not examples to memorize. Do not tune this frozen bank and present it as a fresh generalization test afterward.

Any claim of readiness needs the full audit, the approved legacy reviewer labelled-set gate, repeat independent cases, and isolated tests of generic changes. This audit contains no evidence that the full89 gate passed. The candidate's additional source-reference checks demonstrably can exhaust retries; eliminating unsupported accusations is valuable, but unreviewed defective output is not an acceptable substitute for a correct usable review.

## Reproducibility

SHA-256 was computed independently for the bank, scorer, protocol, all 24 case/score records, all 25 PNGs/configs, and current frozen reviewer files. Every retained PNG matches its score's declared hash.

- Bank: `2548d627feb492d200ca11bd33113121ee1d9467c15a1d474f09a850759b84a5`
- Scorer: `0865730bd4dc488af9f5785433446210665d36c9ba377939e2a788492a519987`
- Baseline runtime archive: `d10588641c1f695be78b1a00d08235601fa7e84f69d733d6d9cc042f0bef2bf2`
- Defective candidate boxplot PNG: `a8d4763a77b4840c7e482f10724e17dc7665ceaa7d9e6b2921616c137311d61a`

All remaining hashes, exact paths, online findings, reviewer retry reasons, final replies, first/last decisions and uncertainty are in the [JSON audit](/Users/muhammad/Documents/NACI/pydantic-vis-harness/docs/experiments/2026-09-17-transfer24-audit-second-half.json). Runtime code remained unchanged throughout this audit.

