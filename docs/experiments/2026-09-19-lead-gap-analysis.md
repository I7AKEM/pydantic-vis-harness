# Lead-directed team: gaps found in the traces and the Dev CSV corpus (2026-09-19)

## What was examined

- Logfire project `vis-harness`, 2026-09-16 to 2026-09-19 13:03 UTC: 162 lead runs (`invoke_agent vis-lead`), every
  tool call and model call, read through the Logfire MCP (no UI). Six runs were read step by step.
- Code on the working tree of `codex/lead-directed-team` (uncommitted state of 2026-09-17): `vis_agent/lead.py`,
  `designer/`, `reviewer/`, `analyst/`, `requests/`, `render/`, all rulebooks, `AGENTS.md`, `docs/lead-directed-team.md`.
- The 500 Dev CSVs (`~/Desktop/Dev CSV`) pushed through the direct-read path and the deterministic checks with no
  model call: `docs/experiments/2026-09-19-corpus/harness.py`, results in `results.jsonl`.
- The six charts rendered today, inspected by eye (`data/renders/8bbbed7a60bf`, `33b460be64a6`, `8297ba7d01bf`,
  `e39837e79ad9`, `1ef48c5fb20e`, `775ea6ddd901`).
- Every finding below has a reproduction test in `tests/requests/test_lead_gaps.py` (11 tests; they pass, which
  means the behaviour is confirmed on the current code). Three candidate fixes live in
  `docs/experiments/2026-09-19-patches/` with desired-behaviour tests in `tests/requests/test_lead_gap_fixes.py`
  (marked xfail until a patch is applied). With all three patches applied the full suite passes: 1949 tests.
- Branch `analysis/lead-gaps-2026-09-19`, created from the current checkout. Only new files were added. The patches
  were applied for the test run and then removed again, because this checkout is shared with a live `--reload`
  server; the tree was verified byte-identical afterwards.

## Verdict

The team draws correct charts when the request fits the chart grammar. All six charts rendered today match their
data and labels, and a routine run is 7 tool calls, 8 model requests, median 19 s. The problems are around the
chart, not in it: a failed run poisons the conversation, the budget ends runs with a crash, the designer cannot
represent three categorical dimensions or top-N and the guards turn that into dead ends, and two typing defects
in the direct reader change what a time chart says. Details, ordered by impact.

## 1. A request left "running" blocks the whole conversation (high)

Evidence. Trace `01a0b9c1c45d8af82156c4c80b54ec00` (today 13:01): a table with city, wealth level, qualification
and count. The designer died twice, the two-attempt cap refused four more design calls, nothing was published,
and request `rq_eb6b26b1...` stayed `running`. The user rephrased the request two minutes later (trace
`01a0b9c3d7532f637f8715e0f219e954`) and `draw` answered "already active in this conversation. Resume and finish
it". The same refusal appears in 4 runs this week; the 280 s run `01a0af8e46b241962d4e037b3d606163` hit it too.

Cause. `lead.py:165-173` refuses any new `draw` while any request of the conversation is `running`. Nothing ever
finalizes a chat request that ends without a publish: the chat path has no failure handling (the API path marks
the request `failed` in `requests/service.py:255-267`; the chat path only emits an error chunk), and a lead that
ends in text after both design attempts are spent leaves the request running because the output validator
(`lead.py:614-635`) only fires when a design was saved. The status `stopped` exists
(`requests/models.py`) and is never assigned. The only exits are `resume` on a request that can do nothing
more, or `publish_visualization` with `no_chart_reason`.

Tests. `test_budget_crash_in_chat_leaves_the_request_running`,
`test_stale_running_request_blocks_the_next_draw_in_the_conversation` (other dataset; same dataset, new question).

Candidate fix (patch 3, 26 lines). `draw` records the run that opened a request; a running request opened by an
earlier run is marked `stopped` and the new draw proceeds; a re-draw inside the same run stays refused, so the
guard still stops restart loops. Tests `test_new_turn_can_draw_after_an_earlier_run_left_a_request_running` and
`test_same_run_still_cannot_redraw_to_bypass_a_diagnostic`. Complementary and not implemented: mark the request
`failed` when a chat run raises, in the event stream's `on_error` hook (`pydantic_ai/ui/_event_stream.py:657`),
which is the parity the API path already has.

## 2. The 18-request budget ends a run by crashing (high)

Evidence. 3 runs died with `UsageLimitExceeded` (`01a0b9b9b84ebc86668979b36cda2c51` today,
`01a0b0a3c6bfd4b541a5cb9455459eb2` and `01a0af8e46b241962d4e037b3d606163` on Sep 17); one more died on a lead
tool retry limit (`01a0ad78de9e5e908248b6d52eb4a17c`). In today's case the count was: revise 1, analyst 2,
designer 3 (with its two retries), fallback designer 2, two `answer_question` calls 4, lead turns 6. Specialist
requests count against the lead's budget by design (`AGENTS.md`), which is right, but the lead never learns how
much is left, the user sees an exception, and the request stays running (finding 1).

Cause. `providers.py:148` sets `UsageLimits(request_limit=18, tool_calls_limit=16)`; the prepare hooks
(`lead.py:218-259`) reserve tool calls for render, review and publish but say nothing about model requests.

Recommendation. Not a bigger budget. Either finalize on failure (finding 1) or hide the specialists when fewer
than about four model requests remain, the same way tool calls are already reserved. Both are small.

## 3. Three categorical dimensions and top-N cannot be drawn; the guards make it a dead end (medium)

Three dimensions. In trace `...b54ec00` the table had three label columns. `grouped_bar` binds category, group
and value; the grammar has no facet. The lead's second attempt put `city` in `required_columns`, which the
designer cannot satisfy, so it died on its output retries. The lead's own instructions say "If design failed ...
retry with a changed direction or use_fallback=true" (`lead.py:82-83`), but the two-attempt cap
(`lead.py:393-397`) refused `use_fallback=true` in 2 runs. After the cap the tool stays visible and is refused
five times across 3 runs, while `consult_analyst` is hidden after one use (`offer_analyst`): the two guards are
inconsistent, and GLM 5.3 at low effort does not act on the refusal text.
Test `test_two_failed_initial_designs_also_refuse_the_fallback_designer`.
Corpus: 19 of 487 readable files have three or more label columns plus a measure (for example
`vizcsv-a2988e7c4b4ea1ca`: city, wealth level, education, count). The workable move is to fix one dimension
(filter or aggregate through the analyst, or drop it) and say so; nothing in the lead's instructions covers it.

Top-N. `limit N` passes the delivery check and always fails at render on a direct CSV, because the direct reader
marks every column `aggregate="none"` and the resolver requires an additive value (`designer/resolve.py:335-338`),
while `chart_capabilities` recommends exactly that key (`designer/capabilities.py:145-146`). Today's trace
`01a0b9b484d6422efc70172ee97f3392` lost a design and a render on "A limit needs a category and additive values
for Other." Test `test_limit_passes_the_check_and_fails_at_render_on_a_direct_csv`. The data agent already returns
the top rows in this corpus, so the fix is to reject `limit` at check time (or drop it), not to support it.

check_spec disagrees with deliver_design. `check_spec` said ok and `deliver_design` then rejected the same spec
for a missing required column (trace `...da2c51`), costing one of the designer's two deliveries.
Test `test_check_spec_passes_a_spec_that_deliver_design_rejects_for_required_columns`.
Patch 1 (53 lines) makes both use one check; test `test_check_spec_reports_the_missing_required_column`.

Numbers this week: the designer's delivery was rejected 45 times in 247 deliveries, and the designer died on its
two output retries 14 times in 11 of 162 runs.

## 4. One analyst call per request, while answer_question stays open (medium)

Evidence. Trace `...da2c51`: the first analyst task (add `rest_count`) produced a wide table that a donut cannot
show; the analyst was then hidden, so the lead called `answer_question` twice (6 model requests whose result
cannot enter the request), then `resume`, then hit the budget. Trace `01a0af8e46b2...`: five `answer_question`
calls, one 90 s analyst timeout, 280 s in total, no answer.

Assessment. The one-call rule is deliberate and reasonable (it stopped the old loops). The gap is the leak: the
request-less numbers path stays offered during a chart request and burns the budget.
Test `test_analyst_disappears_after_one_consultation_while_answer_question_stays_offered`.
Smallest change: hide `answer_question` while a chart request is running (a prepare function like `offer_analyst`),
and tell the lead to ask the analyst for the long shape directly when a stacked or donut chart needs it.

## 5. Years are drawn in value order (medium, corpus-wide)

Evidence. The direct reader types an integer year as `measure` (`analyst/source.py:88`: numeric wins before the
time-name rule). The resolver then defaults a time-role axis whose column is not kind time or ordinal to
`sort value desc` (`designer/resolve.py:327-331`). A line chart over 2021-2024 draws the x axis as 2022, 2024,
2023, 2021, and the delivery check accepts the spec. Corpus: 47 of 48 year-named columns are typed `measure`;
20 of 44 other time-like columns (month, date, period) as well. No trace this week had a year axis, so this is
confirmed by test and corpus typing, not by a wrong published chart.
Test `test_numeric_year_is_a_measure_and_the_line_chart_orders_years_by_value`.
Patch 4 (23 lines): a time-role axis is drawn in time order, including numeric periods; test
`test_a_numeric_year_bound_as_time_is_drawn_in_year_order`. A year bound as `category` stays value-sorted.

## 6. A long cell removes the whole column, silently (low)

Any cell over 256 bytes (about 128 Arabic characters) removes the column from the table the designer sees
(`analyst/source.py:82-84`); the warning stays in the report and is not forwarded to the designer prompt
(`designer/agent.py:135-149`). Corpus: 29 files had columns kept local, all of them `wkt`/`path_wkt`, which is
correct; the exposure is long Arabic labels. Test `test_long_text_column_is_dropped_and_the_designer_is_not_told`.
Suggestion: shorten for display instead of dropping, or forward the warning.

## 7. Reviewer: an error owned by nobody forces "revise" (low)

Trace `01a0b9b80adec66a05a2684f39fbb99b` today: the reviewer wrote "The chart is correct; my initial check of the
legend was mistaken" and still emitted an R-1 error owned by `none`, so the verdict became `revise`
(`reviewer/agent.py:88`); the lead rightly published. The `image` reference kind is never validated
(`reviewer/agent.py:62-71`). Same pattern Codex recorded as rollout 0046 in
`2026-09-17-reviewer-designer-diagnosis.md`. Recorded verdicts this week: 26 pass, 11 revise, 9 not reviewed;
104 of 139 eval reviews have no recorded result in Logfire, so eval verdict rates must come from the saved eval
files, not from traces. Test `test_reviewer_error_owned_by_none_yields_revise_even_when_the_summary_retracts_it`.

## 8. Smaller confirmed items

- `ask_user` needs a running request (`lead.py:600-603`); "which chart do you mean?" about finished artifacts
  fails (trace `01a0af8e46b2...`). The lead could answer in text; the instructions do not say so.
  Test `test_ask_user_cannot_ask_about_a_finished_request`.
- Docs versus code: README says 24 model requests, code says 18 (`requests/service.py:27`). `AGENTS.md` says a
  changed table invalidates stale renders before external work; the analyst path invalidates after the call
  (`lead.py:358-366`). The design doc says in-process API runs reject a duplicate active request; the API
  returns 202 with a warning (`requests/service.py:219-220`). Two revisions of one parent get the same version
  number (`requests/service.py:187`).
- `publish_visualization` never checks status, so a `waiting` request can be published (`requests/service.py:160-207`),
  and `no_chart_reason` bypasses the review gate (`lead.py:590`).
- Check/render parity beyond `limit`: tables over 78 rows fail at render, not at check
  (`designer/resolve.py:266-272`); 22 corpus files are that long.
- In today's donut run the first render failed and the second design was spent on it; in the 100% stacked bar
  run the analyst issued two identical `run_query` calls in the same millisecond (harmless, one model call).

## Corpus pass (500 Dev CSVs, no model)

| Result | Files |
| --- | ---: |
| Read and typed by the direct path | 487 |
| Refused: over 10,000 rows (19,000 to 100,000), with the technical message | 8 |
| Refused: every column is geometry or oversized | 4 |
| Refused at upload: 134 MB over the 20 MB limit | 1 |
| Geometry column kept local (`wkt`, `path_wkt`) | 29 |
| One row (indicator or table territory) | 170 |
| No label column at all | 166 |
| Three or more label columns plus a measure | 19 |
| Year-named columns typed `measure` | 47 of 48 |
| Tables longer than the 78-row render cap | 22 |

Reading is fast: 0.2 s for 5,000 rows by 16 columns. Hijri strings, leading zeros and Arabic-Indic numbers
survived every file. All-empty measure columns (for example a percentage with an empty cell) become text
columns; a one-row indicator then shows "Unavailable", which is acceptable.

## Latency, for the enhancement list

83 routine runs (exactly 8 model requests): median 19.1 s, p95 103 s. 65% of wall time is the lead's own six
model turns (GLM 5.3: median 1.7 s, p95 17.5 s, max 97 s per call), the designer 21%, the reviewer 11%,
rendering 2%. The p95 is provider variance, not loops, which matches Codex's Sep 17 note. Five eval runs hit the
harness's 120 s deadline with a normal 8-request flow. The only code-side lever is fewer lead turns; for example
letting `render_visualization` hand the picture to the inspector in the same tool call would remove one turn
(about 2 to 4 s at the median) and matches the design doc's "the inspector receives the image after every
successful render".

## What was not found

No wrong number or label in any published chart this week; SQL safety in the analyst is solid; labels, Hijri text
and leading-zero identifiers survive the direct path on the whole corpus. The one debatable chart today (a donut
of three averages) followed the user's explicit request; a one-line note that averages are not parts of a whole
would have been the expert touch.

## Files

- Report: this file. Tests: `tests/requests/test_lead_gaps.py`, `tests/requests/test_lead_gap_fixes.py`.
- Patches: `docs/experiments/2026-09-19-patches/` (apply with `git apply`; then run the fix tests with `--runxfail`).
- Corpus: `docs/experiments/2026-09-19-corpus/harness.py`, `results.jsonl`.
