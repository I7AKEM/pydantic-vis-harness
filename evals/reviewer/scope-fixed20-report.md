# Fixed-image reviewer experiments — 2026-09-17

## Result

No tested reviewer configuration has demonstrated the required reliable result. The best verdict agreement is **17/20**, not 20/20, with Gemma grounded + low thinking. It accepts all ten clean images, but three of its seven bad-image rejections give the wrong reason; only four identify the actual labelled defect. Changing to a closed model also eliminates false rejection of clean charts in this sample, but misses more real defects. Enabling Gemma's thinking with the original named prompt does not improve overall agreement and is considerably slower. No runtime reviewer settings or instructions were changed by these experiments.

This is 160 completed case-trials across eight arms, with 161 attempted model requests. Two trials timed out; both remain failures in their respective 20-case denominators. A retry was attempted in the Qwen arm. Trials used concurrency one per arm, while other independent experiments were also running. Latency measures include provider/network effects and are not a dedicated throughput benchmark.

## Frozen inputs and controls

The first manifest was written before any real request. Every arm uses the same 20 PNG byte hashes and unchanged gold labels: eight clean and seven visibly defective historical cases, plus two clean and three defective saved first renders. The deterministic case IDs are `TRIAL20_LEGACY` in `compare_scope.py` and the five `first-render-*` entries in each manifest. The images were inspected locally before the trial. The 15 historical labels were selected from, and not rewritten within, the existing 89-case labelled set. Recent probes are separately labelled and separately scored.

- All arms have the same 30-second case deadline and maximum three model requests, including up to two output retries. No trial is retried out of the denominator or silently discarded.
- **Baseline:** current reviewer factory, prompt, positional reference rows and output schema.
- **Named:** baseline with only reference rows encoded as objects keyed by the actual result column order. Metadata order cannot silently change the binding.
- **Grounded:** named rows, a narrower visible-defect instruction set, explicit location/observed/expected findings, and original task/question/clarifications removed. This is a combined scope intervention, not a single-variable ablation.
- **Summary first:** named with only the two output-tool arguments reordered. The unit test proves the schema and required-field order are the sole contract differences.
- **Claude and Qwen:** exact named input, original instructions/schema/settings, different model only.
- **Gemma named low:** exact named input/instructions/schema and temperature, only `thinking=False` changed to `thinking='low'`. The successful responses reported 32,659 reasoning tokens; named-off reported zero. The timed-out call's tokens are unknown, not zero.
- **Gemma grounded low:** exact grounded input/instructions/schema and temperature, only `thinking=False` changed to `thinking='low'`. This tests the combination of constrained scope and actual pre-output reasoning, using grounded-off as its single-variable control.

Manifests preserve exact user-request text, input image hashes, labels, code hashes and model settings. Later manifests also preserve the generated Pydantic tool schema and its hash. The original three-arm schema was reconstructed in a separate **offline** manifest after those 60 trials; do not confuse its timestamp with the original pre-call input freeze. Schema capture is framework-level, not a claim to have captured the provider's complete HTTP wire body. Declared model settings are recorded separately because FunctionModel removes unified `thinking` from its ordinary settings before the test callback.

## Scores

“Bad rejected” means a defective image received `revise`; it does **not** establish that the stated reason is true or that the proposed repair would fix the actual defect.

| Arm | Agreement | Clean accepted | Bad rejected | Unreviewed | Mean seconds | Median | Maximum |
|---|---:|---:|---:|---:|---:|---:|---:|
| Gemma baseline, off | 12/20 | 4/10 | 8/10 | 0 | 1.27 | 1.05 | 2.98 |
| Gemma named, off | 15/20 | 7/10 | 8/10 | 0 | 1.16 | 1.00 | 2.54 |
| Gemma grounded, off | 14/20 | 6/10 | 8/10 | 0 | 1.38 | 1.31 | 3.15 |
| Gemma summary-first, off | 13/20 | 7/10 | 6/10 | 0 | 1.12 | 1.03 | 2.11 |
| Claude Sonnet 4.5 named, off | 15/20 | 10/10 | 5/10 | 0 | 4.83 | 4.64 | 7.58 |
| Qwen 3.8 27B named, off | 14/20 | 5/10 | 9/10 | 1 | 14.92 | 14.96 | 30.00 |
| Gemma named, low | 15/20 | 7/10 | 8/10 | 1 | 8.56 | 5.40 | 30.00 |
| Gemma grounded, low | 17/20 | 10/10 | 7/10 | 0 | 8.16 | 6.32 | 26.43 |

Exact model IDs: `openrouter:google/gemma-4-31b-it:nitro`, `openrouter:anthropic/claude-sonnet-4.5`, and `openrouter:qwen/qwen3.8-27b`. The main agent executed the Qwen arm using the same frozen-case script.

### Complete confusion counts

| Arm | Clean/pass | Clean/revise | Clean/unreviewed | Bad/pass | Bad/revise | Bad/unreviewed |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 4 | 6 | 0 | 2 | 8 | 0 |
| Named | 7 | 3 | 0 | 2 | 8 | 0 |
| Grounded | 6 | 4 | 0 | 2 | 8 | 0 |
| Summary first | 7 | 3 | 0 | 4 | 6 | 0 |
| Claude named | 10 | 0 | 0 | 5 | 5 | 0 |
| Qwen named | 5 | 5 | 0 | 0 | 9 | 1 |
| Gemma named low | 7 | 2 | 1 | 2 | 8 | 0 |
| Gemma grounded low | 10 | 0 | 0 | 3 | 7 | 0 |

### Unchanged historical versus visible-regression agreement

| Arm | Historical 15 | Recent first-render 5 |
|---|---:|---:|
| Baseline | 10/15 | 2/5 |
| Named | 12/15 | 3/5 |
| Grounded | 11/15 | 3/5 |
| Summary first | 10/15 | 3/5 |
| Claude named | 11/15 | 4/5 |
| Qwen named | 11/15 | 3/5 |
| Gemma named low | 14/15 | 1/5 |
| Gemma grounded low | 14/15 | 3/5 |

These are single trials on a small selected set. They do not establish generalization, production safety, or the full-89 agreement gate.

## Why the verdict alone is insufficient

1. **Contradictory structured findings produce real repair requests.** Gemma reports error-level value mismatches, then retracts the mismatch inside the same message. Examples are `analyst--deaths_by_year`, `analyst--jeddah_by_wealth_level`, and `analyst--monthly_violations_2025`. The message can end “There is no R-1 error” while its structured `level` remains `error`. The harness correctly derives `revise` from that level. Reordering summary before findings did not remove this behavior. Do not regex-ignore or silently downgrade these outputs.
2. **Runtime image QA leaks into task completion and data audit.** Both Gemma and Claude can demand a map on the clipped-header table; Qwen and thinking-enabled Gemma reject the correctly bound coordinate scatter for missing unbound city/price fields or for not being a map. Those are lead/design task-fulfilment questions, not evidence of a visible binding defect. Narrowing the schema's rule and owner enums does not by itself constrain the semantic claim.
3. **RTL and grouped sorting are misread as incorrect values.** `first-render-c76808cc7a78dac8` faithfully displays the authoritative Najran values: employed 10,356 and population 701. A plausible-world assumption must not swap these columns. Grouped `sort value` uses the displayed series sum, not the first series alone, and RTL order is not a reversal defect. Named row dictionaries remove a binding ambiguity but do not stop invented ordering faults.
4. **Palette order is not the actual legend mapping.** The donut `first-render-6eff7ae46ebb4edf` has genuinely clipped value/category text. Baseline and grounded Gemma instead complain that the palette order requires different category colours, although the marks agree with the actual legend. Named Gemma spots clipping but also emits an invalid colour complaint. Claude spots the clipped digit. Thinking-low Gemma passes this defective image after 21.91 seconds.
5. **Horizontal-bar axis titles are a real defect.** `first-render-39471b0e4a5d3fc5` places “professional group” on the numeric horizontal axis and “average violations” on the category axis. Gemma-off passes it. Named-low Gemma correctly describes the swapped titles. Claude rejects it but incorrectly demands categories on X, as though horizontal bars were invalid; this is not a correctly grounded diagnosis. Grounded-low rejects it only for not mirroring the axes into RTL, overlooking the actual swapped labels.
6. **The rate-unit probe was introduced upstream.** `first-render-61793ff199102633` displays percent signs for a rate per 100. Saved lead metadata already classified the rate as share/percent; the renderer followed that metadata. Named/grounded Gemma and Qwen detect the visible unit conflict. Claude and Gemma-low miss it. Do not blame a renderer default for this particular case.
7. **Correct rejection can conceal a missed defect.** `vizcsv-bfec427bf3135ffe` has only a portion of its 63-row table visible in the PNG. Most arms pass it. Named-low Gemma rejects it only because the title/description are absent, not because rows are missing. Qwen notices the scrolling/clipping issue but labels it a warning while its error is the title. The title rule also creates a false rejection on the clean `analyst--cities_with_more_females` table.
8. **Authoritative small numbers must not be recomputed.** The nonzero-to-zero rounding defects in `vizcsv-620e192d0fd6f826` and `vizcsv-ae79cdc7d8e77066` are real. Some Gemma responses correctly spot zero rounding but then multiply an already-percent-valued source by 100 in their suggested wording. A repair must preserve the source number and unit. Grounded Gemma also wrongly demands a mark for a null source value in the monthly legacy case.

For example, named Gemma rejects eight of ten bad images, but only seven contain an error finding identifying the actual labelled defect. Claude's corresponding count is four, not five, when the horizontal-bar misdiagnosis is excluded. The highest-agreement grounded-low arm similarly identifies only four labelled defects: its rich-household, monthly, and driver rejections are instead based on RTL/chronology layout complaints. It accepts the rate-unit conflict, clipped donut, and truncated table. It fixes the two recent clean false positives without demonstrating reliable detection of the recent real defects. These are manual grounding observations from the saved raw findings, not replacement gold labels or a hidden post-processing pass.

## Evidence files and verification

- `results-scope-fixed20-consented.json`: 60 trials; baseline/named/grounded.
- `results-scope-summary-first20-consented.json`: 20 trials; output argument order only.
- `results-scope-claude-named20-consented.json`: 20 trials; closed model control.
- `results-scope-qwen38-named20-consented.json`: 20 trials; open-weight model control, run by main agent.
- `results-scope-gemma-low-named20-consented.json`: 20 trials; reasoning setting only.
- `results-scope-gemma-low-grounded20-consented.json`: 20 trials; reasoning setting only versus grounded-off.
- Each has an adjacent `-manifest.json`. `results-scope-fixed20-offline-contracts-manifest.json` adds the reconstructed contracts for the original arms without external calls.
- `tests/reviewer/test_scope_experiment.py`: exact keyed bindings, scope schema, unchanged ablations, attempted timeout accounting, deterministic balanced selection, and controlled thinking settings.
- Local verification after adding the thinking ablation: `.venv/bin/pytest -q tests/reviewer` — **24 passed**.

The earlier `results-scope-probes.json` contains network failures before explicit image-sharing consent. It is not model-quality evidence and is excluded from all tables above.

No full-89 validation has been claimed or run by this experiment. No runtime reviewer changes should merge on these results. Any candidate must first pass the unchanged full labelled set with at least 0.8 agreement, with clean acceptance and true-defect detection reported separately; an always-pass reviewer would nearly reach 0.8 on the imbalanced full set and is not acceptable.
