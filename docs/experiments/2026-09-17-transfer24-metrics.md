# Transfer24: frozen baseline/candidate metrics

**Outcome: a modest deterministic-contract gain, but no improvement in fast successful delivery and a clear latency regression in this run. This is not evidence that the candidate is generally smarter or production-ready.**

Evidence: [machine-readable metrics](2026-09-17-transfer24-metrics.json),
[baseline raw result](../../evals/generalization/results-baseline/result.json),
[candidate raw result](../../evals/generalization/results-candidate/result.json).
All 48 attempted task-arm runs and their timeouts/errors are retained. No rerun,
metric rewrite, model substitution or holdout-guided tuning was performed during
this reporting pass.

## Design and comparability

The bank has 24 newly authored synthetic tasks: six intent families, each with
two goals and a renamed/reordered meaning-preserving partner. All new cases were
withheld from runtime implementers until runtime freeze. The bank is not human
gold, the paired observations are correlated, and a single trial per arm cannot
establish population generalization or stochastic reliability.

Both arms used identical recorded model IDs/settings: GLM 5.3 for every text role
(including designer/fallback), low reasoning; Gemma 4 31B nitro for inspection,
thinking disabled. These controlled evaluation settings are not a claim about
the production designer default. Both arms used identical shuffled order and
one case at a time per arm, shared 18-request/16-tool budgets, 120s watchdog,
and the same 60s reporting SLA. The two arms began together, but later cases ran
under different wall-clock/provider conditions as their durations diverged.

| Frozen evidence | SHA-256 |
| --- | --- |
| Bank | `2548d627feb492d200ca11bd33113121ee1d9467c15a1d474f09a850759b84a5` |
| Baseline runtime | `573f65b5b612013ffd94558a396ba375d7891df3be68da410328136b354a6218` |
| Candidate runtime | `7ff116ba5c5a222c69f3e7d9806f1356d5e1658524b4de10aa7edebe9150929d` |
| Shared evaluator | `ca70b18caf8c048a4a7229f0d2a62ad8cbae70f7e064301c2fd39790fab9d3b3` |

The actual imported runtime and evaluator hashes match their respective final
hashes; all mutation flags are false. Same model names do not fix provider
queueing, endpoint routing, network time or stochastic model behavior.

## Separated outcomes

All case-level counts below use **24 attempted cases per arm**. Missing
publication counts as unavailable evidence, not an observed wrong chart choice
or demonstrated data corruption.

| Metric | Baseline | Candidate |
| --- | ---: | ---: |
| Frozen deterministic contract passed | 19/24 | 21/24 |
| Contract passed **and** completed within 60s | 18/24 | 18/24 |
| Published artifacts | 23/24 | 23/24 |
| Published chart-family/binding contracts satisfied | 23/24 | 23/24 |
| Published full source data and metadata units preserved | 23/24 | 23/24 |
| Correct published PNG link present in final reply | 19/24 | 21/24 |
| Within 60s, regardless of correctness | 23/24 | 19/24 |
| 120s timeouts | 0/24 | 1/24 |
| Other terminal errors | 1/24 | 0/24 |
| Retained PNGs across all attempts | 25 | 24 |
| Framework-recorded model requests | 205 | 197 |
| Mean latency | 23.40s | 41.80s |
| Frozen nearest-rank p50 | 19.12s | 30.81s |
| Conventional median (middle-pair average) | 19.14s | 36.16s |
| Frozen nearest-rank p95 | 54.43s | 117.64s |

Among the **23 published artifacts** in each arm, all 23 preserve the full saved
source table and units. That does not prove correct pixel annotations or prose.
Timeout durations remain censored observations in the latency distribution.
The candidate was faster on only 6/24 paired cases; the mean paired delta was
**+18.40s**, despite eight fewer framework-recorded model requests. A cancelled
in-flight provider request can be missing from framework usage, so those counts
are not a complete provider-attempt census; Logfire is a separate measurement.

The parent's [Logfire metadata export](2026-09-17-transfer24-logfire.json)
contains 205 baseline versus 201 candidate chat spans, with 24 traces per arm.
Four candidate chat spans have no recorded token usage, explaining the gap from
197 framework requests. Non-nested model spans total 542.43s versus 984.19s,
or 96.58% versus 98.10% of summed case time. Thus fewer observed model calls
still took longer; increased loop count is not an adequate explanation.
These spans do not distinguish provider queueing, inference and transport.

There were five contract improvements and three regressions, with 16 cases
passing in both arms. The improvements are four recovered final-link failures
and one original-trajectory tool-schema failure. The regressions are one outer
timeout and two final-link omissions. Therefore the net contract gain must not
be presented as improved chart-selection accuracy.

## Metamorphic and goal-contrast pairs

| Frozen pair contract | Baseline | Candidate |
| --- | ---: | ---: |
| Meaning-preserving pairs | 7/12 | 9/12 |
| Same-data, different-goal pairs | 4/6 | 5/6 |
| All pairs | 11/18 | 14/18 |

All 18 pairs are complete in each arm. A pair passes only when both members meet
their own delivery-inclusive contract and their persisted source observations
are canonically equivalent. It does not require identical pixels or identical
chart types. Because delivery failures affect these scores, they are not pure
semantic-reasoning accuracy scores. Detailed failed pair IDs are retained in the
JSON report.

## Calls, repetitions and failure mechanisms

| Captured lead tool-call attempts | Baseline | Candidate |
| --- | ---: | ---: |
| Design | 30 | 25 |
| Render | 25 | 25 |
| Review | 25 | 26 |
| Publish | 23 | 23 |
| Cases with more than one design call | 5 | 1 |
| Saved visual-repair attempts | 3 | 0 |

These are tool **attempts**, including schema rejection, a blocked repair, or a
cached return; they are not equivalent to specialist model executions.

- Baseline `g04-curing_paths-original` stops on design-tool retries before any
  design/image exists. The first captured retry rejects a time-kind column with
  a unit. The trace does not expose the second retry return, so its exact reason
  is not asserted.
- Candidate `g04-curing_paths-transformed` reaches the outer 120s timeout after
  **one design, one render, one review**. It has a retained preview but no
  published artifact or final reply. This is not evidence of an infinite repair
  loop and remains a failed case.
- Candidate `g05-overview-transformed` has one technical layout-height recovery,
  not a visual-review repair. It and `g05-exact_record-original` publish valid
  artifact cards but omit the rendered-artifact links in their final replies.
- Both candidate association variants call review twice, but their second
  replies reuse the identical first timeout report. There are **two cached
  repeats**, not two additional external inspections. Both final replies
  incorrectly say the inspector timed out twice.
- Distinct returned review reports: baseline 25 reviewed; candidate 20 reviewed
  and four unavailable (three timeout reports and one output-retry exhaustion).
  Online verdicts are not correctness labels, and unavailable is not a pass.
- Baseline saved stages can reuse a design/review object after no-progress
  handling; simply summing `stage_reports` would double-count those reports.

## Why the raw pass count is not visual accuracy

Independent image audits are separate from these frozen metrics. A critical
counterexample is candidate `g04-sample_spreads-original`, which passes every
deterministic contract check. Direct local image inspection corroborates the
independent auditor: labels **5, 8 and 3 MPa**—the batches' minima—appear beside
upper whiskers at **25, 21 and 24 MPa**. The source and box geometry remain
correct, but the annotation placement is misleading. Its inspector exhausted
output retries on an invalid row citation and returned unavailable; the lead
disclosed that lack of inspection.

[Retained image](../../evals/generalization/results-candidate/g04-sample_spreads-original/renders/dafbb291cb7d/chart.png)
and its SHA-256 are recorded in the JSON sidecar. The raw contract pass is left
unchanged. In particular, **21/24 is not “21 visually correct charts.”**

The evidence supports reduced repeated design attempts and somewhat better
delivery in this one challenge run. It does **not** support a general-intelligence
claim, a speed improvement, or readiness in every chart situation. Any cases
used to guide subsequent changes must become regression cases; a later clean
generalization test needs a fresh withheld bank.
