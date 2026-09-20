# Fixed development-twenty acceptance audit

These are development cases, not held-out evidence. The original seeded twenty
are frozen by ID in `dev20-expectations.json`; none is silently dropped or changed.
The original corpus CSV files remain unmodified.

## Three explicitly different experiments

| Mode | Input intent | Required outcome |
| --- | --- | --- |
| `original` | Original corpus question, no invented brief | 14 potential visual presentations, two text answers, one supplied city list, one unanswerable ratio, two unsupported maps |
| `handoff` | Same 20 CSVs, explicit data-agent request to present the supplied result | 19 rendered source presentations and one honest unsupported WKT response |
| `renderable` | The 19 supported handoffs plus one preregistered supported CSV | Exactly 20 rendered presentations; at least two are categorical tables, not quantitative charts |

The original questions do not uniformly request charts. A correct plain-table or
text answer can therefore fail the **new visual-delivery conformance standard**
without being an incorrect answer to the original question. Do not present the
stricter rescoring as original-task accuracy. The explicit handoff/renderable
prompts remove this ambiguity for subsequent chart experiments.

No case is empty. Important source constraints:

- `97280400c00748a7` asks for a male/female ratio but supplies only `male_count=0`.
  Its handoff asks for that count only; it does not claim to answer the ratio.
- `839d109a0db9ce25` supplies 1,000 WKT-only routes. Geometry stays local and the
  pinned renderer has no route-map type. Honest unsupported handling is **not** a
  verified chart. This case remains in both original and handoff suites.
- `ae315d3da67a2d11` asks for a route map but supplies 1,000 location points, not
  paths. Its handoff explicitly requests a coordinate scatter, not a route map.
- `e07c573241abdb02` originally demands text only, `عدد السكان (الرقم)`, with a
  source value of zero. Its handoff intentionally requests a count card instead.
- `85830f71807a6905` supplies only the city name نجران. The rendered handoff must
  use a table; adding a numeric measure would fabricate data.
- `ba0187c944a3f829` supplies 17 city/region names, not a verified census of every
  Saudi city. The handoff presents the supplied list, without claiming coverage.
- `c76808cc7a78dac8` has employment counts above population and rates above 100.
  The visualization must preserve the data, not invent a work-camp explanation,
  change values, clamp rates, or restart upstream research.

The separate renderable cohort adds `vizcsv-8b3fd04765e40d3a` (`total_count=0`).
Selection was preregistered before new model comparisons: the first ID outside
the original twenty in `random.Random(11).sample(manifest_rows, len(manifest_rows))`.
The handoff only displays that count. It does not invent the port/transport facts
requested by the original, incompletely answered upstream question. See
`dev20-additional.json` for the frozen selection and brief.

## What counts as passing

Rendered cases require all of:

- An actual published artifact and its image link in the final answer.
- Exact full source-row/column fidelity from the **persisted** artifact, not the
  lead's 50-row preview. The evaluator hashes the complete typed source table and
  records the original CSV hash. Leading-zero identifiers remain strings.
- Every case-required column visibly bound in the chart/cards, or present in a
  rendered table. A field merely saved in the source table is not visibly shown.
- A real local PNG with a valid signature and nonzero dimensions. PNGs for first
  and repaired renders are retained in the result's adjacent `-assets` directory.
- A final scoped visual-inspector pass with no material error. Timed-out,
  unavailable, stale or `revise` reviews do not meet that acceptance gate.
- Source-supported numeric claims, allowing supplied time/age context, explicit
  unit factors, exact category counts, and display rounding—but not new measures,
  invented totals, unsupported percent scaling, or fabricated precision.
- No upstream reanalysis or missing-data clarification for a prepared handoff.
- At most one draw, two design calls, two render calls, two inspection calls, and
  one publication; cached calls still count toward visible agent repetition.
- A per-case 60-second latency ceiling.

The summary distinguishes verified quantitative charts, verified rendered tables,
and honest unsupported/text handling. Quality gates are required before choosing
a faster solution. An inexpensive early failure is not a successful latency win.
`p50`, `p90`, `p95`, maximum and mean include all attempts, including failures.

Model usage is passed as one shared `RunUsage` and serialized even if the lead or
a specialist raises, so failures no longer lose their request counts. Saved stage
reports retain available per-stage model/request/time fields; unavailable timings
are not made up. Each run records case and runtime-code hashes and flags code
changes during the experiment. It is not a valid controlled comparison if the
shared runtime changes midway.

These gates do not mathematically prove that every chart is aesthetically correct.
Inspector approval is model evidence; final PNGs still need independent visual
spot checks and representative labelled reviewer evaluation. Numeric text
matching checks numeric fidelity, not every possible false nonnumeric statement.
The existing answer matcher is conservative; any disputed failure must be audited
against the saved response before drawing a model-quality conclusion.

## Commands

Run exactly the renderer-supported twenty, through the same lead/team as the app,
without UI and with bounded concurrency:

```bash
uv run python -m evals.lead.run --cases evals/lead/empty-cases.json \
  --dev20 renderable --concurrency 2 --out evals/lead/results-variant.json
```

Use `--dev20 original` or `--dev20 handoff` for the corresponding adversarial/mixed
twenty. All twenty IDs and disposition gates are fixed before model execution.
Per-role environment overrides select experimental models without modifying the
persisted application configuration. Keep prompts, dataset, concurrency and
runtime hash identical for a model comparison; isolate prompt experiments from
model experiments and repeat paired runs before claiming causal superiority.

Posthoc scoring of the previous comparison is offline:

```bash
uv run python -m evals.lead.rescore_dev20 \
  evals/lead/results-deepseek-current-harness-dev20.json \
  evals/lead/results-claude-sonnet45-harness-dev20.json
```

The stored output is `dev20-baseline-rescore.json`. It evaluates a stronger visual
delivery contract than the old generic `answered` gate. Earlier `cases_ok` values
of 16/20 and 15/20 did not mean that many verified, fast charts: they accepted text,
tables and even clarification, lacked source fidelity gates, and undercounted
request usage on exceptions. The lead remained GLM in both variants; errors in
final prose cannot automatically be attributed to the designer model.

Under the explicit new gates, the saved DeepSeek-designer run meets 10/20 case
dispositions, including six fast reviewed visual presentations; the saved
Claude-Sonnet-4.5-designer run meets 9/20, including seven visual presentations.
These are posthoc conformance counts with the intent caveat above, **not** a new
real-model A/B test. Two DeepSeek failure turns and three Claude-variant failure
turns lack true usage records; the old request totals are incomplete. The updated
runner will retain shared usage even on those failures.

Confirmed illustrative issues in those records include a final answer changing
the supplied `percentage=0.00` into approximately `0.0005%`, a district count chart
omitting the also-requested percentage, repeated identical rate-chart renders,
and published charts whose visual review still requested a revision. These are
specific failures to regress, not evidence that one vendor is generally smarter.

Selected saved PNG IDs for first-render versus final-render inspection:

| Designer variant / case | First PNG ID | Final PNG ID |
| --- | --- | --- |
| DeepSeek / donut `6eff7ae46ebb4edf` | `41d1f660b68b` | `918988a26072` |
| Claude / donut `6eff7ae46ebb4edf` | `430e812e95d2` | `6adbe47359f2` |
| Claude / grouped regions `2177430e3e44a9a3` | `29ebb80ec6e2` | `5a95a391fd14` |
| DeepSeek / city counts `c76808cc7a78dac8` | `d2f3a69276b6` | `4ede9191452a` |
| Claude / city counts `c76808cc7a78dac8` | `52a24b629cee` | None published |
| DeepSeek / per-100 rate `61793ff199102633` | `1587ca76d66c` | Same PNG |
| Claude / district count `f6687502449585a5` | `ca165f82b0d5` | Same PNG, required percentage unbound |

Files are under `results-<variant>-harness-dev20-assets/corpus-vizcsv-<case>/renders/<PNG ID>/chart.png`.
