# Designer isolation experiments — 2026-09-17

## Method and limits

66 real designer runs, at most two model requests in flight, with the same six
saved source reports across three models. The reports cover a percentage metric,
region/gender comparison, violations plus percentage, a wide one-row percentage
comparison, population/employment comparison, and delivery coordinates. Each run
saves its exact prompt, full messages, result, source hash and real rendered files.
Partial metadata annotations are merged by exact existing column name before
dispatch so the previous lead-tool annotation rejection cannot bias the comparison.

These are **designer execution/binding tests, not 66 full-agent correctness tests**.
An image being produced is not proof that it answers the user correctly. Model
providers were not fixed, so timings include routing, cache and provider variation.
The first sandbox-only attempt had connection errors and is excluded entirely.

## Results

| Prompt snapshot | Lead guidance | Model | Rendered / 6 | Mean design s | Median s | Completed model requests |
|---|---|---|---:|---:|---:|---:|
| Original | Saved detailed direction | DeepSeek V4 Pro | 3 | 15.15 | 15.35 | 11 |
| Original | Saved detailed direction | GLM 5.3 low effort | 6 | 10.20 | 8.40 | 11 |
| Original | Saved detailed direction | Claude Sonnet 4.5 | 6 | 11.44 | 11.29 | 9 |
| API clarification v1 | Saved detailed direction | DeepSeek V4 Pro | 4 | 14.28 | 12.15 | 16 |
| API clarification v1 | Saved detailed direction | GLM 5.3 low effort | 6 | 14.42 | 10.41 | 8 |
| API clarification v1 | Saved detailed direction | Claude Sonnet 4.5 | 6 | 11.55 | 10.29 | 9 |
| API clarification v1 | Intent only | DeepSeek V4 Pro | 2 | 24.10 | 18.43 | 12 |
| API clarification v1 | Intent only | GLM 5.3 low effort | 5 | 11.71 | 5.43 | 6 |
| API clarification v1 | Intent only | Claude Sonnet 4.5 | 5 | 8.51 | 8.06 | 7 |
| Final frozen runtime, default routing | Intent only | GLM 5.3 low effort | 6 | 8.51 | 6.69 | 7 |
| Final frozen runtime, latency routing | Intent only | GLM 5.3 low effort | 6 | 7.99 | 5.73 | 6 |

All 66 runs preserved the input source report. Timeouts count as failures and
remain in mean/median latency. The framework's request count counts completed
responses, not all dispatched attempts: three runs timed out at 45 seconds,
including GLM's intent-only population/employment case. The captured messages
distinguish that from zero work, but raw ModelRequest counts are not outbound
counts: a successful output tool adds a terminal acknowledgement never sent to a
model. The replay now uses a counting Model wrapper for future runs; tests cover
both an in-flight timeout and that terminal acknowledgement. Previous result
files retain raw message counts, not retroactively invented counter measurements.

The v1 run was started before the final diagnostic wording correction and grouped
sort clarification. Its exact captured instructions are authoritative; it is not a
test of every line of the final prompt. The final runtime changes require the
integrated lead evaluation.

## Routing experiment on the final frozen runtime

The 12 paired runs changed only `provider.sort`: default versus `latency`, with
identical GLM low-effort settings and intent-only inputs. Both variants rendered
6/6. Latency priority improved the mean by 0.53 seconds but not the maximum
(17.35 versus 16.81 seconds). Only the population/employment pair used different
providers: BaseTen with latency routing at 3.42 seconds, versus Inceptron by default
at 5.70 seconds. Other pairs reached the same providers. This small sample does
not establish that routing fixes the tail. All 12 succeeded, so the 13 completed
responses were 13 completed framework model invocations; opaque SDK/provider
retries are not measured.

OpenRouter documents default price-prioritized load balancing and the explicit
`latency` sort; `require_parameters` alone is not a latency-routing preference.
[Official provider-routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection)

## Findings

1. **The designer model matters, but is not the only cause.** Identical inputs
   produced unsupported DSL keys, missing required percentage bindings, and wrong
   card roles in DeepSeek. Stronger instructions did not reliably remove these
   errors. GLM and Claude were markedly more reliable on these six selected cases.
   This is a limited diagnostic sample, not a universal model ranking.
2. **Lead micromanagement can make a valid request harder.** The same wide
   percentage report took GLM 25.21 seconds with detailed bar/axis/color instructions
   but 1.60 seconds with the original intent; the latter produced two correct KPI
   cards, preserving all six supplied fields. However, another intent-only GLM
   case timed out, so shorter guidance is not a guarantee of low latency.
3. **The harness hid multiple errors behind sequential retries.** A semantic error
   such as unsupported `zero` previously prevented checking missing required
   columns until the next output. Validation now reports both defects together.
4. **The fold diagnostic was misleading.** It suggested `fold` as the remedy for a
   missing category even when `fold` was already present. It now explains that
   category/time bindings are not automatic. No new fold or data semantics were added.
5. **A real renderer localization bug was confirmed from the image.** GLM could
   compare a one-row wide result by binding the generated series as category, but
   the resolver applied source `columnLabels` only to its group legend. The axis
   displayed raw `wealthy_female_pct` / `wealthy_male_pct`. The labels now apply to
   both surfaces; a re-render shows Arabic labels with unchanged 19.94% and 20.02%.
6. **An unnecessary ordering request generated an unfixable repair target.**
   Grouped `sort value desc` sorts by the sum of series, not by one selected series.
   The lead invented an employed-only order not requested by the original question.
   Correct API guidance and less prescriptive delegation are preferable to loops.
7. **A scatter plot is not a route map.** The baseline GLM delivery-coordinate image
   has longitude on X and latitude on Y, correctly labeled with matching ranges.
   The earlier axis-inversion critique is not supported by that image. Its prose
   nevertheless promises routes and city/price tooltips that are not encoded.
   Rendering, visible defects, and answering user intent need distinct checks.

## Recommendation

Use GLM 5.3 with low thinking effort as the open-weight designer finalist for the
integrated 20-case comparison, and retain Claude as the closed-model control.
Delegate intent plus necessary bindings, not unsupported chart-specific features.
Do not change defaults or claim 20/20 based on these isolated results. A full run
must still verify publication, relevant measures, real images and latency tails.

## Artifacts and verification

- `results-isolated-three-models-saved-online.json`: original-prompt 18-run replay.
- `results-isolated-api-hints-two-guidances.json`: 36-run guidance comparison.
- `results-isolated-glm-routing.json`: 12-run final-runtime routing comparison.
- Adjacent directories contain each successful run's PNG, HTML and render config.
- `results-isolated-render-fixes/wealth-labels/chart.png`: same saved GLM spec
  re-rendered after the localization fix, inspected directly.
- Targeted tests: 449 passed (`test_agent.py`, `test_check.py`, `test_resolve.py`,
  `test_designer_replay.py`).
