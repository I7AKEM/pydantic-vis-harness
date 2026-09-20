# Real50: one GLM team, scoped Gemma review, frozen harness

## Protocol and consent

The user explicitly authorized the previously blocked transfer of evaluation
images and reference rows to Gemma through OpenRouter on2026-09-17. This is a
single-configuration harness validation, not a GLM/Claude comparison or prompt
optimization. Production `.env`, model defaults and instructions are unchanged.

The frozen50-case development bank supplies exactly48 rendered-presentation
tasks and2 technical-boundary tasks. It is not a blind heldout set. Task order,
original source CSVs/briefs and expectations are retained. The separately versioned
semantic overlay applies; raw historical results are never rewritten.

Configuration for this process only:

- Lead, profiler, analyst, designer and explicit fallback: `openrouter:z-ai/glm-5.3`.
- Inspector: `openrouter:google/gemma-4-31b-it:nitro`, thinking disabled,
  temperature0. GLM uses the existing low-effort settings.
- Advisor disabled. No other model is a fallback. Production's different saved
  designer/fallback defaults were not edited.
- Serial execution,50 attempted tasks maximum,120s turn watchdog,60s SLA,
  existing18 shared model-request and16 tool-call limits.
- Actual Pydantic AI tools and local Node renderer, through final response;
  no UI automation and no fake models. No changes to application/evaluator
  inputs while this run is active.

Evidence directory:
`evals/lead/results-maturity50-glm-gemma-20260917-v1/`.
Each completed rollout preserves candidate text, full local checkpoint, all
rendered PNG/HTML/config files and a separate machine-contract score. The final
`result.json` is written only after the batch completes.

Application hash: `6dd8a41fcd6172e8e8fc0a5cc8a66b50c921c29156889ff3c609689a2e7833b9`.
Evaluator hash: `411b63112ce4dc93580ef119aa21af5b3d73cd2e72d0139f77f15d267055443a`.
Lead instructions: `699bfbc64a2d82b4f36092d617ef569371ce81d6535c1d8f4b8f2a5ddee81ba1`.
Complete optimization/input guard: `e644ecbe86e61279992d763a2aaf8465d958a73f7397681b2af123ccaf6cc331`.
These values are also recorded per case with its exact effective-contract hash.

## Timing and independent audit

Logfire SDK instrumentation is enabled for this process under service
`vis-eval-maturity50-glm-gemma-v1`, with `include_content=False` and
`include_binary_content=False`. The existing `vis-harness` project receives
timing, token and tool metadata, not CSV/message/image content. Queries use the
Logfire MCP connector. Lead run IDs in saved messages link cases to root spans;
timing sums must not double-count nested tools/specialists.

First lead span began at2026-09-17T00:56:13.070615Z. The first case took81.49s
with8 model requests, even though it had no repair loop. Its renderer took0.348s,
designer4.914s and Gemma1.541s; most waiting was in the lead's GLM requests. One
37-output-token request took28.264s and reported0 reasoning tokens. This localizes
that delay to the model-request boundary, not to rendering or evidence of long
reasoning. It does not by itself distinguish provider queuing, inference,
networking or retry internals.

Independent local audits inspect exact briefs, saved values/specs, **every first
and repair PNG**, final delivery and reviewer findings:

- [Cases01–17](2026-09-17-maturity50-audit-01-17.md).
- [Cases18–34](2026-09-17-maturity50-audit-18-34.md).
- [Cases35–50](2026-09-17-maturity50-audit-35-50.md).

These are agent audits with explicit uncertainties, not human gold labels.
Scrollable table viewports, complete accessible source data and static PNG
glyph/row coverage are judged separately. A model inspector's pass or a correct
final chart after a false rejection does not establish a correct trajectory.

The protocol follows [OpenAI Docs evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices#how-to-read-evals)
by separating task-specific metrics from independent judgment and preserving
failures as future regression evidence.

## Completed result

All50 cases were attempted once; the process exited successfully. All56 retained
PNGs, including initial and repaired images, were independently inspected and
their SHA-256 values rechecked. All50 checkpoints share the frozen application,
evaluator, instruction and optimization hashes above and the same model settings.
All50 lead run IDs also match the Logfire export. No failed case was dropped,
rerun out of the denominator or rescored in place.

This baseline **does not establish production readiness**. Machine contracts,
inspector verdicts, native-image appearance and final task completion disagree.

| Measurement | Result | Meaning |
|---|---:|---|
| Raw executable contract pass | 34/50 | Includes two boundary cases; not independently verified chart accuracy. |
| Raw contract plus60s SLA | 29/50 | Five otherwise passing cases miss the SLA. |
| Within60s regardless of quality | 37/50 | Speed alone does not establish success. |
|120s watchdog failures | 4/50 | Cases38,41,42,44; all retained as failures. |
| Independent task audit | 32 pass /16 fail /2 uncertain | Agent judgments of intent, semantics, final claims and useful delivery; not human gold. |
| Published artifacts | 46 |44 have a PNG; two are no-chart fallbacks. |
| Final replies containing the PNG link | 34/48 chart tasks | Publication does not guarantee final-response delivery. No UI flow was tested. |
| Cases with a false/overstrict reviewer error | 11 | Cases2,6,7,9,23,26,27,40,46,48,49; a case-level count, not reviewer accuracy. |
| Cases with an unnecessary repair attempt | 7 | Cases2,6,7,9,23,26,48; includes a blocked extra attempt. Two other judgments remain unknown. |

A complete faithful Markdown table can fulfill a table-permitted handoff even
when it fails the separate PNG-link contract (e.g.27 and28). By contrast, saying
“published” without useful visible content or a link is not final delivery.
The audit labels the final retained PNG separately from whether it was published
or delivered; an attractive abandoned preview cannot count as completed work.

All48 proposed chart families are acceptable under their briefs in the audit,
which often explicitly permits tables. That does **not** prove optimal chart
selection or48 successful charts: one case never produces a PNG, several are
abandoned, and role/wording/delivery defects remain. The native first-attempt
image judgments for chart tasks are41 pass,3 fail,1 uncertain and3 no-image.
Last retained image judgments are46 pass,1 uncertain and1 no-image, regardless
of publication. Provider-resized vision inputs and UI viewports were not observed.

## Latency and calls

Across all50 attempted cases, mean elapsed time is40.32s, median20.26s, and
observed p95 is120.00s. The four timeouts are watchdog-censored; this is not a
latency distribution of successful completions only. Summed case time is2015.89s.

| Operation | Observed calls | Median seconds | p95 seconds | Maximum seconds |
|---|---:|---:|---:|---:|
| Lead GLM model request |338|1.53|17.56|97.29|
| Designer GLM model request |77|3.12|22.37|45.00|
| Gemma model request |55|1.02|2.46|4.75|
| Render tool |60|0.47|0.81|2.04|

Logfire records470 attempted client-side model-call spans versus465 framework-
recorded requests; cancelled calls account for the distinction. These counts do
not reveal downstream provider retries. Non-nested model-request spans total
1969.36s, approximately97.7% of summed case elapsed time. Do not add the enclosing
specialist/tool/root durations again. Model waiting dominates this sample, while
false reviews add avoidable model round trips. A slow model span alone does not
identify queueing versus inference versus network delay.

Case41 has one design/render/review/publication, then times out before its final
reply. Its first two lead requests alone take27.83s and73.91s; the designer takes
3.02s and reviewer1.14s. Cases38 and42 time out through different repair/technical
paths. It is not accurate to attribute every slow case to the inspector.

## What failed and what was real

- **Unsupported criticism amplified:** cases2/7/9 reject correctly mapped first
  renders; case7's repair PNG is byte-identical, but the designer claims a fix.
  Case23 treats a correct row just outside the30-row reference excerpt as an
  error and names two countries absent from both source and picture.
- **Contradictory structured judgment:** case46 says all observed/expected values
  match while still returning an error-level finding. The lead publishes the
  correct table without a redesign; code does not force every repair.
- **Actual defects need repair:** case25 drops a valid2016 count because another
  measure is null; case48's first axis applies% to population counts. Their first
  repairs are justified. Case48's later duplicate-region claim is false.
- **Executable configuration gaps:** cases21/42/44 accept indicator heights that
  fail only at rendering. A table precision option used in38 is known to be
  unsupported. These are not imaginary visual defects.
- **Meaning/constraint transfer:** case30 expands M/F despite the literal-code
  requirement;26 invents an age unit. The source cells stay unchanged, which is
  insufficient to guarantee faithful displayed meaning.
- **False completion and boundary claims:** case31 claims a fully scrollable
 1000-row delivery although the returned static card contains20 rows and no
  full-table link. Full rows remain saved; this is not a harmless scrollbar
  viewport. Case29 correctly reports a technical row limit but asks for changed
  input despite the handoff's no-new-data requirement.
- **Evaluator limitations:** case47's true statement about absent months trips
  the numeric-answer gate. A false inspector rejection also fails the review
  gate on correct charts. Conversely, raw strict-pass misses case30's invented
  code meanings and the boundary behavior above. Raw scores remain untouched.

The [reviewer/designer diagnosis](2026-09-17-reviewer-designer-diagnosis.md)
separates direct evidence from prompt/context hypotheses and prior controlled
reviewer experiments. Both prompts/contracts and model reliability contribute;
this single run cannot assign a causal percentage to either.

## Evidence and next gate

- [Joined per-case audit, scores and trace IDs](2026-09-17-maturity50-summary.json).
- [Timing-only Logfire export](2026-09-17-maturity50-logfire-spans.json):1059 spans,
  fetched in two pages and matched to all50 cases. No message/CSV/PNG payloads.
- Original untouched baseline output:
  `evals/lead/results-maturity50-glm-gemma-20260917-v1/result.json`.
- The three independent audit reports linked above preserve every PNG hash,
  disputed finding and uncertainty.

No prompt optimization, model-default change, commit or cleanup was performed
as part of this baseline/diagnosis. DSPy/GEPA remains blocked from optimizing an
unvalidated quality reward:28 raw chart tasks lack audited executable choice
contracts, semantic/binding contracts need validation, and reviewer pass is not
a trustworthy reward. The new audit evidence should inform a separately
versioned regression/metric update; it must not retroactively redefine success.

Priorities are to preserve explicit constraints through delegation, ground and
narrow reviewer claims, let the lead/designer reject unproven criticism, repair
executable renderer-contract gaps, and ensure faithful final delivery. Evaluate
those changes under a new frozen run, keeping false alarms, missed real defects,
source semantics, delivery and latency separate. Do not add an automatic
specialist loop or a new planner.
