# Lead-directed team: gaps found in the traces and the Dev CSV corpus (2026-09-19, revised 2026-09-20)

Revision note. An independent review checked every number, trace narrative, test and patch of the first version.
This version keeps what survived, corrects what did not, and lists the withdrawn claims at the end. Nothing in
this document is a production change; the patches are proposals tested in a private copy of the working tree.

## Scope and method

- Traces: Logfire project `vis-harness`, window 2026-09-16T00:00:00Z to 2026-09-19T13:03:00Z, read through the
  Logfire MCP `query_run` tool. Counts use root `invoke_agent vis-lead` spans unless stated; one run in the window
  (`01a0af919c8e1cef6e3a92203856f88c`) exported tool and model spans but no root span, so it is absent from the
  run counts and present in the trace narratives. The SQL for every number is in the appendix.
- Code: the working tree of branch `analysis/lead-gaps-2026-09-19` at HEAD 53a77f0, which still carries the
  uncommitted Codex changes of 2026-09-17 (the code that produced the traces).
- Corpus: the 500 Dev CSVs pushed through the direct-read path and the deterministic checks with no model call
  (`docs/experiments/2026-09-19-corpus/harness.py`, `results.jsonl`). The harness records typing, shape and the
  offline recommendation per file. It does not supply the upstream brief, compare cells, or render, so it cannot
  show fidelity of labels or values; it shows what the reader accepts, refuses and how it types columns.
- Charts inspected by eye: the six rendered on 2026-09-19 (`data/renders/8bbbed7a60bf`, `33b460be64a6`,
  `8297ba7d01bf`, `e39837e79ad9`, `1ef48c5fb20e`, `775ea6ddd901`) and the Sep 17 box plot named by the review.
- Tests: `tests/requests/test_lead_gaps.py` (18 tests; they pass on the current code, which is what confirms each
  behaviour; each docstring says what the test establishes) and `tests/requests/test_lead_gap_fixes.py` (7 tests:
  5 marked xfail until the patch they name is applied, 2 guards that must hold before and after). Verified on the
  unpatched tree: 18 passed; 2 passed, 5 xfailed. With all three revised patches applied in a private copy: the
  7 fix tests pass with `--runxfail`, 13 of the 18 gap tests pass and the 5 that describe the patched behaviours
  flip as intended, and the existing suite passes (1949 tests, the two gap files deselected).

## Verdict

The team draws correct charts when the request fits the chart grammar; the six charts of 2026-09-19 match their
data and labels, and a routine run is 7 tool calls, 8 model requests, median 19 s. The confirmed defects are in
the flow around the chart: a request that stays `running` after a failed or unfinished turn, a budget that ends a
run with an exception, a designer contract that loses required columns between calls and cannot express three
categorical dimensions, a delivery check that disagrees with the renderer, and a default axis order that draws
numeric years by value. One published chart from the Sep 17 evaluation has misplaced labels, so the picture
inspection cannot be called defect-free for the week.

## Confirmed defects

### 1. A request left `running` blocks new draws until it is published or resumed (high)

What happens. `draw` refuses any new request while a request of the conversation is `running`
(`vis_agent/lead.py:165-173`). A request stays `running` when the chat run raises (nothing in the chat path
changes the status; the API path marks it `failed`, `vis_agent/requests/service.py:255-267`), when the run is
cancelled, and when the lead ends its turn in text without publishing (the output validator at
`lead.py:614-635` only fires when a design was saved). The status `stopped` exists in
`vis_agent/requests/models.py:14` and is never assigned.

Evidence. Trace `01a0b9c1c45d8af82156c4c80b54ec00` (2026-09-19 13:01) ended in text with request
`rq_eb6b26b1...` still `running` after both design attempts were spent. The rephrased request two minutes later
(`01a0b9c3d7532f637f8715e0f219e954`) was refused with "already active in this conversation"; that turn recovered
by publishing the exhausted request as a source table with `no_chart_reason`, so the user got a table, not the
chart they asked for, and not a permanent block. The three refusals inside the window are not all defects: the
refusal at 2026-09-17 13:33:19 (`01a0af8e46b241962d4e037b3d606163`) was correct, because run
`01a0af919c8e1cef6e3a92203856f88c` was reviewing that very request at that moment and published it 14 s later;
the refusal at 13:03:40 the same day was the guard stopping the same run from re-drawing; the origin of the third
(`rq_0d233932...`) is outside the window. The dead end is the case where the owning run is gone.

Tests. `test_budget_crash_in_chat_leaves_the_request_running`,
`test_running_request_left_by_a_crashed_run_blocks_the_next_draw` (two variants). Guards that any fix must keep:
`test_same_run_cannot_redraw_to_bypass_a_diagnostic`, `test_resumed_request_is_not_superseded_by_a_draw_in_the_same_run`,
`test_a_live_concurrent_run_keeps_its_request`.

### 2. The 18-request budget ends a run with an exception (high)

Three runs in the window died on `UsageLimitExceeded` (`01a0b9b9b84ebc86668979b36cda2c51` on 2026-09-19,
`01a0b0a3c6bfd4b541a5cb9455459eb2` and `01a0af8e46b241962d4e037b3d606163` on 2026-09-17); a fourth died on a lead
tool retry limit (`01a0ad78de9e5e908248b6d52eb4a17c`). In the 2026-09-19 case the 18 requests were 7 by the lead,
6 by the analyst (2 for `consult_analyst`, 4 for two `answer_question` calls) and 5 by the designers (3 DeepSeek,
2 fallback). Specialist requests share the lead's budget by design (`AGENTS.md`); the gap is that the exhaustion
is an exception to the user and finding 1 follows. `providers.py:148` sets the limits; the prepare hooks
(`lead.py:218-259`) reserve tool calls for render, review and publish but not model requests.

### 3. Required columns are not carried between design calls (medium, new in this revision)

`design_visualization` passes only the current call's `required_columns` to the designer (`lead.py:467-469`).
In `01a0b9b9b84ebc86668979b36cda2c51` the first call required `rest_count`; the fallback call omitted the
argument, and the alternate designer delivered a donut of `wealthy_count` only, which the lead then recognised as
not answering the request. Test `test_required_columns_are_not_carried_to_the_next_design_call`.

### 4. Three categorical dimensions cannot be drawn, and the guards close the exits (medium)

In `01a0b9c1c45d8af82156c4c80b54ec00` the table had city, wealth level, qualification and count (53 rows). The lead
required all four columns from the first call. The designer's first run misused `fold` on a category column and
left the `group` role unbound; its second run bound two dimensions and could not bind `city`, which no chart in the
grammar takes (grouped bars bind category, group and value; there is no facet). Both designer runs died on their
two output retries. The cap then refused four more calls; only the last asked for `use_fallback=true`, which the
lead's own instructions name as the recovery (`lead.py:82-83`). The follow-up run refused one more fallback
request for the same request. In the window the cap refused 5 calls in total, 1 of them a fallback request.
Corpus: 19 of 487 readable files have three or more label columns and a measure. Nothing in the lead's instructions
says to fix one dimension (filter or aggregate through the analyst) or drop it.
Test `test_two_failed_initial_designs_also_refuse_the_fallback_designer`.

### 5. The grammar's `limit` passes the delivery check and never renders on a direct CSV (medium)

The direct reader marks every column `aggregate="none"` (`vis_agent/analyst/source.py`); the resolver refuses
`limit` on such columns (`vis_agent/designer/resolve.py:335-338`); the delivery check accepts it; and
`chart_capabilities` recommends it (`vis_agent/designer/capabilities.py:144-146`). In
`01a0b9b484d6422efc70172ee97f3392` the analyst had already selected the top three rows by SQL
(`ORDER BY avg_wage DESC LIMIT 3`); the designer added `limit 3` anyway and the render failed with "A limit needs
a category and additive values for Other", costing a design and a render before a second design succeeded.
Top-N selection itself works and is the analyst's job; the defect is the `limit` key (fold the remainder into
Other). Test `test_limit_passes_the_check_and_fails_at_render_on_a_direct_csv`.

### 6. `check_spec` approves what `deliver_design` rejects (medium)

Only `deliver_design` applies the required-column rule (`vis_agent/designer/agent.py`, `deliver_design`);
`check_spec` said ok on the same spec in `01a0b9b9b84ebc86668979b36cda2c51`, and one of the designer's two
deliveries was spent on a defect the check could have reported. In the window 45 of 247 deliveries were rejected
and the designer died on its output retries 14 times in 11 runs.
Test `test_check_spec_passes_a_spec_that_deliver_design_rejects_for_required_columns`.

### 7. A numeric year on a time axis is drawn in value order by default (medium, code-level)

The direct reader types integer years as `measure` (`analyst/source.py:88`: numeric wins before the time-name
rule). The resolver defaults a time-role axis whose column is not kind time or ordinal to `sort value desc`
(`designer/resolve.py:326-331`), and the delivery check accepts `time year` on such a column. A line chart over
2021-2024 draws the x axis as 2022, 2024, 2023, 2021. The designer rulebook tells the model to use `sort none`
for time (`designer/rulebook.md:57`), which avoids it when followed. No trace in the window drew a year axis, so
no wrong published chart is shown; the exposure is the corpus: by a strict rule (the column name is a year word or
ends in one, and every value is a four-digit year between 1300 and 2100) 39 columns in 39 files qualify, and all
39 are typed `measure`. Four `month` columns (values 1 to 12) are typed `measure` as well; the looser 47-of-48
figure of the first version counted measures such as `prev_year_count` and is withdrawn.
Tests `test_numeric_year_is_a_measure_and_the_line_chart_orders_years_by_value`,
`test_explicit_sort_none_keeps_the_source_order_of_numeric_years` (guard).

### 8. One long cell removes the column from the chart; the designer is not told (low)

Any cell over 256 bytes removes the whole column from the chart table (`analyst/source.py:82-84`). The warning
reaches the lead in the `draw` result (`requests/service.py:128`) but not the designer prompt
(`designer/agent.py:109-149`). In the corpus pass all 29 dropped columns were geometry (`wkt`, `path_wkt`), which
is the intended behaviour; the exposure is a long Arabic label. Forwarding the diagnostic to the designer is the
safe change; shortening labels in code is not, because it can merge or alter meaning.
Test `test_long_text_column_is_dropped_the_lead_is_told_and_the_designer_is_not`.

### 9. Reviewer: contradictory evidence still arrives as a `revise` verdict (low)

The verdict is derived from any `error` finding (`reviewer/agent.py:88`), and the rulebook chooses that
deliberately, including when the repair owner is `none` (`reviewer/rulebook.md:29`). The defect in
`01a0b9b80adec66a05a2684f39fbb99b` is the finding itself: its observation ends "This is consistent" and the summary
says "my initial check was mistaken", yet the level is `error`. The lead judged it and published, which is what
the instructions ask. Two code facts widen this: an `image` reference needs no evidence check
(`reviewer/agent.py:62-71`), and an error owned by `none` has no repair path (`lead.material_design_review`).
The Sep 17 analyses should be read with this: their audits found 11 false or over-strict reviewer errors and 7
unnecessary repairs in Real50, a partial-reference false alarm (case 23), extra retries when a stricter evidence
format was tried, and a real defect the reviewer caught (case 25). No deterministic reference check can verify
what the vision model saw. Recorded verdicts in the window: 25 pass and 10 revise from `deliver_review`; 104 of
139 deliveries and 106 of 148 `review_visualization` returns carry no recorded result in Logfire (the tool
results of the evaluation runs were not exported), so evaluation verdict rates must come from the saved files.
Test `test_reviewer_error_owned_by_none_yields_revise_even_when_the_summary_retracts_it`.

### 10. A published chart with misplaced labels (from the Sep 17 evaluation)

`evals/generalization/results-candidate/g04-sample_spreads-original/renders/dafbb291cb7d/chart.png` draws the
batch minimums "5 MPa", "8 MPa", "3 MPa" beside the upper whiskers at 25, 21 and 24 MPa. The delivery check
passed it, the reviewer failed three times on an invalid row reference, and the lead published it as unreviewed
(`docs/experiments/2026-09-17-generalization-results.md`, trace `01a0ad7f1841455b3575dc0494be6ab8`). This is a
renderer label-binding defect for box plots that neither code nor the inspector caught.

## Smaller items and contract mismatches

- `ask_user` goes through `active_request` (`lead.py:312-328`): it refuses `done` and `waiting` requests and
  reactivates `failed` or `stopped` ones. A question that belongs to no request ("which chart do you mean?",
  trace `01a0af8e46b241962d4e037b3d606163`, a table-only request) cannot be asked through the tool; the lead can
  ask in its text, and the instructions do not say so. Test `test_ask_user_by_request_status`.
- `consult_analyst` is hidden after one use (`lead.py:247-253`) while `answer_question` stays on offer. In
  `01a0b9b9b84ebc86668979b36cda2c51` the lead had asked the analyst for the wide shape itself, then spent two
  `answer_question` calls (4 requests) whose results cannot enter the request. The one-call rule is deliberate;
  the leak is the gap. Test `test_analyst_disappears_after_one_consultation_while_answer_question_stays_offered`.
- Wording that does not match the code, no failure shown: README says 24 model requests, code says 18
  (`requests/service.py:27`); `AGENTS.md` says aesthetics belong to agents while `designer/check.py:62` repairs
  palette contrast in code; `AGENTS.md` says SQL is the only computation path while the resolver computes
  `percent` shares and the `limit` Other total (`designer/resolve.py`).
- Check versus render parity beyond `limit`: tables longer than 78 rows fail at render, not at check
  (`designer/resolve.py:266-272`); 22 corpus files are that long.

## Candidate patches (proposals, tested in a private copy, not applied to the checkout)

| Patch | Verdict | Why |
| --- | --- | --- |
| 1 `1-check-spec-required-columns.patch` (revised) | Adopt with changes made | One shared required-column check; `check_spec` now lists it together with the other executable defects, the same list `deliver_design` reports. The first version checked it only when everything else passed. Tests: `test_check_spec_reports_the_missing_required_column`, `test_check_spec_lists_the_required_column_together_with_other_defects`. |
| 3 first version (`draw` supersedes a request opened by another run) | Rejected | A different run id does not prove abandonment: a live concurrent run's request would be marked stopped, a run that resumes and then draws would bypass the guard, and API-created or revised requests had no run id. Both failure modes are now guard tests. |
| 3 `3-finish-the-requests-a-lead-run-owns.patch` (revised) | Adopt with changes, after the owner's review | `draw`, `revise` and `resume` record the run that works on the request (`steps["lead_run_id"]`); a `Hooks` capability on the lead (`wrap_run`, the framework's run-lifecycle hook) closes the requests that run owns and left `running`: `failed` after an exception or cancellation, `stopped` after a turn that ended without publishing. The `draw` guard is unchanged; `resume` reopens a stopped request. Ownership is explicit, no abandonment is inferred, no workflow step is added. Tests: `test_budget_crash_marks_the_request_failed_and_the_next_draw_proceeds`, `test_a_turn_ending_in_text_stops_its_unpublished_request_and_resume_reactivates_it`, `test_cleanup_touches_only_the_requests_the_run_owns`, plus the three guards. Points to review: the API path already marks failures, so the two agree; an API run whose lead ends without publishing now reports `stopped` instead of `running`; the hook is not exercised under Temporal durability. |
| 4 `4-time-axis-chronological.patch` (revised) | Adopt with changes made | A time-role axis defaults to time order, numeric periods included, only when the spec gives no sort. An explicit `sort none` keeps source order (Hijri years 1447, 1445, 1446 stay as supplied, guard test) and an explicit value sort still applies (guard test). The first version reordered numeric years even under `sort none`. |

Not implemented, for the owner to weigh: reserve model requests for the final steps the way tool calls are reserved
(finding 2); carry `required_columns` across calls or say in the instructions that they must be repeated
(finding 3); hide `answer_question` during a chart request; reject `limit` at check time on direct CSVs; forward
the dropped-column diagnostic to the designer; tell the lead to fix one dimension when a table has three.

## Corpus pass (500 Dev CSVs, no model)

| Result | Files |
| --- | ---: |
| Read and typed by the direct path | 487 |
| Refused: over 10,000 rows (19,000 to 100,000), with the technical message | 8 |
| Refused: every column is geometry or oversized | 4 |
| Refused at upload: 134 MB over the 20 MB limit | 1 |
| Geometry column kept local (`wkt`, `path_wkt`) | 29 |
| One row | 170 |
| No label column | 166 |
| Three or more label columns plus a measure | 19 |
| Columns that are years (strict rule) typed `measure` | 39 of 39 |
| `month` columns (values 1 to 12) typed `measure` | 4 |
| Tables longer than the 78-row render cap | 22 |

The independent rerun reproduced every non-timing figure. Reading is fast (0.2 s for 5,000 rows by 16 columns);
the slow harness timings came from the offline recommender's pairwise column checks, which the runtime does not
run. The harness does not establish fidelity of labels, Hijri strings or leading zeros across the corpus; the
repository's unit tests cover those paths for single cases.

## Latency

79 runs in the window have a root span and exactly 8 model requests. Median wall time 19.1 s; nearest-rank
p95 117.6 s (the 76th of 79 sorted values); with linear interpolation between the 75th and 76th values the p95 is
100.9 s. The top four values are 117.6, 120.0, 120.0 and 120.0 s: three runs were cut by the evaluation harness's
120 s deadline (`evals/lead/run.py`, `turn_timeout`), so the p95 sits on that deadline. Summed over the 79 runs,
65.5% of wall time is inside the lead's own model calls, 21.2% inside the designer, 10.5% inside the reviewer and
1.7% in rendering. Model-call spans include queueing, inference, transport and any internal retries; they do not
say which. The lead makes six calls per routine run because each tool result returns to it; that is the design,
and `AGENTS.md` rules out automatic hand-offs between specialists, so the lever is the length of the lead's calls,
not their number.

## Withdrawn or corrected from the first version

- "Top-N cannot be drawn": wrong. The analyst selects rows by SQL; only the grammar's `limit` fold fails.
- "No wrong number or label in any published chart this week": wrong; see finding 10. The inspection covered the
  six charts of 2026-09-19 only.
- "47 of 48 year columns typed measure" and "20 of 44 other time-like columns": replaced by the strict rule (39 of
  39 years; 4 `month` columns), because the loose rule counted measures such as `prev_year_count`.
- "The column is dropped silently": the lead's `draw` result carries the warning; the designer prompt does not.
- "Labels, Hijri text and leading zeros survived every file": not established by the harness.
- "Two `answer_question` calls, 6 model requests": 4. The 280 s run was a table-only request, where
  `answer_question` is the intended tool; it is not an example of the leak in the donut run.
- "The cap refused `use_fallback` in 2 runs": 1 in the window; the follow-up run added one more for the same
  request. Only the last of the four refused calls in the 13:01 run asked for the fallback.
- "Let `render_visualization` hand the picture to the inspector": withdrawn; `AGENTS.md` forbids automatic
  hand-offs.
- Duplicate-execution 202 responses, sibling version numbers, the timing of table invalidation, and
  `no_chart_reason` skipping review: withdrawn as defects; the first two are wording differences without a shown
  failure, and a table fallback has no image to review.
- "p95 is provider variance": withdrawn; the spans do not separate causes, and three of the top values are the
  evaluation deadline.
- Patch 3, first version: rejected (see the table).

## Appendix: queries and verification

Window for every query: `start_timestamp` 2026-09-16T00:00:00Z, `end_timestamp` 2026-09-19T13:03:00Z, project
`vis-harness`, table `records`.

Headline counts (one query):

```sql
SELECT
  sum(CASE WHEN span_name = 'invoke_agent vis-lead' AND parent_span_id IS NULL THEN 1 ELSE 0 END) AS lead_root_spans,
  sum(CASE WHEN span_name = 'invoke_agent vis-lead' AND parent_span_id IS NULL
           AND exception_type = 'pydantic_ai.exceptions.UsageLimitExceeded' THEN 1 ELSE 0 END) AS lead_usage_limit,
  sum(CASE WHEN span_name = 'invoke_agent vis-lead' AND parent_span_id IS NULL AND coalesce(is_exception,false) THEN 1 ELSE 0 END) AS lead_exceptions,
  sum(CASE WHEN span_name = 'execute_tool draw' AND exception_message LIKE '%already active in this conversation%' THEN 1 ELSE 0 END) AS already_active,
  sum(CASE WHEN span_name = 'execute_tool deliver_design' THEN 1 ELSE 0 END) AS deliver_design_calls,
  sum(CASE WHEN span_name = 'execute_tool deliver_design' AND coalesce(is_exception,false) THEN 1 ELSE 0 END) AS deliver_design_rejected,
  sum(CASE WHEN span_name = 'invoke_agent designer' AND exception_message LIKE '%Exceeded maximum output retries%' THEN 1 ELSE 0 END) AS designer_deaths,
  count(DISTINCT CASE WHEN span_name = 'invoke_agent designer' AND exception_message LIKE '%Exceeded maximum output retries%' THEN trace_id END) AS designer_death_traces,
  sum(CASE WHEN span_name = 'execute_tool design_visualization' AND exception_message LIKE '%already used its two initial design attempts%' THEN 1 ELSE 0 END) AS cap_refusals,
  sum(CASE WHEN span_name = 'execute_tool design_visualization' AND exception_message LIKE '%already used its two initial design attempts%'
           AND attributes->>'gen_ai.tool.call.arguments' LIKE '%use_fallback":true%' THEN 1 ELSE 0 END) AS cap_refusals_of_fallback
FROM records
-- result: 162, 3, 4, 3, 247, 45, 14, 11, 5, 1
```

Review results (one query):

```sql
SELECT span_name,
  CASE WHEN attributes->>'gen_ai.tool.call.result' IS NULL THEN 'no result recorded'
       WHEN attributes->>'gen_ai.tool.call.result' LIKE '%"next":%' THEN 'cached repeat'
       WHEN attributes->>'gen_ai.tool.call.result' LIKE '%"verdict":"pass"%' THEN 'pass'
       WHEN attributes->>'gen_ai.tool.call.result' LIKE '%"verdict":"revise"%' THEN 'revise'
       WHEN attributes->>'gen_ai.tool.call.result' LIKE '%not_reviewed%' THEN 'not_reviewed' ELSE 'other' END AS kind,
  count(*) AS n, count(DISTINCT trace_id) AS traces
FROM records WHERE span_name IN ('execute_tool review_visualization', 'execute_tool deliver_review')
GROUP BY 1, 2 ORDER BY span_name, n DESC
-- deliver_review: no result 104 (90 traces), pass 25, revise 10 (8 traces)
-- review_visualization: no result 106 (93 traces), pass 25, revise 10 (8 traces), not_reviewed 4, cached repeat 3
```

Latency (one query; percentiles computed from the returned sorted list):

```sql
WITH leads AS (
  SELECT trace_id, span_id, duration AS total_s FROM records
  WHERE span_name = 'invoke_agent vis-lead' AND parent_span_id IS NULL
), lead_chats AS (
  SELECT c.trace_id, sum(c.duration) AS lead_model_s FROM records c
  JOIN leads l ON c.trace_id = l.trace_id AND c.parent_span_id = l.span_id
  WHERE c.span_name LIKE 'chat %' GROUP BY c.trace_id
), parts AS (
  SELECT trace_id,
    sum(CASE WHEN span_name = 'invoke_agent designer' THEN duration ELSE 0 END) AS designer_s,
    sum(CASE WHEN span_name = 'invoke_agent reviewer' THEN duration ELSE 0 END) AS reviewer_s,
    sum(CASE WHEN span_name = 'execute_tool render_visualization' THEN duration ELSE 0 END) AS render_s,
    sum(CASE WHEN span_name LIKE 'chat %' THEN 1 ELSE 0 END) AS model_reqs
  FROM records GROUP BY trace_id
), runs AS (
  SELECT l.total_s, lc.lead_model_s, p.designer_s, p.reviewer_s, p.render_s
  FROM leads l JOIN lead_chats lc ON l.trace_id = lc.trace_id JOIN parts p ON l.trace_id = p.trace_id
  WHERE p.model_reqs = 8
)
SELECT count(*), sum(total_s), sum(lead_model_s), sum(designer_s), sum(reviewer_s), sum(render_s),
       array_agg(round(total_s, 3) ORDER BY total_s) FROM runs
-- 79 runs; sums 2443.2, 1601.2, 519.1, 256.8, 41.2 s; sorted[39] = 19.123, sorted[75] = 117.64, sorted[74] = 98.982
```

Corpus year rule (Python over `results.jsonl` and the CSV files): a column qualifies when its name matches
`(^|_)(year|سنة|السنة|عام|العام)$` and every non-empty value matches `\d{4}` between 1300 and 2100; 39 columns
qualify, all typed `measure`. The looser `(^|[_\s])(year|...)($|[_\s])` rule matches 48, including
`prev_year_count`, `previous_year_count` and `employed_within_year_salary`.

Verification of this revision: at the start of the revision the tracked working-tree changes had been staged by
another session (the index held 44 modified and the new experiment files; HEAD had moved to 53a77f0), so the
invariant used is the unstaged diff outside the authorized files, which was empty before the first write and
empty after the last. The three revised patches apply cleanly to the checkout (`git apply --check`) and were
applied only in a private copy of the working tree, where the existing suite passed (1949 tests) and the fix
tests passed with `--runxfail`. The shared checkout was not modified beyond the report, the two test files and
the patch files, and nothing was committed over the other session's staged index.
