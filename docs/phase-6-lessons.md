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

## Left for later

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
