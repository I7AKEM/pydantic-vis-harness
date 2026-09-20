# Claude designer production-v3: first twenty audit

This is a completed, authorized real-model run of the frozen `renderable` development cohort, through the data-agent handoff API rather than the UI. All twenty attempts, including the timeout, are retained in `results-parallel20-claude-production-v3.json` and adjacent per-case assets. It is the first segment of the subsequently requested fifty; no supplementary cases were launched by this worker.

The closed-model substitution is **designer and designer fallback only**: Claude Sonnet 4.5. Lead, profiler, and analyst remain GLM 5.3; the image inspector remains Gemma 4 31B Nitro. Production lead instructions were used without an override. Concurrency was one, the per-turn watchdog 120 seconds, and the acceptance SLA 60 seconds. Model overrides were process-local; no runtime, prompt, evaluator, dependency, or `.env` file was changed. The command exited 1 because some evaluated cases failed, not because execution or serialization failed.

## Frozen evidence

- Application SHA-256: `096451ded74efcdae3058d3a635924fbc66b41c4796c978706078037f91755a6`.
- Evaluator SHA-256: `5914d8a0037305557f9a822879261902b4c00172c58289717cdf62478c848403`.
- Combined SHA-256: `10de585940ee00e4271fbdedee20aea48359bfc7fc1915923cdbbeb8d2e1d6df`.
- Cases SHA-256: `8541cb0af6a7f19a8acde058cef7f785e00f16799f45d0cee1492d6102eeb477`.
- Production lead instructions SHA-256: `f8b393a809120ba5a8fbb41be12e7d9577fc6c8da1b5be37afdd0212f8d25efd`.
- All three changed-during-run flags are false; the application and evaluator hashes were rechecked after completion.

## Unmodified outcome

| Metric | Result |
| --- | --- |
| All strict gates, including latency | 12/20 |
| Published full-source fidelity | 19/20 |
| Final numerical-claim fidelity | 19/20 |
| Published PNG evidence | 17/20 |
| Final image-link delivery | 16/20 |
| Final scoped inspector pass | 15/20 |
| At most 60 seconds | 15/20 |
| Repetition bounds | 20/20 |
| Framework completed-request usage | 166 |
| Mean / median | 40.53 / 28.65 seconds |
| p95 / maximum | 115.17 / 120.00 seconds |

The one source/numeric fidelity failure is a timeout without a published artifact or reply, not evidence that a source cell was changed. Nineteen cases generated at least one PNG locally; two subsequently published a no-chart table fallback, leaving seventeen published PNG artifacts. The inspector-based quality count excluding latency is thirteen charts plus two rendered tables; this is not an independent visual guarantee.

The request count is completed framework usage, not a complete count of billed or outbound attempts: the timed-out case retains one completed GLM response and a subsequent unanswered request. Do not interpret it as just one attempted model call.

## Failed cases: raw gates and inspected causes

Case IDs below omit the common `corpus-vizcsv-` prefix. PNG IDs resolve under `results-parallel20-claude-production-v3-assets/<case>/renders/<PNG ID>/chart.png`.

| Case | Seconds | Failed gates / evidence |
| --- | ---: | --- |
| `6eff7ae46ebb4edf` donut | 27.74 | Review and final image-link delivery. First PNG `b6db1a053695` already has correct blue **وافد 375,161** and teal **مواطن 373,877**, matching the legend; labels are unclipped. Gemma falsely alleged a swap. An unnecessary `sort none` repair produced another correct image, `d3c235336432`. Its review contains an error-level finding whose own explanation retracts the claimed numerical errors. The lead published the chart but omitted its image link and inaccurately described the first mapping as fixed. |
| `97280400c00748a7` male count zero | 120.00 | Timeout and missing delivery. Only `draw` completed; `design_attempts=0`, `render_attempts=0`. Claude was never called. The first GLM response arrived about 29.4 seconds after the request; the following GLM request had no response before the watchdog. There is no PNG to inspect. |
| `ba0187c944a3f829` seventeen city/region rows | 29.03 | No-chart fallback fails chart, review, image, required-visible-column, and final-delivery gates. First PNG `80d17528b34d` visibly contains all seventeen rows, including جدة / مكة المكرمة / نجران, with correctly paired headers and values. Gemma called column order a data mismatch and gave contradictory left/right descriptions. Repair returned `no_change`; the lead then passed `no_chart_reason`, removing the valid PNG from the published artifact. The full table remained in final text. This failure is not cropping or missing rows. |
| `39471b0e4a5d3fc5` driver averages | 114.91 | Latency only. PNG `ec1f685b4118` clearly shows 3.76 for each profession group with correct axes. Claude design took 7.30 seconds and Gemma review 0.75 seconds. The serialized GLM request-to-response interval **after successful publication** was about 92.81 seconds. |
| `45980b90faceca07` wealthy percentages by gender | 23.73 | Review only. PNG `53d6871dd8e1` has the correct six values, Arabic labels, and separate denominators. Gemma's error-level finding explicitly concludes that no R-1 error was found. The lead nevertheless described the inspector as confirming the result, without disclosing its structured `revise`. Before rendering, there was also an avoidable second design: GLM had rephrased the Arabic draw request into English, saving `language=English`; first Claude output followed English despite Arabic in the direction. The second design corrected that before the first render. |
| `c76808cc7a78dac8` population versus employed | 73.35 | No-chart fallback plus latency. First PNG `9d06d6c367f8` is correctly paired and legible: Najran blue population is 701 and teal employed is 10,356, matching the legend and source; all ten pairs are visible. Gemma falsely alleged swapped colors. The no-change repair was followed by `publish_visualization(no_chart_reason=...)`, which creates a table fallback, although the lead's text said a chart was published. |
| `ae315d3da67a2d11` thousand-coordinate scatter | 81.89 | Latency only. PNG `6d75b6e643fc` visibly has a readable coordinate scatter, correct axes, no invented route lines, and a ten-application legend. Full row fidelity passed. Claude design took 8.18 seconds and review 1.06 seconds. Three GLM request/response timestamp gaps were about 10.48, 30.33, and 24.81 seconds. |
| `2bc0cfa90c65f142` five wealthy-city counts | 61.16 | Latency only. PNG `d5bb01ee233e` clearly displays the correct five values 6, 5, 4, 4, 4. Claude design took 6.09 seconds and review 0.78 seconds. Multiple GLM timestamp gaps of roughly 15.36, 16.92, and 17.67 seconds dominate the turn. |

Static PNG visibility and normal scrolling in an interactive table are different requirements. The city/region PNG in this run is already complete. The retained HTML contains the full escaped table; the package's table path is not an interactive S2 chart (`interactive=false`). This audit does not count an ordinary scroll viewport as corrupt data, and it leaves the original strict static-image acceptance gates unchanged.

## Timing interpretation and scope

End-to-end case durations and saved specialist `seconds` come from local measured elapsed time. The cited GLM intervals are differences between serialized message timestamps; they demonstrate where the wait occurred but are **not** provider compute, queue, or network spans separately. Provider names in the records indicate routing, not a controlled comparison of those providers. Do not sum nested specialist times with a containing tool or end-to-end time. Saved stage reports can repeat a prior report after a no-change repair, so naive summation can double-count it.

The evidence supports reviewer false rejections, lead delivery/fallback mistakes, and GLM lead tail latency in this run. It does not support attributing every failure to Claude or declaring either designer generally superior from one paired development run. No default model was switched, no cases were rerun or removed, and no changes were committed.
