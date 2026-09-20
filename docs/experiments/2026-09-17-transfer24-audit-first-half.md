# Transfer24 independent audit: first three families

Status: complete — all 24 task-arm checkpoints and all 24 retained PNGs independently inspected.

Scope: `relationship_sequence`, `composition_independent_rates`, and `nested_allocation`; 12 tasks in each of two frozen arms (24 task-arm observations). Inputs are independently authored synthetic data, not user-exported data. This is an agent audit, **not human gold**. No UI use, external model calls, runtime/evaluator edits, or holdout-guided tuning by this auditor.

## Frozen evidence

- Bank: `evals/generalization/bank.json`, SHA-256 `2548d627feb492d200ca11bd33113121ee1d9467c15a1d474f09a850759b84a5`, frozen 2026-09-17 03:32:26 UTC.
- Baseline runtime: `573f65b5b612013ffd94558a396ba375d7891df3be68da410328136b354a6218`; started 03:40:13 UTC.
- Candidate runtime: `7ff116ba5c5a222c69f3e7d9806f1356d5e1658524b4de10aa7edebe9150929d`; started 03:40:12 UTC.
- Both arms: GLM 5.3 text team, Gemma 4 31B visual reviewer, identical recorded model/settings, serial within arm, shared limit 18 requests / 16 tool calls, 120s case timeout, same fixed shuffled case order. No benchmark resubmission or tuning is authorized by this audit.

## Criteria recorded before viewing task results

The natural-language task and authoritative brief determine correctness. Machine-contract chart lists are evidence, not unquestionable gold. Equivalent encodings are accepted when they actually fulfill the goal, preserve identities and supplied values, use correct units, and deliver a usable artifact. A correct spec does not establish correct pixels; a review pass does not establish correct output. Every retained first/repair PNG must be viewed.

Original and transformed variants differ only in column identifiers/order and row order, with supplied definitions mapping the same observations. They must retain equivalent task meaning, not byte-identical images. Non-temporal category order may vary. Temporal plots must be chronological even though the transformed rows are shuffled.

| Goal (original and transformed) | Required meaning and visible encoding | Legitimate alternatives / exclusions |
| --- | --- | --- |
| g01 association | Six separate paired points: inlet temperature 18/24/21/27/20/25 °C against corresponding pressure 101/104/109/105/99/112 kPa. Temperature horizontal, pressure vertical. | Scatter or equivalent unconnected paired-point encoding. No time-connecting path, swapped roles, aggregation, or causation claim. |
| g01 trajectory | Pressure over dates 2026-02-01…06 in chronological order, all six values. Temperature is context only. | Line, area, or chronological columns; another interpretable graphical time-series encoding can be legitimate. No table-only result, temperature-pressure scatter, or second temperature measure axis. |
| g02 allocation | Mutually exclusive hours by activity: Inspection 240, Packaging 160, Dispatch 360, Rework 40. | Pie/donut/treemap or readable absolute bar/column allocation; retain direct hours encoding. Do not substitute independent failure rates or create a recalculated source percentage column. Renderer-provided composition percentages are not automatically a source rewrite. |
| g02 failure comparison | Independent supplied rates: Inspection 6.5%, Packaging 12%, Dispatch 3.5%, Rework 25%. | Aligned-baseline bars/columns or another clear common-scale rate comparison. No pie/normalized common whole, hours measure, or ×100 rescaling. |
| g03 parent composition | Three absolute rig totals subdivided by modules, preserving all nine readings. A: Compute 35/Cooling 15/Storage 10 W; B: 20/30/5 W; C: 25/10/20 W. | Stacked bars/columns with one total-length mark per rig; no 100% normalization, merged modules across rigs, or grouped-only substitute for requested subdivided total. |
| g03 module comparison | Every one of the same nine readings has its own aligned-baseline mark; both module and rig identities discernible. | Grouped bars/columns with either nesting orientation, or equivalent shared-scale faceted individual marks. No stacking, sum-only representation, or identity merging. |

## Output conventions

The JSON sidecar records each arm/case separately. `source_fidelity` concerns saved values/identities; `display_fidelity` concerns their actual visible interpretation, including units. `appropriate` is independent of the strict chart allowlist. `final_delivery` records an artifact link/embed in the final reply matching the retained artifact, while `artifact_persisted` is separate; no live HTTP request is implied. `chart_task_correct` evaluates the graphical goal, whereas the stricter `task_correct` additionally includes final delivery and explicit prose/instruction violations. Minor prose failures must not be described as wrong chart selection. Boundary/timeout/failure states are not called successful charts. Reviewer findings are classified as true, false, uncertain, mixed, or none; absent images cannot be visually certified. Unsupported final claims and needless repairs are explicitly recorded. No conclusions about unseen live UI interactions are implied.

## Audited results

Every audited PNG is appropriate, source-faithful and readable for its stated graphical goal. All 24 observations retain exactly one PNG each; all first renders are also their final renders. There are no actual redesigns, rerenders, or repair rounds in this half of the frozen experiment. Correct graphics do not imply correct final delivery, perfect prose, successful online inspection, or low latency.

| Dimension | Baseline (12 tasks) | Candidate (12 tasks) |
| --- | ---: | ---: |
| Source/display fidelity and appropriate graphical task | 12/12 | 12/12 |
| Correct final artifact link/embed | 10/12 | 12/12 |
| Strict machine-contract pass | 10/12 | 12/12 |
| Audit pass including delivery and explicit prose/instruction claims | 8/12 | 10/12 |
| Online false rejection of a correct image | 3 | 0 |
| Online inspection unavailable after timeout | 0 | 3 |
| Actual repairs / unnecessary repairs | 0 / 0 | 0 / 0 |
| Redundant cached review-tool calls | 0 | 2 |
| Completed within 60 seconds | 12/12 | 9/12 |
| Median / maximum wall time | 17.30s / 32.11s | 36.00s / 117.64s |

The prose-inclusive count must not be presented as a chart-selection accuracy score. Four of its six failures across both arms are non-graphical wording/instruction defects; the other two are missing or malformed artifact links. No observed graphical-goal failure explains these differences.

### Paired observations

All rows below pass source fidelity, display fidelity, graphical appropriateness, and first/final PNG inspection in both arms. `Delivered` means a correct final link/embed, not merely a persisted artifact. Full judgments and per-image/checkpoint hashes are in the JSON sidecar.

| Case suffix | Baseline seconds / delivered | Candidate seconds / delivered | Additional audit finding |
| --- | --- | --- | --- |
| g01 association original | 12.78 / yes | 44.87 / yes | Baseline false review self-retracts; candidate timeout count is misstated. |
| g01 association transformed | 23.61 / yes | 60.62 / yes | Baseline false axis-swap review self-retracts; candidate timeout count is misstated. |
| g01 trajectory original | 21.41 / yes | 14.07 / yes | Baseline final axis-minimum claim contradicts its PNG. |
| g01 trajectory transformed | 10.97 / no | 15.11 / yes | Baseline final render ID is corrupted. |
| g02 allocation original | 11.92 / no | 27.13 / yes | Baseline publishes image but omits its final link. |
| g02 allocation transformed | 9.07 / yes | 16.57 / yes | Both deliver correct direct-hour composition. |
| g02 failure comparison original | 19.12 / yes | 16.58 / yes | Baseline adds a new ratio despite explicit no-new-calculations instruction. |
| g02 failure comparison transformed | 32.11 / yes | 16.51 / yes | Both show the four independent rates on a common zero baseline. |
| g03 parent composition original | 15.48 / yes | 46.75 / yes | Candidate online inspector times out; final disclosure is truthful. |
| g03 parent composition transformed | 9.36 / yes | 117.64 / yes | Candidate latency outlier is not a repair loop. |
| g03 module comparison original | 19.15 / yes | 66.93 / yes | Candidate exceeds latency target without repair. |
| g03 module comparison transformed | 25.88 / yes | 56.72 / yes | Baseline false mapping error retracts itself; lead declines repair. |

### Evidence and disagreements with machine scoring

- Baseline `g01-trajectory-transformed`: correct chronological line image exists under `134a69454caa`, but final embeds the corrupted ID `134a694caa`; unusable final image link.
- Baseline `g02-allocation-original`: correct direct-hours donut persists, but final contains no image or artifact hyperlink. Its renamed/shuffled counterpart supplies the correct link.
- Baseline `g03-module_comparison-transformed`, `g01-association-original`, and `g01-association-transformed`: online review emits an error-level finding whose own narrative explicitly verifies the values and retracts the allegation. Viewed images are correct. Lead declines all three unnecessary repairs and describes the contradictions truthfully.
- Candidate `g03-parent_composition-original`: reviewer times out after 30s. Lead discloses that limitation rather than claiming a review pass. Independent image audit finds the stacks correct.
- Candidate `g03-module_comparison-original` and `g03-parent_composition-transformed` take 66.93s and 117.64s, respectively, without a repair loop. The latter has only one designer call (3.57s), one render and one reviewer call (6.91s). The parent auditor independently queried Logfire and reports GLM lead waits of 51.74s (design-delegation decision), 19.11s (inspect decision), and 20.50s (publish decision); that is corroborating parent evidence, not an external query by this PNG auditor. These are latency failures relative to 60s, not chart-selection failures.
- Candidate `g01-association-original` and `g01-association-transformed` are visually correct and linked properly, but both final replies say the inspector timed out twice. Their saved timelines show one 30.0077s / 30.0066s timeout and a second cached return only 0.791s / 1.957s later with a no-repeat instruction. The lead truthfully discloses lack of inspection; only the timeout count is false. Each has one redundant cached review-tool call, not a second external timeout or a repair loop. Neither was incorrectly described as a successful online review.
- Two baseline prose-only issues are separate from correct charts: failure comparison adds an approximately correct new ratio despite the no-new-calculations instruction; original trajectory claims the axis starts at 99 kPa, repeating a resolver compromise, while the PNG's minimum tick is 98 kPa. The scorer does not inspect those claims. Original association's 'axis range 99–112' is recorded as imprecise data-range wording, not a hard graphical failure.
- Both original and transformed stacked views are legitimate despite differing segment order/colors. Their task asks for within-rig subdivision, not aligned within-module comparisons. Byte-identical output is not the oracle.

No strict chart-family disagreement was necessary in these observations: all designs satisfy both the substantive task and the machine allowlist. The independent audit still evaluated legitimate alternatives, including varying category order and zero versus nonzero line-chart axes, without imposing new aesthetic gates. No table was truncated, no source row was missing, and no explicit full-table request was violated in this assigned half.

## Interpretation and limits

The original-to-opaque/shuffled transformations did not break chart selection or role mapping in these three families in either arm. This is positive transfer evidence for these 12 tasks, not proof that the entire harness generalizes. Three shared synthetic data families and one trial per arm do not yield 24 independent domain tests. No holdout was used for prompt/runtime adjustment, no cases were rerun to replace unfavorable observations, and no UI/tooltips or live artifact HTTP availability were tested.

The candidate improves observed final-link delivery but has a worse latency distribution in this single run; the audit cannot isolate a causal runtime-versus-provider explanation. Three candidate inspections actually timed out, and two added a cheap cached repeat tool call. The largest delay has parent-confirmed GLM lead decision waits, not repeated drawing. Specialist internal model retries, cached tool returns, and actual repair rounds are distinct and should not be conflated.

Integrity verification after the final case: exactly 12 expected task IDs per arm; 24 unique records and 24 viewed PNGs; all retained PNG inventories and SHA-256 values match the sidecar; every checkpoint SHA-256 is unchanged; all stored source rows/columns exactly match bank values/identities in source order; each CSV byte hash matches the frozen bank. Bank SHA-256 remains `2548d627feb492d200ca11bd33113121ee1d9467c15a1d474f09a850759b84a5`. This auditor changed only the two assigned audit documents and did not modify raw results, bank, runtime, defaults, or evaluator.
