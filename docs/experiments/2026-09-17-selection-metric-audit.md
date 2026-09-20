# Chart-selection and fidelity metric audit — 2026-09-17

## Scope and conclusion

This audit inspected the 50 frozen development handoffs in
`evals/lead/case-bank-v1/cases.json`, the additive
`evals/lead/runtime-contracts-v1.json` overlay, the current evaluator, and the
relevant structural validation/rendering code. The objective is harness maturity:
correct interpretation and delivery with bounded latency, not another model
comparison.

The cases already test source preservation, delivery, resource limits, and
latency. Their main selection gap is that **mentioning every requested column is
not the same as assigning those columns to the correct visual roles**. In
particular, headline/support roles, measure/category roles, and rendered-value
transformations need explicit evaluator evidence.

This was an offline audit. No model calls or external data transfers occurred.
No runtime code, prompts, frozen cases, or historical results were changed.
The local wrong-headline probe below performed structural checks only; it was
not a rendered or independently reviewed end-to-end success.

## Exact contract coverage

There are 48 requested rendered presentations and two technical-boundary cases.
Counts below describe acceptance contracts, not execution or success counts.

| Contract | Initial 20 | Supplementary 30 | Total |
| --- | ---: | ---: | ---: |
| Explicit `charts` allowlist | 20 | 0 | 20/48 rendered |
| Exact `bindings` | 0 | 0 | 0/50 |
| `metrics` / indicator headline-support acceptance | 0 | 0 | 0/50 |
| Required `visible_columns` | 20 | 28 | 48/48 rendered |
| `strict_source` | 20 | 29 | 49/50 |
| Required image delivery | 20 | 28 | 48/48 rendered |
| Required PNG evidence | 20 | 28 | 48/48 rendered |
| Required reviewer pass | 20 | 28 | 48/48 rendered |
| End-to-end latency limit | 20 | 30 | 50/50 |
| Per-tool call limits | 20 | 30 | 50/50 |
| Explicit `axis_titles`, `display_labels`, or `language` gates | 0 | 0 | 0/50 each |

The absence of axis-title or display-label gates is not itself a reason to add
fixed aesthetics requirements. It indicates only that these fields are not
independently scored. Exact source names and legitimate localized presentation
must remain possible.

The two non-chart outcomes are intentional:

- `corpus-vizcsv-061a265236a642ce`: the 22,208-row source exceeds the existing
  10,000-row direct-source limit. The contract requires an honest explanation,
  no image, and no repeated specialist work on the same source.
- `corpus-vizcsv-7a6c7f323afafbe3`: all 1,000 text rows must remain available in
  the complete source-table fallback. It must not invent category counts or
  receive credit as a verified chart. The source geometry remains local.

The runtime overlay currently contains **one semantic contract**, for
`corpus-vizcsv-2177430e3e44a9a3`. Four source cases contain the exact gender codes
`F` and `M` without supplied code meanings:

- `corpus-vizcsv-2177430e3e44a9a3`
- `corpus-vizcsv-2571f37808cda8e2`
- `corpus-vizcsv-1240bc417714a3e6`
- `corpus-vizcsv-245c6996f0f23a81`

All 50 briefs have no supplied `column_descriptions` or `code_meanings` mappings.
Some do supply percentage units. Nothing in this audit invents a codebook,
denominator, currency, or domain meaning. The historical `original_question`
field is not authority to override the actual prepared-data handoff.

## Demonstrated wrong-headline acceptance gap

Case `corpus-vizcsv-46dad75ae7fa7b62` explicitly requests `percentage` as the
headline indicator, with `same_university_returners` and `total_postgrad` as
supporting values. It also says the source percentage was rounded to zero and
must not be recalculated.

A local read-only probe loaded the saved report from:

`evals/lead/results-parallel20-glm-production-v3-assets/corpus-vizcsv-46dad75ae7fa7b62/case.json`

It constructed each spec with `Spec` / `IndicatorCard`, serialized it with
`to_text`, and called `check_spec(..., policy=False)` and `visible_columns`.

| Headline | Support | Executable structural check | Current visible-column check |
| --- | --- | --- | --- |
| `percentage` | `same_university_returners`, `total_postgrad` | Pass | Pass |
| `total_postgrad` | `same_university_returners`, `percentage` | Pass | Pass |

The second presentation violates the brief even though it preserves all source
values and mentions all required fields. This is an **evaluator coverage gap**,
not a reason to make runtime schema validation select the headline. A new
case-specific role contract should distinguish these two designs offline.

## Conservative evaluator-only additions

### 1. Support alternatives with chart-specific role contracts

Add a small, versioned, opt-in `presentation_options`-style expectation. Its
semantics should be **any one valid option**, not one preferred chart. Each
option may constrain the chart family and the relevant exact bindings, folded
columns, or indicator card roles. Keep it in an additive evaluation overlay;
do not rewrite the frozen study or introduce a runtime aesthetics gate.

The existing flat `bindings` expectation cannot express, for example, both a
valid chart binding and a valid complete table alternative. Nor does it express
card values versus support. Avoid comparing serialized specs or demanding one
series/card order when multiple orders answer the brief.

Begin with exact instructions in the initial cases:

| Case ID suffix | Grounded role requirement |
| --- | --- |
| `46dad75ae7fa7b62` | `percentage` is the headline; the two named counts are support. |
| `45980b90faceca07` | Two percentage headlines, `wealthy_female_pct` and `wealthy_male_pct`, with their own sex-specific counts/totals as support; retain the existing complete-table alternative. |
| `6eff7ae46ebb4edf` | Requested donut: category `نوع_السكان`, value `العدد`. |
| `ae315d3da67a2d11` | Scatter x/y use the `latitude` / `longitude` pair. Either orientation can be valid if its axes are truthful; this is not a map or a connected route. |
| `39471b0e4a5d3fc5` | `profession_group` identifies categories; `avg_violations_per_person` is the measure; bar/column/table remain valid. |
| `2bc0cfa90c65f142` | `city` identifies categories; `wealthy_count` is the measure; preserve every supplied row. |
| `61793ff199102633` | `education_level` identifies categories; `violation_rate_per_100` is the measure, not a raw count. |
| `2177430e3e44a9a3` | Compare the supplied `percentage` over `region` and `gender`; preserve both dimensions and literal codes. |
| `9e75e9ae40758227` | Compare `population_count` over `age_group` and `person_type`. Both truthful category/group orientations can be valid. |
| `c76808cc7a78dac8` | Compare the exact `population` and `employed` measures by `city`; accept one-to-one fold, dual-axis, or table alternatives without correcting the source values. |
| `f6687502449585a5` | Preserve `district`, `violation_count`, and `percentage` as distinct supplied measures; retain dual-axis/table alternatives. |

For the seven single-primary indicator-only cases, exact primary-column checks
are straightforward. Do not turn the other single-row briefs into a fabricated
headline preference when they merely ask to display all supplied fields.

### 2. Cover straightforward supplementary selection without overfitting

Fifteen of the 28 supplementary rendered cases have a conservative starting
set of alternatives:

- **Seven single-row cases:** indicator or complete table, preserving all
  requested fields and missing values:
  `00754e9ed454a58b`, `09050180d3961b03`, `18c8e508976a1ff7`,
  `44cfda42866aa5ae`, `2075320dff9f6ebd`, `57c25fcba38f1bb0`,
  `a25bc59748f9842d`. In `09050180d3961b03`, the percentage is missing; do not
  demand a numerical headline or permit replacement by zero.
- **Text-only region list:** `ac951afc1e53d382`, complete table without invented
  counts.
- **Annual values:** `010c162b92ef3206`, truthful line/bar/column/table using
  `year` and `new_jobs_count`, preserving period identity and order.
- **Six category/measure pairs:** `099ca8ed3f245957`, `245c6996f0f23a81`,
  `442a491c20867c73`, `98f1ef4953f7c74d`, `ec9b6239518a7b5e`,
  `ffcc0df19d7c2f61`. Bar/column/table are safe alternatives. Additional chart
  families should be accepted only when their semantics are justified; for
  example, negative changes must not be treated as positive pie shares.

These are proposed acceptance options, not adopted gold labels. The remaining
13 supplementary rendered cases have additional dimensions, mixed measures,
or composite time fields and deserve explicit alternative-by-alternative audit:
`03384a96e9fe5870`, `1706fb33ef7fd300`, `07d3a923817c343d`,
`1240bc417714a3e6`, `98fe17bdec87024a`, `39d623d403ef86e5`,
`ed2d9d4b2f49d899`, `244e80ce1f6ea1e6`, `e384bfa45ac5ab8e`,
`e6f74cc7f3324781`, `a723f837bb1cd6a9`, `1ea76a97e400d852`,
`20d73400a693d49f`. A guessed single gold chart would create another source of
false failures.

### 3. Extend explicit unknown-code regressions

Apply the already documented F/M no-codebook contract to the other three
matching cases listed above. This means checking unsupported expansions, not
declaring that F or M has a particular meaning. Supplied `code_meanings` or
approved display labels remain authoritative in cases where they actually exist.

## Source fidelity is not rendered-value fidelity

`strict_source` hashes the persisted complete table. `visible_columns` collects
bound/folded/card field names. Neither proves that the encoded values and
category-to-value associations in the renderer are unchanged.

Relevant executable paths in `vis_agent/designer/resolve.py` include:

- `percent=True` normalizes stack values to derived percentages.
- `limit` can fold categories into an Other value.
- Histogram rendering bins supplied values and produces distribution counts.
- Missing-measure rows can be dropped from a non-table rendering, with a
  compromise recorded.

Such transformations can be legitimate for other tasks. For these handoffs,
however, the exact brief says not to recompute, reaggregate, sample, invent
values, or replace missing values. An unchanged saved CSV is therefore
necessary but insufficient evidence of a faithful presentation.

Add evaluator-only checks of the saved resolved data/config and transformation
diagnostics, comparing the used measures and category/value identities against
the authoritative source. Allow ordering and one-to-one wide-column folding.
Reject unauthorized derived proportions, collapsed Other groups, or distribution
counts when the brief asks to present the original prepared measures. Test both
positive and negative examples so this does not become a blanket ban on useful
chart types for future tasks.

For tables, inspect complete accessible content separately from a static PNG.
A working scrollable viewport may legitimately show only part of the table.
An inert scrollbar drawn in a PNG does not make hidden rows accessible, and an
image's dimensions alone do not prove that its glyphs are readable.

## Contract pass is not independently verified quality

Use names such as `contract_pass` and `contract_within_sla`, not a claim of
verified visual quality. In particular:

- The model reviewer's pass is evidence about a scoped inspection, not a gold
  label or proof of correctness. Historical false rejections and contradictory
  findings must not become desired optimizer behavior.
- Independent image/semantic audits must be tied to the actual run, source
  identity, artifact version, and render hash. An old successful image audit
  cannot certify a newly generated image.
- Numeric prose matching currently establishes that mentioned numbers occur in
  the source/context; it is not a complete natural-language proof of their
  category association or of every semantic claim.
- The 50 cases are known development data. Source-grouped train/validation
  splits are useful for tuning but do not create a fresh blind test set.

Report contract failures, delivered artifacts, end-to-end latency, model/tool
counts, and independent visual/semantic audit status separately. Do not let a
speed bonus compensate for a wrong or undelivered presentation.

## Prioritized maturity work

1. **Close deterministic contract holes first:** primary/support roles, exact
   measure/dimension bindings, and preserved rendered values. Add offline
   positive/negative regression tests before using them as optimization reward.
2. **Version the additive evaluator overlay:** preserve the frozen 50 inputs
   and raw results; record the overlay/scorer hash for every new run. Keep
   acceptance metadata out of model task inputs.
3. **Run real end-to-end regression evaluations on one stable harness:** do not
   change runtime/evaluator code mid-run, retain failures, and compare complete
   delivery trajectories rather than first-action proxies.
4. **Audit failures and a sample of apparent successes independently:** account
   for genuine scrolling, source/code meanings, renderer transformations, and
   reviewer false alarms. Promote confirmed failures into regression cases.
5. **Optimize only after the metric is credible:** tune a scoped prompt if
   useful, then validate correctness before speed. Track provider/model time
   separately from design/render/review and repeated-harness work, without
   conflating this maturity effort with another model-selection experiment.
