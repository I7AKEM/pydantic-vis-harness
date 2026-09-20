# GLM production v3: first 20 cases and failure audit

Run completed on 2026-09-17 local time. This is the first, unchanged 20-case
segment of the subsequently requested 50-case-per-model comparison. It is the
fixed `renderable20` **data-agent handoff** cohort, not a claim to answer the
original upstream research questions. No cases were dropped or rerun.

## Configuration and integrity

- Raw result: `results-parallel20-glm-production-v3.json`.
- Raw SHA-256: `b8b286de36bd99afe18efa8419b9fe2b6132401a3f92a1b0c0357e1c23268af2`.
- Evidence: adjacent `results-parallel20-glm-production-v3-assets/`, including
  all 20 `case.json` checkpoints, source signatures, raw messages, and 21 PNGs.
- All text roles and designer fallback: `openrouter:z-ai/glm-5.3`.
- Reviewer: `openrouter:google/gemma-4-31b-it:nitro`.
- Production lead instructions, no `--instructions` override; lead effort `low`.
- Process-only model overrides; repository environment and default models untouched.
- Concurrency 1 within this arm; separate Claude arm ran concurrently.
- Per-case pass SLA 60 seconds; watchdog 120 seconds; framework limit 18 model
  requests. Failed/capped attempts are included in the denominator and usage.
- Application SHA-256: `096451ded74efcdae3058d3a635924fbc66b41c4796c978706078037f91755a6`.
- Evaluator SHA-256: `5914d8a0037305557f9a822879261902b4c00172c58289717cdf62478c848403`.
- Combined SHA-256: `10de585940ee00e4271fbdedee20aea48359bfc7fc1915923cdbbeb8d2e1d6df`.
- Case definitions SHA-256: `8541cb0af6a7f19a8acde058cef7f785e00f16799f45d0cee1492d6102eeb477`.
- Application and evaluator hashes matched before and after the run; all three
  `*_changed_during_run` flags are false. No runtime, evaluator, prompt,
  dependency, or configuration edits were made by this experiment worker.

## Recorded result

| Measure | Result |
|---|---:|
| Strict end-to-end passes | **12/20** |
| Completed outcomes | 17/20 |
| Delivered PNG evidence | 15/20 |
| Reviewer gate passes | 13/20 |
| Source-fidelity gate passes | 17/20 |
| Answer-fidelity gate passes | 15/20 |
| Repetition gate passes | 16/20 |
| Cases within 60-second SLA | 20/20 |
| Model requests, including failed cases | 202 |
| Mean latency | 16.60 s |
| Median latency | 15.13 s |
| p95 latency | 31.23 s |
| Maximum latency | 34.14 s |
| 120-second timeouts | 0 |
| Framework request-cap failures | 3 |
| Explicit source-table fallbacks | 2 |
| Questions sent back to data agent | 0 |

CLI exit status 1 means failed cases, not an aborted run. Every case has a saved
result. All cases produced at least one local PNG, but a local PNG is not the
same thing as a delivered, reviewed final response. The three request-cap cases
have no final reply. The two fallbacks intentionally discard their rendered PNG
from the published artifact. The source-fidelity gate failures in capped cases
do **not** demonstrate changed source cells: the evaluator lacks a final selected
artifact. Persisted artifacts in the capped city/employment and education-rate
cases still match their original typed source signatures.

## Independent inspection of all eight failed cases

The actual first and last available PNGs for every failed case were opened
locally with `view_image` and compared with source rows, specs, reviewer findings,
and tool results. This audit does not rewrite any recorded gate or verdict.

| Case suffix | Available render(s) | Evidence and failure classification |
|---|---|---|
| `6eff7ae46ebb4edf` | `cc842f40687c` | **True initial visual defect plus blocked repair.** Inside donut labels are genuinely clipped against the white background. Gemma correctly notices clipping but assigns `owner=renderer`. The lead requests `labels off`; `chart_capabilities` explicitly offers that repair. The harness nevertheless blocks both redesign calls because only `owner=designer` permits a repair. The lead delivers a source-table fallback without the requested donut. The numeric gate also sees digits in the quoted example of clipped text; the missing chart already makes this a genuine failure. |
| `ba0187c944a3f829` | `9430e883b1ca` | **Reviewer false positive causes unnecessary fallback.** Static PNG contains all 17 rows, including the last three cities جدة, مكة المكرمة, and نجران. Region values sit under المنطقة and city values under المدينة. Gemma incorrectly says columns are swapped. The one attempted redesign is equivalent and the lead discards the correct image. There is no row-clipping defect in this PNG. |
| `9e75e9ae40758227` | `8c2d14f4a1ab` | **Inconsistent reviewer output.** All ten values, category pairs, and legend mappings are correct; categories progress right-to-left. Gemma emits an R-1 `level=error`, then states within the same finding that the mappings are correct and no R-1 error exists. A separate legend-placement warning is non-material. The lead publishes the correct PNG; the structural review gate remains failed. |
| `45980b90faceca07` | `8ec5554e68da` | **Inconsistent reviewer output.** The two cards correctly show 19.94% / 20.02%, with the four exact count/total supports. Gemma marks 37,438 as an error while immediately confirming that 37,438 is correct and retracting the concern. The PNG and final numbers are correct; the review gate remains failed because the finding is still `level=error`. |
| `2571f37808cda8e2` | `7bceb9c275ec` | **Evaluator false positive, not a model numeric typo in this run.** The PNG correctly shows 50.44% for F and 49.56% for M. Final prose/table preserve exact source percentages 50.4421768707483 and 49.5578231292517, and counts 1483 and 1457. The literal column heading `count_under_30` is parsed as an unsupported numeric claim of 30. Read-only diagnostic substitution of that heading with `count_under_thirty` makes `answer_numbers_match` pass. Raw result and evaluator remain unchanged. |
| `c76808cc7a78dac8` | `b9d79cb051df` | **True initial overlap plus repair-routing/control failure.** Population-value labels visibly overlap city names in the grouped horizontal bars. Gemma assigns `owner=renderer`; four scoped `labels off` repair attempts are blocked despite supported capability guidance. The lead then publishes the flawed preview, opens a fresh `revise` request, and obtains a replacement design before reaching 18 requests. There is no final reply and no repaired PNG. Source cells in the persisted published artifact remain exact. |
| `2bc0cfa90c65f142` | First `84faa7d9d93f`, last `4f368873e010` | **False RTL-order alarms trigger waste until the request cap.** Both PNGs correctly show مكة المكرمة=6, الدرعية=5, جازان=4, جدة=4, الباحة=4, descending when read right-to-left. Gemma twice calls the order ascending. The lead also passes an `rq_` ID to `revise`, receives a valid diagnostic, then unnecessarily changes `sort none` to `sort value desc`; the visible image is unchanged. Further capability/repair attempts consume the remaining budget. No final artifact/reply is delivered. |
| `61793ff199102633` | `0411df94b407` | **Overstated review claim plus repair-routing/control failure.** The chart correctly pairs 13.19 and 7.17 with the two education groups and uses rate-per-100, not percent. X ticks repeat a long unit and rotate vertically; this is cumbersome, but the asserted overlap is not visible in the actual PNG. Gemma assigns `owner=renderer`. Four width/format repair attempts are blocked; the lead publishes, opens `revise`, and obtains a new design before the 18-request cap. No final response or replacement PNG is delivered. |

## Table viewport qualification

A table taller than an interactive viewport can legitimately scroll. That is
different from claiming every row is visible in a static PNG. In this run the
region/city PNG is 1598×1084 and actually contains all 17 rows; its failure is
neither a normal scroll viewport nor static clipping. The audit does not convert
ordinary scrolling into a defect and does not retroactively change any score.

## What this run establishes, and what it does not

- Wall-clock latency is bounded and below the 60-second pass SLA for all 20.
  That does not make a fast capped failure successful.
- Multiple failures are directly caused by an interaction between reviewer
  findings and the harness's owner-specific repair gate. The tool announces a
  supported repair, but its execution is blocked solely by the review owner.
- The model sometimes keeps trying after a blocked/limited repair, including
  publishing and opening `revise` within the same run. The global Pydantic usage
  budget terminates it, but the caller then receives no final reply.
- Gemma's false RTL/column alarms and unretracted structured error fields are
  material failure sources even when the initial image is correct.
- The gender answer failure is independently diagnosed as an evaluator issue;
  it is not the precision typo seen in the earlier concise-v2 experiment.
- No gate was manually upgraded. No new default model, repair strategy,
  reviewer prompt, commit, or cleanup is justified by this partial 50-case
  comparison. The remaining 30 cases require their own frozen manifest and run.
