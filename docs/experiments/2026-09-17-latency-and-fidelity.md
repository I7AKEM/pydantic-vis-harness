# Visualization latency and fidelity experiments — 2026-09-17

Follow-up: the user subsequently approved the two blocked model arms and increased
the experiment to fifty tasks per arm. The unchanged initial twenty are segment
one; thirty newly frozen cases are segment two. See
`evals/lead/parallel50-v3-protocol.md` and the continuation report
`docs/experiments/2026-09-17-parallel50.md`. The historical results below are preserved.

## Status and acceptance

**The 20/20 goal has not yet been demonstrated.** Model-output validity, a successful render,
and a visually correct answer are different results. Do not call a clarification, an unreviewed
image, or an explicitly limited table fallback a verified chart.

Completed evidence now includes **one integrated 20-case run** and **eight fixed-image reviewer
experiments of 20 cases each**. The integrated GLM/concise candidate scores **16/20**, after an
audited evaluator-only correction; its original result remains untouched. The two production-prompt
model-comparison reruns have not launched because the permission layer rejected the subagents'
requests. Renewed, explicit data-sharing confirmation is pending. The earlier six-case designer
probes below are exploratory evidence, not completed 20-case experiments.

Experiments use the existing OpenRouter credentials and CLI/API path, not the chat UI. CSV cells
are authoritative and unchanged. Variants retain exact inputs, model messages, elapsed time and
local PNGs. The revised lead evaluator checks full-source row signatures, required visible
bindings, final image existence, successful visual inspection, delivery, repeated calls and
numeric captions. It reports latency and quality separately. This follows the principle of
task-specific success criteria and controlled comparisons in the [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

The original seeded twenty are heterogeneous: they include an explicitly text-only request, a
city-name answer, a missing-ratio case and unsupported route maps. The separate `handoff` experiment
explicitly asks to present the supplied result and is **not** evidence that the original research
question was answered. Its geometry-only case remains unsupported. The `renderable` cohort adds a
preregistered additional source presentation instead of claiming that a WKT diagnostic is a chart.
Rendered tables are reported separately from quantitative plots.

## Isolated designer baseline (18 real runs)

The same six recorded first-design inputs were replayed through each model, with at most two calls
in flight. Metadata annotations were merged by exact existing column name to bypass the unrelated
lead tool's all-columns requirement. No designer received a different source table.

| Designer | Valid spec + real render | Mean design time | Completed model responses |
| --- | ---: | ---: | ---: |
| GLM 5.3 | 6/6 | 10.20 s | 11 |
| Claude Sonnet 4.5 | 6/6 | 11.44 s | 9 |
| DeepSeek V4 Pro | 3/6 | 15.15 s | 11 |

These are executable/binding results, **not six-of-six visual correctness scores**. Evidence:
`evals/designer/agent/results-isolated-three-models-saved-online.json` and its adjacent image directory.
The similarly named file without `-online` contains connection failures and is not model evidence.

## API hints and delegation experiment (36 real runs)

Each model received the same six sources with either the saved detailed lead direction or the
original intent alone. Instructions added concrete executable card/fold/label guidance and combined
diagnostics. Exact prompts are saved; this run loaded an intermediate instruction snapshot before
the final fold-wording correction, so it must not be presented as a test of the final prompt verbatim.

| Designer | Direction | Valid spec + real render | Median design time | Maximum |
| --- | --- | ---: | ---: | ---: |
| GLM 5.3 | Saved detailed | 6/6 | 10.41 s | 30.78 s |
| GLM 5.3 | Intent only | 5/6 | 5.43 s | 45.00 s |
| Claude Sonnet 4.5 | Saved detailed | 6/6 | 10.29 s | 19.36 s |
| Claude Sonnet 4.5 | Intent only | 5/6 | 8.06 s | 12.30 s |
| DeepSeek V4 Pro | Saved detailed | 4/6 | 12.15 s | 34.65 s |
| DeepSeek V4 Pro | Intent only | 2/6 | 18.43 s | 45.01 s |

Intent-only GLM produced a correct two-card wealthy-percentage specification in 1.60 s versus
25.2 s for detailed instructions on that source. But another intent-only GLM request timed out at
45 s without a model response. This does not establish a universal speed improvement. Completed
response counts do not count an outbound request that timed out before returning.

Evidence: `evals/designer/agent/results-isolated-api-hints-two-guidances.json`.

## Confirmed harness and input problems

- The lead rejected annotations for two columns of a six-column table before the designer ran.
  It now permits an exact-name subset while preserving other columns, source cells and lineage.
  Independent review also caught a synthesized `not stated` denominator overwriting a known share
  denominator during a partial annotation. The existing definition and partition are now retained.
- Failed visual repairs cleared the preview, allowing a later call to masquerade as an initial
  design. The persisted repair attempt now prevents that bypass.
- A lead could end with a promise despite a usable saved design. A bounded output validator now
  returns the unfinished-delivery decision to the lead; it does not call specialists or impose a
  fixed workflow. Irrecoverable work can explicitly deliver an unverified source-table fallback.
  Direct design/render continuations are included; unrelated informational follow-ups are not.
- A geometry-only source was repeatedly retried. The technical limit is now saved and returned as
  terminal diagnostics without exposing geometry cells to a model. Rephrasing the same immutable
  source does not bypass that cache. API resume preserves terminal status without another model run.
- Some resolver errors escaped tool diagnostics. They now return to the lead as render failures.
- Folded column labels were applied to series but not to a category bound to that generated series
  field. The same specification now displays its approved Arabic labels; source values are unchanged.
- Lead-generated metadata incorrectly labelled a rate per 100 as `%`. A formatter-only repair cannot
  fix incorrect metadata. The concise candidate instructions describe that distinction.
- A real integrated GLM attempt emitted `innerRadius 60`, then `65`. The pinned renderer clamps
  this dimensionless parameter to `[0,1]`, producing a hairline ring with clipped text. The executable
  spec now enforces that actual API range and finite values, with `0.6` as an actionable example;
  values are rejected rather than silently rescaled. Capabilities expose the units/bounds. Valid
  endpoint values remain legal: this is API validation, not a new aesthetic policy.
- Static tables used a 450px viewport. Pinned S2 `autoFit` only crops empty space; it does not
  expand the viewport to show hidden rows. The 17-row regional/city table omitted its final three
  rows from the PNG even though input counts claimed all 17. After the integrated run, default
  table height was corrected to fit every row; explicit undersizing now returns a diagnostic.
  A 2400px resource limit returns an honest technical limitation instead of sampling. An exact
  local replay now paints all 17 rows, including جدة, مكة المكرمة and نجران. This does **not**
  retroactively change the integrated run's failure. See `evals/lead/table-completeness-probe/README.md`.

A separate, text-only live terminal-error regression first exposed another failure: the lead tried
to publish the unsupported WKT source, and an argument retry caused it to repeat publication until
the run failed. Publication now returns the existing failed outcome, with no fabricated artifact.
The follow-up real GLM run completed in **7.68 s, three model responses and two tool calls**, explaining
the unsupported renderer boundary honestly. It generated and transmitted no images or geometry rows.
This is a **passed failure-handling test, not a successful chart**, and not part of the 66 designer runs.
Evidence: `evals/lead/results-terminal-geometry-regression-v2.json`. Further API-resume and annotation
hardening was checked locally after that run; it was not a second complete 20-case model evaluation.

## Visual reviewer evidence

Manual review of the saved first/final images confirmed false rejections of correctly bound longitude
and latitude, employment and population, and a regional bar that was visibly present. Other defects
were real: clipped donut labels, driver-chart axis titles swapped in the initial render, and `%` on a
rate-per-100 axis. Two Claude regional PNGs were byte-identical despite different render IDs.

The fixed-image experiment completed **eight arms × 20 inputs = 160 case-trials**, including two
timeouts counted as failures. All arms use the same frozen PNGs and labels: ten clean and ten
defective images. Original manifests, prompts, tool schemas, settings and raw findings are retained.
Historical labels are not changed to make a scoped inspector look better.

| Reviewer arm | Verdict agreement | Clean accepted | Bad rejected | Mean time |
| --- | ---: | ---: | ---: | ---: |
| Gemma baseline, thinking off | 12/20 | 4/10 | 8/10 | 1.27 s |
| Gemma named rows, off | 15/20 | 7/10 | 8/10 | 1.16 s |
| Gemma grounded scope, off | 14/20 | 6/10 | 8/10 | 1.38 s |
| Gemma summary-first schema, off | 13/20 | 7/10 | 6/10 | 1.12 s |
| Claude Sonnet 4.5 named, off | 15/20 | 10/10 | 5/10 | 4.83 s |
| Qwen 3.8 27B named, off | 14/20 | 5/10 | 9/10 | 14.92 s |
| Gemma named, low thinking | 15/20 | 7/10 | 8/10 | 8.56 s |
| Gemma grounded, low thinking | 17/20 | 10/10 | 7/10 | 8.16 s |

Correct rejection is not necessarily correct diagnosis. The highest-agreement arm correctly
identifies only **four of ten actual labelled defects**; three other rejections cite imaginary
RTL problems, and it accepts the clipped donut, incomplete table and wrong-unit chart. The named-off
Gemma arm identifies seven actual defects, despite lower verdict agreement. Claude removes the
clean-chart false rejections in this sample but misses five defective images. These controlled
results do not support blaming the open model alone or switching reviewer defaults.

No reviewer candidate has been adopted, and the full 89-case labelled-set validation has not run.
Details, confusion matrices and grounded examples: `evals/reviewer/scope-fixed20-report.md`.

## Integrated 20-case experiments

The intended comparison comprises three configurations on the same frozen
`renderable` handoff cohort, with one case in flight per configuration:

1. GLM 5.3 lead, designer and fallback; production lead instructions; Gemma visual inspector.
2. Same team except Claude Sonnet 4.5 designer and fallback; same production instructions.
3. Same all-GLM text team as (1), with `evals/lead/concise-instructions.md`; same Gemma inspector.

Fallback model overrides prevent silent cross-model substitution. Source/case/runtime hashes,
all failures, original/final images, review outcomes, calls and latency are retained. The production
instruction comparison changes only designer model; the GLM pair changes only lead instructions.
All use existing provider routing. Cross-case provider/load variability remains a limitation.

The first attempts were aborted, **not counted as completed twenty-case comparisons**. A fallback
artifact had `spec: null`; the evaluator called the spec parser and lost its final aggregate output.
The corrected runner now scores that fallback honestly, retains messages and usage on scoring errors,
writes an atomic checkpoint after every case, separates application/evaluator fingerprints, and imposes
a 120-second per-turn evaluation deadline. The pass SLA remains 60 seconds; timing out is a failure.
Only arm 3 completed its restarted 20-case run as `results-parallel20-glm-concise-v2.json`.
The permission layer rejected the other two subagents' launches before execution; quoting the
parent's consent did not satisfy its trusted-context requirement. They have **no v2 results** and
must not be included in a model A/B comparison. No permission workaround was used.

### Completed all-GLM concise candidate

- Source-cell fidelity: **20/20**. Rendered artifacts delivered: **19/20**; the remaining case
  delivered an explicit source-table fallback, not a verified PNG.
- Overall gates: raw **10/20**, audited rescore **16/20**. Numeric fidelity is **19/20**.
- Median latency **10.36 s**, p95 **28.17 s**, maximum **66.17 s**; **181 completed model requests**.
- Same frozen application for all twenty:
  `fe222dcea1e46f5287ec3986d8979570133f3de7ff2783f1e5d5b89f6ed7ebe3`.

The run made 23 successful design delegations (27 designer model responses), 23 image inspections
(23 reviewer responses), and 131 other/lead model responses. Design-stage wall time totalled 131.50 s;
review-stage time totalled 20.49 s. These are components of, not additions to, the 295.22 s summed
case duration. The longest unnecessary repair followed a false review finding; replacing the
designer alone cannot establish that this failure is fixed.

The numeric scorer initially counted digits in bare image URLs and URL-shaped link labels as
claims about the data. A tested URL-token correction fixes seven false numeric flags and improves
six overall cases. Ordinary numeric link labels and real incorrect values remain checked. A separate
rescore retains every original field except the seven numeric booleans, recalculated summary and
added audit metadata. The raw JSON and PNGs are unchanged; no model calls were repeated or removed.
Evidence: `evals/lead/results-parallel20-glm-concise-v2-rescored.json` and its `-audit.md`.

The four remaining failures are:

1. Donut: a real clipped-label first render is repaired, but Gemma falsely rejects the final
   legend/sector mapping. The original failed review remains a failed gate.
2. Region/city table: false swapped-header findings lead to a source-table fallback. The PNG also
   genuinely hides the last rows, which the reviewer misses; this separate runtime bug was fixed
   only after the experiment, as documented above.
3. Age groups: Gemma rejects a correctly bound RTL chart, causing an unnecessary 36.65-second
   redesign and a **66.17-second** total, above the unchanged 60-second pass SLA.
4. Gender: the final answer transcribes **49.5571768707483%** instead of source
   **49.5578231292517%**, despite a correct chart. This is a genuine answer failure, not a URL artifact.

Deterministic passing gates do not independently certify every image pixel. No claim of universal
chart correctness or a 20/20 result is made. The next controlled comparison must freeze the new
table-completeness runtime for every arm; a run on that runtime is not directly a same-harness
model-only comparison with this completed, pre-fix candidate.

Independent local visual inspection covered all twenty cases, including the failed table's saved
attempts. It found no additional visible numerical/binding corruption. It did identify a presentation
warning: the `percentage_saudi=100` card lacks a `%` suffix because its supplied metadata unit is
null. This warning is separate from the unchanged strict score. The 1000-point coordinate scatter
cannot be checked point-by-point visually because of overlap; full-source/config checks and visible
image inspection are complementary, not interchangeable. Per-case evidence and uncertainty are in
`evals/lead/manual-audit-glm-concise-v2-0-9.md` and `evals/lead/manual-audit-glm-concise-v2-10-19.md`.
Several images also use English despite the Arabic brief. This is documented as a language-consistency
limitation; the frozen cohort did not impose a language gate, so the 16/20 score is not a claim of
complete Arabic-localization compliance.

Post-table-fix application fingerprint:
`096451ded74efcdae3058d3a635924fbc66b41c4796c978706078037f91755a6`.
Post-URL-fix evaluator fingerprint:
`5914d8a0037305557f9a822879261902b4c00172c58289717cdf62478c848403`.

## Trace corroboration and routing

Logfire MCP was queried directly. The newest five available lead traces were from September 16,
15:27–15:42 UTC; they are not the newly captured CLI experiments. Their total durations were
98.98, 46.21, 98.68, 43.96 and 16.54 s. Individual render tool calls took roughly 0.44–0.84 s.
One 98.68 s trace spent 75.53 s in ten GLM lead calls; another spent 66.81 s in a single Flash
designer delegation. Model/provider latency and repeated turns, not PNG generation alone, dominate.

The current GLM settings require parameter support but do not explicitly sort providers by latency.
[OpenRouter's provider-routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection)
describes price-weighted default routing and explicit `sort: "latency"`. A separate paired routing
experiment tested that option without changing production defaults. On the final designer runtime,
both arms rendered all six fixed inputs. Default routing averaged 8.51 s (median 6.69, maximum 16.81),
while latency routing averaged 7.99 s (median 5.73, maximum 17.35). Only one pair changed downstream
provider. That is a small average improvement, **not evidence that the latency tail was fixed**.
Evidence: `evals/designer/agent/results-isolated-glm-routing.json`. Across these three experiments,
66 designer runs were executed; the original six source cases were reused, not 66 independent cases.
Short samples cannot establish reliable tail-latency guarantees.

## Local verification

- Final full Python suite, including URL/table patches: **1753 passed** (96.74 s;
  one dependency deprecation warning).
- Final targeted verification: **103 evaluator tests**, **445 table/resolver/render tests**,
  and **24 reviewer tests** passed. These overlap the full suite; they are not additional cases.
- Deterministic designer evaluation after the table patch: **40/40**.
- New regressions cover partial annotations, failed-repair budget bypass, geometry-only retries,
  premature final promises, resolver diagnostics, folded labels, and strict evaluation accounting.
- No new default model/prompt is selected solely from these isolated results. No commit or cleanup
  of older evidence has been performed while full end-to-end acceptance remains outstanding.
