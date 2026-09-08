# Phase 6 lessons: the lead and the conversation

## Exit test

Date: 2026-09-08. Models: lead `openrouter:anthropic/claude-sonnet-4.6` with the advisor
`openrouter:openai/gpt-5.6-sol`; profiler, analyst, and designer `openrouter:google/gemma-4-31b-it:nitro`.

- A request killed mid-run resumes from its last checkpoint: met, with real models (see "What the runner
  records for a killed run") and in `tests/requests/test_runner.py` (a design step that dies leaves the
  analyze checkpoint, and the resume does not run the analyst again).
- A revise produces a linked version: met in the web chat (version 2 with its parent, the root question, and
  the change) and in the runner and lead tests.
- A clarification round-trips with a human and with a program: met in the web chat (the youth question) and
  in `tests/requests/test_api.py` (a program receives the question at its return address, posts the answer,
  and receives the artifact); the program path also ran against the live server for a request with no
  question.
- Tool choice on the twenty evaluation cases: see the table below.

Unit suite at the end of the phase: 975 tests. Analyst evaluation 70 of 70 tables (up from 69 cases; the new
case is `age_group_share_summed`); in the last run, after the rulebook's aggregate sentence was reworded, every
table still matched and one case (`monthly_violations_2025`) failed its checks-clean assertion on the summary,
which is the run-to-run variance seen in Phase 4b. Designer agent evaluation 31 of 31 with every automatic
score 1.00; the model-free designer set 37 of 37.

## Lead evaluation

Final run on the merged branch at 40a9877, `uv run python -m evals.lead.run --corpus` (results in the session
scratchpad as `lead-results-final-2.json`; 3.7 minutes with three cases at a time):

| Set | Cases | Turns | Tool choice | Outcome | Redo analysis | Notes |
| --- | ---: | ---: | --- | --- | --- | --- |
| Eleven scripted conversations | 10 of 11 | 19 | 17 of 19 | 18 of 19 | 3 of 3 | the missing-column case, below |
| Ten corpus questions, seed 11 | 8 of 10 | 10 | 8 of 10 | 8 of 10 | none expected | two files answered from the profile |
| Together | 18 of 21 | 29 | 25 of 29 | 26 of 29 | 3 of 3 | exit line: at least 18 of 21 cases |

The three misses:

- `missing-column-resume`: "Chart the number of citizens by region" on a file with no region column. The
  lead saw the column list in the profile it had just fetched and said so itself instead of calling `draw`
  and letting the analyst ask; the answer "use gender instead" then went to `draw`, not `resume`. The chart
  was right. The case wanted the analyst's question so that the pause and the resume would be exercised
  through the chat; that path is proven by the runner and channel tests and by the youth question in the web
  chat, but the lead pre-empts an obvious missing column when it can see the columns.
- `corpus-vizcsv-97280400c00748a7`: a one-cell file (`male_count` = 0) asked for the male-to-female ratio.
  The lead said the file cannot answer, without a tool. True, and the analyst would have said the same as a
  question.
- `corpus-vizcsv-ba0187c944a3f829`: "how many cities" on a seventeen-row list. The lead counted from the
  profile's statistics instead of calling `answer_question`, despite the instruction added for exactly this;
  the count was right.

How the numbers moved during the phase: the first full run scored 15 of 17 scripted turns and 3 of 10
corpus turns under a strict "always draw" expectation. Three changes followed, each measured: the lead no
longer asks before calling a tool (the specialists ask); values are answered through the analyst, never
from the profile; corpus turns count a chart, a question, or a table, because the corpus files are
result-table exports and four of the ten hold a single cell. The scripted clarification case was rewritten
twice: its first version told the lead to ask, which tests obedience, not the flow; its second used a vague
term ("poverty line") that the analyst answered with a stated assumption, which the "do not ask
needlessly" rule allows, so the case now accepts a question or an assumption and then a resume or a
revision, and a separate case asks for a column the file lacks.

Confirmed lessons: the lead follows an explicit "ask me first" literally, so evaluation messages must never
contain one; a chart-first lead still answers "how many" questions with a value, which is right; the
specialists' asking is a judgment that the evaluation can only bound, not force; and per-case scoring is
what the exit test reads, so the runner prints both.

## Web chat check

On the owner's running server (uvicorn from the working tree, reloaded by the merges), with the Turkish
population CSV `vizcsv-5b598d47ed1741aa.csv` uploaded through the channel with a brief:

- "ارسم رسمًا بيانيًا يقارن نسبة كل فئة عمرية بين السكان الأتراك ومتوسط المملكة" with the attachment line:
  `profile_csv` then `draw`; a grouped column in Arabic, right to left, with the table, notes, assumptions,
  and one line of IDs (`art_ecc8b749…`, `rq_cd1d1be8…`). The picture showed inline. The numbers were wrong,
  though: the analyst averaged the male and female shares (0 to 14: 16.67 instead of 33.33).
- "اجمع نسب الذكور والإناث بدلًا من أخذ متوسطها": `revise` with `redo_analysis` true, chosen by the lead and
  said aloud; version 2 linked to version 1, `SUM(percentage)` in the SQL, the root question kept and the
  change recorded, all seven steps saved, the conversation ID on the request.
- "كم عدد السكان الأتراك الإجمالي؟ أرقام فقط بدون رسم": `answer_question`, 114 people, with the brief's
  caveat that the file is an extract.
- "ما نسبة الشباب بين السكان الأتراك؟ ارسمها": the lead asked which definition of youth to use before calling
  any tool; "15–24 سنة" then went to `draw`, the result was a single number (14.91%), so no chart was drawn,
  which is right, but the lead then offered two chart ideas instead of stopping at the number and its IDs.
- Continue and artifact recall were exercised through the evaluation set rather than by hand.

The averaged shares were the analyst's rulebook: "average percentages, never sum a percentage". Shares of one
whole add; the rule now says so when the brief or the column meaning says the percentages share one
denominator, and the Turkish file is an analyst evaluation case with its brief.

## Thirty conversations in the browser

Run on 2026-09-08 through the chat page in the in-app browser, against a second server instance on port 7933
with its own data folder and database, so the owner's server and data were untouched. Twelve datasets were
uploaded through `/datasets/upload` with their briefs, exactly as the Upload CSV button does, and every message
was typed into the composer with the attachment line the button adds. Thirty cases, 43 turns, twelve
cases with follow-ups. Verdicts: 23 cases passed outright, 5 passed with a note, 2 failed on a turn
(34 turns passed, 7 with a note, 2 failed).

| Case | Dataset | Turns | Verdict | What happened |
| --- | --- | ---: | --- | --- |
| 1 | Turkish population (with brief) | 3 | pass | draw: grouped_column, shares summed (0-14 = 33.33), table, notes, IDs, picture shown Then: revise picture only: version 2 linked, grouped_bar, second picture shown; the reply omitted the table on a picture-only change Then: artifact recall: both versions listed with IDs and types, from the conversation, no tool call needed |
| 2 | Turkish population (with brief) | 1 | pass | answer_question: 114, no chart; the analyst's total-check warning about excluded rows reads oddly for a deliberate filter |
| 3 | Turkish population (with brief) | 1 | pass | draw: gender shares summed per population, English reply, picture shown, caveats from the brief |
| 4 | Turkish population (with brief) | 1 | pass | continue with a fresh attachment: nothing to continue, the lead proposed five questions with reasons instead of failing |
| 5 | citizens.csv | 2 | pass | draw: grouped chart shown, table with code meanings from the brief, warnings explained Then: revise with redo_analysis true: filtered to females, version 2, second picture, the lead said the analysis was re-run |
| 6 | citizens.csv | 1 | pass | answer_question: averages by gender, no chart |
| 7 | citizens.csv | 2 | fail | missing column: the lead listed the columns and asked which to use itself (no draw, no request); a fair question, but it pre-empts the analyst Then: draw after the answer: analyst fine (4 F / 4 M) but the designer hit its request limit on a two-row result; table delivered with the reason, no picture |
| 8 | citizens.csv | 2 | pass | draw: the analyst took the wealthy flag as high earner and said so; single number 50%, no chart by design; the lead offered follow-ups Then: revise with redo: income above 60000, single number again, assumption restated, no chart by design |
| 9 | arabic.csv | 2 | fail | draw: Arabic bar by city, picture, table, totals summed across dates and said so Then: title-only revision: two revisions came back without a chart (designer exceeded output retries), the lead reworded and retried, the third drew with the new title; two stray artifacts |
| 10 | arabic.csv | 1 | pass | monthly trend on one month of data: single row, no chart, honest explanation and alternatives offered |
| 11 | arabic.csv | 1 | pass | answer_question: top city Riyadh 3,150, no chart |
| 12 | conflict_codes.csv | 2 | pass | draw: tickets by status with code meanings from the brief, picture, notes the unused code Then: revise picture only: donut 2 True, second picture, table repeated |
| 13 | seeded-13 (Arabic categories) | 2 | pass | draw: Arabic region categories, picture, table with unit Then: revise with redo: sorted descending, the three regions are all there are and the lead said so, second picture |
| 14 | seeded-13 (Arabic categories) | 1 | note | attachment only: profile summary with columns and statistics (the file's own diacritics kept), but one suggested question instead of three to five |
| 15 | seeded-19 (Hijri years, 22k rows) | 1 | note | draw over 65 Hijri years: the designer delivered a table type, the lead revised it to a line on its own, final line with two series shown, 20-row table with the total |
| 16 | seeded-19 (Hijri years, 22k rows) | 1 | pass | answer_question: total paid violations 857,421, no chart |
| 17 | seeded-01 (Hijri dates, 22k rows) | 2 | note | draw over 22k rows: Hijri months bucketed as text (769 months), designer chose a table for that many buckets, table picture shown, the lead offered a line for a period Then: revise with redo: yearly averages over 65 Hijri years, correct numbers, but the designer chose a table again (year-like column not treated as time), the lead offered a line |
| 18 | fines corpus file (1000 rows) | 2 | pass | draw: total fine by district over 1000 rows, values match the analyst evaluation's expected table, picture, warnings shown Then: revise with redo: top five districts, second picture, the lead said the numbers changed and why |
| 19 | fines corpus file (1000 rows) | 1 | pass | draw: violations per month in Arabic, picture, partial-month caveat |
| 20 | regions corpus file | 1 | pass | the home-machine question: draw with no question asked, 16-row table, percentage column used with the assumption stated, picture |
| 21 | citizens/residents corpus file | 2 | pass | draw: donut as asked, citizens vs residents with shares, picture Then: revise picture only: pie labels on percent, second picture |
| 22 | gender by region corpus file | 2 | pass | draw: gender shares by region from the percentage column, 16-row table, picture Then: revise with redo: top five regions by female share, second picture, assumptions stated |
| 23 | population report corpus file | 1 | pass | report request: draw plus answer_question, a chart with a written analysis in Arabic |
| 24 | Turkish population (with brief) | 1 | pass | unknown artifact id: the lead said the id does not exist and offered three questions; no invented chart (it reasoned from the fresh conversation rather than calling revise) |
| 25 | none | 1 | note | file never uploaded: find_dataset called, then one draw call that errored, then the right answer (upload it first); nothing invented |
| 26 | citizens.csv | 1 | pass | Arabic question on an English file: draw, Arabic reply, averages by gender, picture |
| 27 | Turkish population (with brief) | 1 | pass | two numbers asked: answer_question, 33.33 vs 32.31 with shares summed, no needless chart |
| 28 | fines corpus file (1000 rows) | 1 | pass | draw: average fine by violation type, long Arabic labels kept with translations, picture, assumption stated |
| 29 | seeded-19 (Hijri years, 22k rows) | 2 | note | draw over 65 Hijri years: line [('السنة الهجرية', 'ordinal'), ('إجمالي المخالفات المدفوعة', 'measure')], picture, 20-row table with the total Then: revise with redo added the second series, but the designer returned a table (two-series line over 65 years exceeds its limit); the lead explained and offered a shorter range, bucketing, or two charts |
| 30 | citizens.csv + arabic.csv | 1 | pass | two attachments: the lead drew from the Arabic file as asked, picture, table |

The two failures and what was done:

- Case 9, a title-only revision: the designer's delivery check refused an explanation that mentioned the year
  from the caller's own title ("The summary mentions 2026, which is not in the result"), twice; the lead
  retried with rewordings and finally changed the data to make the check pass, leaving two chartless
  artifacts. Fixed in 6d89cd7: numbers the caller wrote in the change or in an answer count as wording, in
  the designer's and the analyst's number checks. Rerun after the fix: one revision, the new title, version 2.
- Case 7, a chart after a missing-column answer: the designer hit its eight-request budget on a two-row
  gender count and the runner delivered the table with the reason. The same report designs cleanly in three
  requests when run again, so this was provider variance in the designer's model; the graceful path held.
  Rerun after the fix: the lead called `draw`, the analyst asked which column stands for region, the answer
  went through `resume`, and the chart was drawn.

The notes, in order of weight, and what was done about each before the merge:

- Long Hijri series: the designer chose the table type for 65 years with two series (cases 15, 29) and for
  769 or 65 buckets with two measures (case 17), while a single series over 65 years drew as a line (case 29
  turn 1). The cause was upstream of the designer: the analyst returned one column per measure (paid, unpaid),
  which the designer cannot draw as two series. The analyst's rulebook now asks for long format when two or
  more measures of one unit are compared over one axis (one row per axis value and measure, a series column,
  one value column); measures of different units stay side by side. Case 15 rerun: 130 rows in long format
  and a two-series line. Case 17's 769 buckets stay a table by the designer's own limit.
- With a dataset attached and no question the lead proposed one question instead of three to five (case
  14). The instructions now ask for a numbered list of three to five, each with a reason, using only columns
  that exist. Rerun: three suggestions with reasons.
- A picture-only revision sometimes omitted the table under the new picture (case 1 turn 2). The
  instructions now say every artifact gets its table, a picture-only revision included. Rerun: the table
  is repeated under the new picture.
- The analyst's note about rows excluded by a deliberate filter read oddly (case 2). The `total_explained`
  check now names the WHERE clause when the query filtered on purpose ("expected when the question asks
  for a subset") and keeps the "dropped rows" wording for a query with no filter.
- On a file that was never uploaded the lead called `find_dataset`, then one `draw` that errored, before
  answering correctly (case 25). Two changes: `draw` and `answer_question` accept an upload's file name
  through one `resolve_dataset` (a name that matches nothing is a plain failure that tells the lead to ask
  for the upload, a malformed ID is still a retry), and `find_dataset` returns a sentence when nothing
  matches instead of an empty list. A wording rule alone did not stop the extra call: with the empty list
  the lead still tried `draw` in two reruns; with the sentence it stopped. Rerun: one `find_dataset` call
  and the right answer.
- Found while re-running the lead evaluation after these changes: on "now draw it" after a numbers-only
  answer the lead called `resume` thirteen times because the failure said only that nothing was unfinished.
  The message now says to treat the message as a new question and call `draw` or `answer_question`, and
  the instructions say to call `resume` at most once for a message. Browser check: "numbers only" then
  "now draw it" gives `answer_question` then `draw`.
- The lead pre-empts an obvious missing column from the profile in some runs (case 7 first run) and lets
  the analyst ask in others (the rerun); both end well. Left as is.

After the fixes: the unit suite passes (980 tests), and the lead evaluation on the final code is at its
earlier level: 18 of 21 cases, 27 of 29 turns on the expected tool, 26 of 29 outcomes, redo 3 of 3. The
analyst evaluation with the long-format rule gave 69 of 70 tables with every check clean on its first run.
Two later runs gave 67 of 70 each: the first while the lead evaluation, the browser runs, and the unit
suite shared the provider (three times the usual time per case, three semantic profiles timed out, one
lost), the second alone at normal speed. The misses were not the long-format rule: in each run two or
three plain questions came back as clarification questions, a different set each time (whether "singles"
includes the divorced, whether an overall share should be split by date, how to spell Jeddah in Arabic,
a question that only restated the user's question, and once a question with nothing in it). Rerunning
those six cases four times gave the same rate before and after a rulebook clause against each of them
(three asks in twelve attempts either way), so the clause was dropped. The empty question is now sent
back to the model as a retry. The spurious questions started in the evening's runs after four runs at
69 or 70 without one, on the same analyst code, so the provider's route for the model is the first thing
to check; the lead handles such a question gracefully, but the user is asked something the data already
answers. It is the first item under "Left for later".

Everything else behaved as designed: chart first with the table, IDs shown once, revisions deciding
`redo_analysis` correctly (picture-only for horizontal bars, donut, pie, title; re-run for filters, sums,
top-N, added series), numbers-only questions answered without a chart, single-number answers without a
chart, Arabic and English replies following the question, code meanings from briefs, a fresh "continue"
turned into suggestions, an unknown artifact ID refused plainly, and the right file chosen when two were
attached.

A setup lesson: the project's `.env` pins `DUCKDB_PATH`, so a second instance started with only
`DATA_DIRECTORY` wrote its dataset rows into the main database; set both variables for an isolated instance.

## What the runner records for a killed run

Scratch script `killed_run.py`: a fresh store, the Turkish CSV with its brief, a terminal request, and the run
cancelled the moment the analyze checkpoint appeared (8.2 seconds in).

- After the kill: status `running`, steps `understand`, `profile`, `analyze` saved, no artifact.
- `run_request` again: 4.2 seconds, status `done`, the analyze output byte-identical to the saved one, the
  steps `design`, `render`, `review`, `deliver` added, a grouped column delivered with 14 rows.

A crash inside a step (an exception rather than a kill) is recorded as `failed` with the error in plain
words and the same checkpoints; resume treats both alike.

## Channel round trip

Scratch script `channel_roundtrip.py` against the running server, with a small HTTP receiver on port 7999:

- `POST /requests` with the dataset, an Arabic question about gender shares, an identity, and the return
  address: 202 with the request ID.
- `GET /requests/{id}` polled every three seconds: `done` with all seven steps.
- One callback received, status `done`, carrying the artifact ID; `GET /artifacts/{id}`: version 1, a grouped
  column, the picture URL, and gender shares summed per population type.
- The pending-question path (a callback with `waiting`, `POST /requests/{id}/answer`, a second callback with
  `done`) is covered by `tests/requests/test_api.py` through the app's own callback route.

## Costs

Models: lead `openrouter:anthropic/claude-sonnet-4.6` (advisor `openrouter:openai/gpt-5.6-sol`), specialists
`openrouter:google/gemma-4-31b-it:nitro`. Wall time with three cases at a time: the twenty-one-case lead
evaluation 3.7 minutes (6.5 minutes for the first run, which hit two profiling timeouts on large corpus
files); the seventy-case analyst evaluation 5.3 minutes; the thirty-one-case designer evaluation 1.2 minutes.
A chat turn that draws costs eight model requests with the fake models (lead two, profiler one, analyst two,
designer three) and nine to twelve with real ones when the analyst or designer repairs once; a revision
without new analysis costs the lead's two plus the designer's three. Tokens and money per run are in Logfire
(project vis-harness), not in the results files; the evaluation runner records tool calls and IDs only.

## The designer's loop

Logfire raised an issue on the evening of 2026-09-08: `UsageLimitExceeded`, "request_limit of 14", on the
web chat's Arabic question about population by age group and gender in Riyadh. The trace showed the whole
story. The lead spent two requests, the analyst four and answered correctly, and then the designer (Gemma
4 31B, temperature 0) called `recommend_charts(intent="composition")` eight times in a row, sixteen output
tokens each. Calls one and two returned a valid shortlist with grouped bars on top; calls three to eight got
the refusal text, and the model re-emitted the same call until the request cap (the six requests already
spent plus the designer's eight). The user got the table and no chart. Logfire showed the same signature in
three of the 68 designer runs of the previous two weeks, one of them in the afternoon's browser run, where
it went by as "the designer could not finish" without being chased.

Root cause. The budget was advisory: after two calls the tool stayed in the model's tool list and the
"you have used your calls" message came back as a normal, successful tool result, which the library counts
as success. A small model at temperature 0 that repeats once repeats forever, and nothing in the code
broke the repetition. Codex, asked for a second opinion at high effort, agreed and added two things: the
rulebook never told the model the two-call limit or forbade repeating, and the code accepted the same
intent twice as a valid call. The analyst's `run_query`, the designer's `check_spec`, and the lead's
`resume` used the same soft pattern; `check_spec` had already been ignored twice, and `resume` had once
looped thirteen times before a wording fix.

The fix, on the `fix/tool-budgets` branch, uses what Pydantic AI 2.38 provides and nothing else: the
tool's `prepare` hook returns `None` once its calls are spent, so the tool is withdrawn from the following
requests, and a model that still names it gets one unknown-tool retry before the run ends with
`UnexpectedModelBehavior`, which the callers already catch; an over-budget call inside one response is a
`ModelRetry` on a tool registered with `retries=1`. A first version also answered a repeated intent with a
retry prompt: the designer evaluation dropped from 31 to 25 delivered, because Gemma answers a retry prompt
by repeating the call, so a benign second call became a dead run. The prompt was removed; a second call
within the budget is simply accepted. Applied to `recommend_charts`, `check_spec`, `run_query`, and `resume` (withdrawn while the chat
conversation has nothing unfinished; the terminal and programs keep it). The request runner now runs the
design step once more on a fallback designer when the first run fails (`PYDANTIC_AI_DESIGNER_FALLBACK_MODEL`,
the lead's model by default) and says so in a warning, and the "could not finish" prefix is no longer
doubled. The library has no detector for repeated identical calls, and `tool_calls_limit` is a global cap;
neither replaces the hooks.

The lesson that outlasts the patch: the old tests certified the bug. They asserted that the third call
returned a refusal message, so they proved the model was told, not that it was stopped. The test for every
budget now drives a model that ignores the message and asserts the run ends within a fixed number of
requests. And a specialist that "could not finish" in a test run is a defect to trace, not a note; one
Logfire query on agent-run exceptions shows the count in seconds.

Evaluations after the fix: unit suite 989 passed; model-free designer evaluation 37/37; designer agent
evaluation 31/31 delivered with every score at 1.00 and 3.4 requests per run; lead evaluation 17/21 cases,
tool choice 27/29, outcome 25/29, redo analysis 3/3. The four misses are the two one-cell corpus files the
lead answers from the profile (known) and two needless analyst clarifications (the open item below), one of
them repeated after the user's answer, where the lead resumed a second time and the chart was drawn. In the
run on the stricter first version the designer looped for real on "average income by gender" and was cut at
three requests instead of nine.

### Open-weight models tried after the loop

On 2026-09-09 the owner asked for an open-weight alternative to Gemma 4 31B for the specialists. The lead
runs on Sonnet 4.6; Gemma is the profiler, analyst, and designer because the two inherit the profiler's
default. Candidates came from OpenRouter's live list: open weights (a Hugging Face id), tool calling, input
under one dollar per million tokens, then the recent and plausible ones. Each ran the 31-case designer
evaluation once under the new budgets; the four that matched or nearly matched Gemma as designer also ran
the 70-case analyst evaluation.

| Model | Designer, delivered | Requests | Seconds | Analyst, tables right | Price in/out per M |
|---|---|---|---|---|---|
| Gemma 4 31B (current) | 31/31 | 3.6 | 4.8 | 67 to 70/70, 7 s | 0.09 / 0.34 |
| Kimi K2.6 | 31/31 | 3.5 | 5.8 | 61/70, 13 s, six timeouts | 0.95 / 4.00 |
| DeepSeek V4 Pro | 31/31 | 3.3 | 9.1 | 66/70, 7.9 s | 0.58 / 1.74 |
| Qwen 3.8 Flash | 30/31 (a rate limit) | 3.7 | 15.7 | failed nearly every delivery | 0.15 / 0.47 |
| MiniMax M3 | 30/31 | 3.4 | 6.1 | 61/70, 7.0 s | 0.30 / 1.20 |
| MiMo V2.5 | 30/31 | 3.5 | 12.0 | not run | 0.14 / 0.28 |
| Gemma 4 26B MoE | 28/31 | 3.7 | 5.7 | not run | 0.07 / 0.34 |
| DeepSeek V4 Flash | 27/31 | 3.9 | 10.3 | not run | 0.07 / 0.18 |
| Mistral Small 4 | 22/31 | 4.4 | 7.9 | not run | 0.15 / 0.60 |

GLM 5.3 Flash and gpt-oss-120b cannot run at all: their endpoints refuse a request with reasoning
disabled, which the designer and analyst set; testing them needs an agent variant that allows reasoning.
Nemotron 3.5 Lightning was rate-limited upstream on both attempts. No candidate looped. The analyst misses of
the candidates are extra rows and columns the question did not ask for and vague questions answered
instead of asked, the same kinds Gemma makes, only more often.

Reading: nothing cheaper than Gemma beats it on either evaluation; the two that match it as designer cost
six to ten times more and are worse as analyst. Gemma stays, with the budgets and the fallback designer
covering its loops. The closest all-rounder for a later switch is DeepSeek V4 Pro; a decision should rest
on the two-hundred-case scale set, since one run of 31 cases cannot see a one-in-twenty loop rate.

## Left for later

- The analyst sometimes returns a clarification question for a plain question (about one case in
  twenty-five in the evening's runs, none in the afternoon's), including questions that restate the
  user's question. Check the provider's route for the analyst model first, then consider a check that
  refuses a clarification whose question repeats the user's question, and a tuning round on the
  analyst's rulebook with the analyst evaluation as the metric.
- After a single-number result the lead delivers the number without a chart, as designed, but then offers
  chart ideas instead of stopping; if the evaluation shows it often, add one sentence to the instructions.
- On the vague "youth" question the lead asked for the definition itself, before any tool ran. The
  instructions now say the specialists ask; the lead still pre-empts an obvious missing column it can see in
  the profile (the evaluation's `missing-column-resume` case), which is right for the user but skips the
  request and its pause.
- `resume` with no ID needs a conversation ID; the terminal always names the request, and the chat adapter
  always supplies one, so the gap is only in a program that calls the lead directly.
- Overdue questions are reported, never expired; nothing moves a waiting request to stopped on its own.
- The review step is a placeholder that records "not reviewed"; Phase 5 fills it without changing the
  step order.
- The built-in chat cannot take a free-text answer to a tool's question, so the pause is relayed by the
  lead in prose and the answer comes back as a plain message; approvals in that UI are yes or no only.
- The in-process guard against running one request twice is per process; two servers on one database
  would need a lock in the store.
- Requests and artifacts are filtered in Python after reading every row; fine for a local tool, and the
  place to push filters into SQL if the history grows.
- The channel's callback client is never closed at shutdown; a lifespan hook would tidy that.
- The designer evaluation runner still records `build_prompt(...).model_dump()` as case metadata, so its
  saved inputs carry two empty fields the model never sees; harmless.
- Codex could not write reports into the repository's `.superpowers` folder from a worktree sandbox;
  reports go to `/private/tmp` and the controller copies them.
- The lead pre-empts the analyst when the profile already shows a column is missing, and it answered a row
  count from the profile once in ten corpus questions despite the instruction; both are right for the user
  and skip the analyst's checks. Measure with the evaluation before tightening the instruction further.
- The corpus half of the lead evaluation is a stress test over result-table exports; four of ten files hold
  one cell. A corpus export that keeps source tables (already on the Phase 4b list) would make it a real
  tool-choice measure.
