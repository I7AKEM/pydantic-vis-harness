# Indicator implementation and validation — 2026-09-15

**Status: implementation and validation runs complete. Indicator metric and image checks pass; remaining routing, response-format, warning-disclosure, and legacy-analysis limitations are recorded below. No merge was performed.**

This work follows the [implementation plan](superpowers/plans/2026-09-15-indicator-cards.md) and the Downloads report `20260913-183937`. It does not establish coverage of every visualization request. The release gates require correct metrics, appropriate presentation, faithful rendering, and delivery; a valid spec or existing image is insufficient.

## Implemented behavior

### Follow-up regression: literal `percentage` unit

The user's artifact `art_2ce1b391309d41258632e473ea06c8f8` exposed a gap in the original
unit coverage: a supplied `unit: "percentage"` rendered the word `percentage` beside
108.86. The original failed render is retained at `data/renders/1b077356b887`; the
new scorer records its failure in `outputs/indicator/percentage-alias-original-failure.json`.

The shared unit policy now recognizes exact English/Arabic percent aliases as `%`.
It changes spelling only: 108.86 stays 108.86, 0.34 stays 0.34, and fractions,
percentage points, basis points and compound/unknown units remain distinct. New
query metadata is canonicalized before checking and saving. Historical reports
retain their original unit metadata; formatting and range checks interpret aliases
consistently. Percentage changes may be negative or exceed 100; part-of-whole
shares still obey their explicit scale.

- Full offline suite: **1,450 passed**, one existing Starlette deprecation warning
  (`outputs/indicator/percentage-full-tests.log`).
- Final visual review also corrected the RTL percent-symbol position: the number
  and `%` form an LTR run in PNG and HTML, while Arabic count nouns retain their
  own direction. Explicit ordinary-chart formats such as `0.0 percentage` use `%`
  too. The wider follow-up run passed 1,007 checks and found one old test expecting
  literal `pct`; its expectation was updated for the new alias policy. All **381**
  resolver, indicator renderer, and indicator scorer checks then passed
  (`outputs/indicator/percentage-final-recheck.log`).
- Exact saved-spec replay: the PNG and accessible HTML display `%`, one Arabic
  heading, and the unchanged 108.86. Raw report metadata remains `percentage`.
  Preview and draw evidence: `outputs/indicator/percentage-alias-preview/`.
- Live designer regression: **1/1** passed delivery, spec, presentation, metric,
  and rendered fidelity (`outputs/indicator/percentage-alias-live.json`). This is a
  known regression, with an explicitly adapted brief to preserve the original
  heading, not an unseen confirmation case.
- Added negative scorer tests reject a literal `percentage` suffix, omitted unit,
  fraction/percentage-point substitutions, and 100× numeric changes. The previous
  full eval matrix below predates this follow-up; those runs were not repeated.

### Indicator behavior

- `indicator` is a first-class chart with one to six explicitly bound cards. A card has a primary result column, context columns, supporting columns, and optional formatting. Indicators require one complete result row and preserve all supplied columns. The existing designer decides whether a card fits the question.
- The request runner no longer skips design for a single number. It uses the existing designer/check/render/persistence path, including fallback, revisions, and resume. Explicit numbers-only/table requests still use the answer path.
- The pinned GPT-Vis adapter draws cards through its existing Node canvas entry point. No new agent, renderer package, or orchestration layer was added.
- Shares use explicit partition metadata before total checks. Scalar rates, partial selections, signed percentage changes, and complete partitions are distinguished. SQL remains responsible for every statistic.
- Zero and NULL differ. A NULL metric displays unavailable; a technical failure remains a failure or disclosed fallback. Tiny nonzero values and exact integers retain their meaning through Python formatting and actual drawn-text checks.
- Explicit language revisions reuse the saved analysis. Request language detection honors common instructions such as “Make this card Arabic” even when the instruction itself is English.
- New analyst queries with a share must state `%` or `fraction` in the column metadata. A missing scale is a fixable error returned within the existing three-query budget. Legacy saved reports remain loadable with unknown scales; the renderer never guesses or rescales them.

### Current layout and units: the user's latest preference

The statistic label appears **inside the card above the number**. A matching outer heading is omitted so the same heading is shown once. The number and its meaningful unit are drawn as adjacent runs, allowing a smaller unit without losing it. Multiple cards retain their own labels and units.

Meaningful supplied units remain visible, with a bounded localization policy for person/user/order nouns. Generic `count`/`number` markers may be omitted. Money, percentages, compound units, and the original source metadata remain distinct. A label's meaning is not invented from a missing unit.

The earlier proposal to show a bare number and suppress the meaningful noun was superseded by the user's explicit correction. The actual user regression is the DuckDB sum of `citizen_count`, **18**, with source unit `person`. The current preview draws `إجمالي عدد المواطنين`, `18`, and `شخصًا` inside the compact card, with the description below. Its independent rendered-fidelity check passes on the actual PNG/config text and bounds. See [actual preview](../outputs/indicator/user-population-preview/chart.html) and [saved query/result](../outputs/indicator/user-population-preview/result.json). The separate mixed-unit preview is illustrative, not the user's data.

## Test environment and evidence

- Python **3.12.12**, through the existing `.venv/bin/python`. The sandbox denied reading the normal uv cache; direct execution used the already installed environment rather than changing dependencies.
- Renderer validation uses **Node 22.23.2** at `/private/tmp/indicator-node22/node-v22.23.2-darwin-arm64/bin/node`. The ordinary shell resolves Node 25, so an explicit Node 22 PATH is necessary for these checks.
- Renderer pins remain `@antv/gpt-vis-ssr@0.3.8` and browser package `@antv/gpt-vis@1.0.1`.
- The recorded same-day runs use `openrouter:google/gemma-4-31b-it:nitro` for the lead and specialists shown in their provenance. These runs use the same model family for baseline/candidate comparisons; they are not a comparison against the September 13 report's different lead setup.
- Baseline git revision: `2bcc745`. Candidate work remains uncommitted; output provenance records git revision and dirty paths, corpus hashes, models, prompts, and dependency versions. No PR or commit was created for this validation record.
- Saved evidence is under `outputs/indicator/` and is ignored by git. Designer `--out` saves source reports, complete design outputs, scores, paired comparisons, and portable assets. Analyst `--out` saves complete outputs/checks, scores/assertions and provenance. Lead evidence retains messages, attempted tool calls/retry prompts, request/artifact records, returned source metadata, timing, usage, and copied render assets. Missing monetary cost is not treated as zero.

The counts below were calculated with DuckDB over the **named success metrics**. Requests/check calls/seconds are efficiency measurements and are never included in success rates.

## Recorded same-day baseline and candidate

| Check | Baseline | Recorded candidate | Interpretation |
| --- | --- | --- | --- |
| Deterministic recommendations | 37/37 | 38/38 | Adds an explicit summary indicator case while retaining a non-summary single-number case. |
| Ordinary designer suite | 31 cases; all recorded automatic correctness metrics 1.00 | 31/31 Delivered, Passed and ChartAccepted | Same-model compatibility evidence; legacy ChartAccepted remains a rules-agreement diagnostic. |
| Ordinary lead seed suite | 11/11 cases; 19/19 tool/outcome; 3/3 revision decisions | 21/21 seed-plus-corpus cases; 29/29 tool/outcome | Seed and corpus-extended runs must not be compared as if they were the same sample. |
| Latest completed full offline run | — | 1,373 passed, one existing deprecation warning | `pytest-final-verified.log`; subsequent duplicate-footnote fix passed 52 focused renderer/scorer tests. |
| Latest focused eval/scorer regression block | — | 189 passed | Exact selected eval test block, including frozen fixture compatibility, strict metric scoring, and unit/text evidence. |

Evidence: [baseline designer log](../outputs/indicator/baseline-designer.log), [baseline lead JSON](../outputs/indicator/baseline-lead.json), [ordinary designer candidate](../outputs/indicator/designer-regression.json), [deterministic log](../outputs/indicator/designer-deterministic.log), [offline log](../outputs/indicator/pytest-complete.log).

Ordinary designer mean recorded model requests changed from 3.23 to 3.13; mean time changed from 4.76 seconds to 2.51 seconds (candidate p50 2.39, p95 3.39). Service/model timing variation prevents attributing that difference to the feature. Formerly skipped scalars now incur a designer run; this introduces overhead. The focused dev run averaged three designer requests. No “no overhead” claim is supported.

## Focused results already recorded

| Evidence file | Scope | Presentation fit | Metric fidelity | Rendered fidelity | Important qualification |
| --- | --- | --- | --- | --- | --- |
| `dev-final.json` | 12 dev cases × 3 = 36 | 36/36 | 36/36 | 36/36 | Development cases, not confirmation. |
| `heldout.json` | Original 12 heldout × 3 = 36 | 30/36 | 30/36 | 30/36 | Age breakdown and missing-year coverage failed in every repeat. This set subsequently informed changes. |
| `discovery.json` | All 35 one-row discovery results | 29/35 | 29/35 | 29/35 | Seven cases fail at least one named criterion; the failed metric sets overlap differently. |
| `focused-after-coverage.json` | Combined original 24 × 3 = 72 | 68/72 (94.44%) | 68/72 (94.44%) | 68/72 (94.44%) | Still below the 95% presentation gate; includes one inappropriate NULL clarification and three age-breakdown selections. |

All 72 specs in `focused-after-coverage.json` passed the spec checker used for that run. **That did not establish presentation correctness.** A later intent-aware check was added for indicator-incompatible intents; the final matrix must verify that change. The earlier scores remain intact.

The four failures in the combined run are:

1. `dev_unavailable [1/3]`: the designer asked the user to verify the data/time period instead of delivering an unavailable-value card for the already valid NULL result.
2. `heldout_age_breakdown [1/3]`, `[2/3]`, `[3/3]`: the requested age distribution became a set of headline cards. The independent gold still requires preservation of the breakdown presentation.

## Failures and evaluation corrections are kept separate

### Confirmed runtime or delivery problems in preserved evidence

- Missing per-year detail was presented as a complete scalar indicator in `vizcsv-6c8cc1666963d616` and the original heldout missing-years case.
- Population/age breakdowns became indicators in `vizcsv-8001e09f5f45bb3f` and the heldout age case.
- Three discovery questions with explicit Arabic response formats were drawn as indicators: `vizcsv-1ddfa1a4c0823358`, `vizcsv-9f9155e976cefaff`, and `vizcsv-a7761ce7247590cc`.
- `lead-final-1.json`: the multi-KPI request hit a real analyst timeout. Its failed request is not counted as successful because the evaluator completed.
- The first denominator-revision turn returned the right numeric share, 20, but its analyst metadata omitted `%`; the picture lacked the required percentage unit. The reply also claimed no warnings despite the returned unknown-scale warning. Correct SQL values alone do not make this a passing delivery.
- The no-pending resume turn attempted a withdrawn tool. The saved trace explicitly contains `Unknown tool name: 'resume'` and the list of offered tools without resume, followed by recovery text. It remains a tool-control failure.

`lead-final-1.json` recorded **11/14 passing conversations**, 19/20 tool selections, 19/20 outcomes, 16/18 checked metric outcomes, and 17/18 checked image deliveries. All five checked style/data analysis-reuse decisions passed. These are historical candidate results, not a final release pass.

### Restrictive presentation golds needing human interpretation

Two discovery failures preserve the requested numbers and scope but differ from the frozen presentation choice:

- `analyst--egyptian_top_port` uses a one-bar chart with the correct port identity. The frozen accepted set is table/indicator. This is not evidence of a wrong number or missing entity.
- `vizcsv-a987ac48cb20a44c` uses the two correct primary cards but reciprocally repeats each metric as the other's support. This violates the exact support gold and adds clutter; it does not drop or alter a metric.

Their original golds and failures were **not** broadened or relabeled to make the run pass.

### Evidenced evaluation defects corrected

- A no-pending request originally expected resume even though the tool is deliberately withdrawn. The gold correction is recorded; attempted unknown-tool calls still fail.
- Generic count labels and meaningful count nouns needed dimension-aware lead comparisons. Explicitly requested meaningful units remain required; currency and percentage expectations remain strict. Rendered fidelity still verifies raw metadata and actual visible units.
- Analysis-reuse scoring originally compared a language-only report field; it now compares saved SQL work, result, model, creation time and elapsed analysis time.
- Final-answer numeric checking originally rejected mandatory row counts/version numbers and copied verified source-total warnings. These are now accepted only from saved metadata/context; unrelated values and 100× percentage rescaling still fail.
- Provider usage includes Decimal cost fields; evidence serialization now preserves them safely instead of losing a completed run.
- `indicator_percentage_change` in `analyst-focused-retry.json` returned the correct −80 and said “decreased by 80%.” The old check incorrectly rejected the unsigned magnitude. The new bounded directional-wording helper accepts that wording while rejecting incorrect increases, negation, and contradictory signed phrasing. The final live SQL run passes this case.

## Holdout integrity

- The **35 discovery cases** remain discovery, including their original questions, saved reports, classification rationale and hashes.
- The **original 12 heldout cases** retain their original definitions and outputs. `heldout-manifest.json` now marks them **used for tuning** after their failures informed changes.
- `confirmation.json` contains **12 fresh synthetic source families**, frozen before confirmation model runs. Its manifest hashes the cases and every input report. It covers unseen age bands, missing depot and quarter coverage, scalar/share/mixed-unit/NULL/precision/localization cases.
- The actual Arabic citizen-count regression and its cross-language lead conversation are separate known regressions, **not** fresh confirmation cases. The actual-user display gold was updated only because the user explicitly changed the requested layout/unit behavior.

## Final matrix

| Required final check | Evidence/status |
| --- | --- |
| Full offline suite | `pytest-final-verified.log`: 1,373 passed, one existing warning. The final footnote correction then passed all 52 focused renderer/scorer tests in `footnote-final-tests.log`. |
| Deterministic recommendations | `designer-deterministic.log`: 38/38. |
| Fresh confirmation: 12 × 3 with rendering | `confirmation.json`: 36/36 presentation, metric, and rendered fidelity. Frozen expectations unchanged. |
| Final focused designer regressions: 24 × 3 | `focused-final.json`: 72/72 Delivered, Passed, ChartAccepted, presentation, metric, and rendered fidelity. Includes the previously failing breakdown and NULL cases. |
| Actual citizen count/layout and explicit Arabic revision | `lead-user-regression.json`: 2/2 turns with correct 18/person values and image delivery; Arabic revision reused analysis. `user-regression.json` initially found an identical description repeated as a footnote. That duplicate was fixed; `user-regression-fixed.json` rescored the unchanged saved model output with rendered fidelity true, preserving the original failed scores and original assets separately. |
| Focused analyst SQL | `analyst-focused-complete.json`: 8/8 tables and clean checks before the new unit guard. Final guarded run `analyst-final-verified.json`: 7/8; the remaining rate-support case timed out, then passed alone in `sql-timeout-retry.json`. All eight unique cases have been verified, but this is not a claim that the final initial run was 8/8. |
| Focused lead three independent final runs | `lead-acceptance-1/2/3.json`: 13/14, 14/14, 14/14 conversations. All 60 turn outcomes, 54 checked metric outcomes, 54 checked deliveries, 45 checked final-answer number outcomes, and 15 analysis-reuse decisions passed. Tool selection was 59/60: one unavailable-resume attempt recovered to a correct text answer. |
| Ordinary analyst suite | `analyst-regression.json`: 69/71 correct tables. Two failures were a partition metadata retry failure and a repeated regional-total sum. The same unchanged two cases passed 2/2 on both final candidate (`ordinary-recheck.json`) and original baseline (`ordinary-baseline-recheck.log`). This bounds the observed failures as unstable results; it does not erase the initial wrong query or prove deterministic correctness. |
| Ordinary designer suite | `designer-regression-final.json`: 31/31 Delivered, Passed, and ChartAccepted. |
| Scale train/dev/heldout; heldout render/judgment | Full scale file: 163 eligible cases (143 corpus plus 20 seeded), 57 saved unanswered reports excluded. 154/163 delivered, 140/163 ChartAccepted; some missing-coverage clarifications are appropriate despite legacy delivery golds. Final heldout run: 29/40 eligible, 29/29 automatic delivery/chart/render checks, 25/29 text-only judge passes. The 11 excluded heldout reports are not successes. Actual-image review below identifies remaining source/semantic gaps. |
| Ordinary lead plus seed-11 corpus sample | `lead-regression-corpus-fixed.json`: 21/21 cases, 29/29 tool/outcome, 3/3 revision decisions after the partition metadata compatibility fix. |
| Built-in browser smoke checks | Verified English totals/mixed units, Arabic 20% with supporting counts, a color revision reusing saved analysis, a Riyadh filter recomputing [4,20,20], unavailable [NULL,0,0], and a no-image numbers-only answer of 60. Artifacts/requests and copied PNG/HTML/config evidence: `browser-evidence/evidence.json`. |

**Remaining boundaries:** a model sometimes attempts the unavailable resume tool; the framework rejects it and the recorded run recovers. The browser lead can say there are no warnings while the returned artifact contains warnings, and a “just the number” request currently receives a table/summary rather than only the number. Those are response-control/disclosure gaps, not solved by the indicator renderer. The deterministic and focused metric gates pass; full-system edge-case closure is not established.

## Independent review of actual PNGs

The Codex eval subagent directly inspected **14 PNGs** against their saved questions, frozen reports, specs and explanations: all four scale cases that failed `LLMJudge`, plus the first rendered repeat of each fresh confirmation case. Two of the 12 confirmation cases correctly clarified missing depot/quarter detail and produced no image. This was a model visual review, not a human review. The existing `LLMJudge` receives text/specs, **not the PNG**, so its 25/29 score must not be described as an image-quality score. Full per-case reasons and image/source hashes are saved in [visual-review.json](../outputs/indicator/visual-review.json).

- **Fresh confirmation:** all 10 existing PNGs preserve their supplied values, units, context and precision. The two missing-coverage clarifications are appropriate. One scope limitation remains: `confirm_land_registry_text` passes its frozen designer-only table fallback expectation and has the exact requested explanation, but it also has a table PNG. This does not establish end-to-end compliance with the user's no-chart/exact-text instruction. The review records 11 passing outcomes and one uncertain whole-request outcome; automatic scores and frozen golds remain unchanged.
- **Scale percentage card:** `vizcsv-b2a15904ec3d6ba4` visibly shows **48.5 without `%`** despite the percentage question and explanation. Its saved source unit is NULL, so the numeric/source metadata is preserved but the semantic presentation fails. The new live analyst unit guard addresses new queries; this frozen legacy report still exposes the gap.
- **Scale complete-year request:** `vizcsv-df9ab911b6b9b867` faithfully draws values through **2026**, which is incomplete on September 15, 2026. This is a failed period-selection assumption already present in the frozen report, not a rendering arithmetic error.
- **Two uncertain scale outcomes:** `vizcsv-222e820210670029` draws 19 numeric years after dropping a NULL first-year growth value while claiming 20 years; latest-complete-year coverage is not established. `vizcsv-6ed66df8328f06bc` correctly draws five wealth-stratum rates around 34%, but does not establish a pooled rich-versus-non-rich comparison. Neither image has the suspected 100× percentage scaling error.

The scale review therefore records **two semantic failures and two uncertain outcomes** among the four selected judge failures; three of their four PNGs faithfully render the supplied data. These judgments supplement the automatic evidence without changing scores, broadening golds, or treating the selected cases as a representative estimate of all chart quality.
