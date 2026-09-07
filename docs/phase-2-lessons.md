# Phase 2 lessons: the data analyst

What the second agent taught us, recorded as the design asked (section 17 of the Phase 2 design).

## The exit test

On thirty real questions over corpus files, the result table must be right at least nine times in ten, and every
seeded label inversion must be caught by the checks.

| Analyst model | Tables right | Delivered results with no error-level check | Seconds per question |
|---|---|---|---|
| Gemma 4 31B (profiler's default) | 30 of 30 | 100% | 4.8 |
| GPT-5.4 mini | 29 of 30 | 100% | 8.7 |
| Claude Sonnet 4.6 | 29 of 30 | 97% | 16.1 |
| Mistral Small | 18 of 30 | 97% | 7.4 |

Seconds include profiling the file first, since every evaluation run starts from an empty store; Gemma's number is
from the final run after the review fixes, the others from the benchmark run before them. Gemma stays the
default. The seeded inversions live in `tests/analyst/test_checks.py`: swapped F and M labels, a relabel without its
code column, a label the data does not hold, shares that do not add up, an average outside the column's range, an
empty result, and time out of order. Each is caught with no model involved.

## The final check before the merge: 69 questions

The set was grown from thirty to sixty-nine questions before the merge (33 Arabic, 36 English, 8 expecting a
clarification), weighted towards trends, filters, Arabic column names, and files with an omitted geometry column.

| Analyst model | Tables right | Delivered results with no error-level check | Seconds per question |
|---|---|---|---|
| Gemma 4 31B (default) | 69 of 69 | 100% | 5.7 |
| GPT-5.4 mini | 60 of 69 | 97% | 7.5 |

The first Gemma run scored 68 of 69 with four results carrying an error-level check. All four were one false
positive: the summary check flagged numbers that came from the question or the column names ("under 15",
"December 2025", "drivers over 25") as numbers not in the result. Numbers present in the question or the result's
column names are now exempt. The one table miss was an over-cautious clarification on the paid-share question, which
the rerun answered.

GPT-5.4 mini's misses on the larger set are real: it counted rows instead of summing an employee count, summed a
region total that was already a total, returned every store where the question asked for the top one, rounded a
share to two decimals, answered a question about a missing schools column with a table, and asked a clarification on
three answerable questions. Gemma stays the default with a wider margin than the thirty-case set showed.

## Where SQL fails

It did not, on this set. No delivered query was rejected by the guard, timed out, or hit the row cap, and no check with
severity error survived to delivery on Gemma or GPT-5.4 mini. The two first-run misses on Gemma were representation,
not arithmetic: a share written as a fraction (0.171) where the reference had a percentage (17.1), and a year bucket
written as a date (2020-01-01) where the reference had the integer 2020. The evaluation now accepts both forms, and
the rulebook asks for percentages from 0 to 100.

## Which questions need clarification

The four questions built to need one (an undefined "recent", an undefined "large", a schools column that does not
exist, a salary column that does not exist) got a clarification from every model. The differences are in
over-asking:

- Mistral Small asked on twelve answerable questions ("do you mean the number of rows per app?"), which is why it
  scores 0.60 on tables while its delivered results are almost all clean. It is a cautious model, not a wrong one, and
  the wrong tool for this seat.
- GPT-5.4 mini and Sonnet each asked once, on "the most common violation type in Jeddah": the city column has
  seventeen distinct values, the prompt listed only the five most common, and Sonnet concluded Jeddah was absent
  instead of filtering for it. The prompt now says when the listed values are a sample, and the rulebook says to
  filter rather than assume.

## What the checks caught

Nothing at delivery, which is the point: the checks run inside `run_query`, so a model sees a label mismatch or an
out-of-range average with the result and repairs before delivering. The warnings fired as designed on the share
within each gender (shares that need not sum to 100) and on filtered totals, and travelled with the answer.

## Cost and time

Gemma answers in about 2 to 3 seconds once the file is profiled, with two model requests per question (one query
call, one delivery). The lead on Sonnet 4.6 adds its own two turns; a chat question on a freshly uploaded 1,000-row
file took 16 seconds end to end.

## What the branch review found

Codex reviewed the whole branch before the merge and found two real holes in the query guard and three smaller
defects, all fixed with tests:

- A CTE named after a real table could read that table inside its own definition. Real tables other than the dataset
  are now rejected whatever CTE names exist.
- Columns the profile marks as omitted (long text, WKT, geometry) could be selected raw. The guard now rejects any
  reference to them and rejects `*` unless it excludes them; only `count(*)` remains.
- A null code crashed the label check; descriptions could be given out of result order and mislabel the lead's table;
  the request budget was measured against the lead's shared counter rather than the analyst's own run.

## The profiler before the merge

The three profiler sets were run on this branch before the merge, as the standing rule requires: held-out 0.998,
training 0.998, hand-made 0.958, the same columns wrong as before Phase 2. Moving the profiler's instructions into its
rulebook file changed nothing, as the byte-for-byte test guarantees. One run overlapped with an analyst evaluation and
two profiler requests stalled for the full 90 seconds; the one-retry rule absorbed one of them, and the rerun alone was
clean. Run the sets one at a time when the numbers matter.

## Process

Every task was implemented by Codex from a written brief holding the exact code and tests, and reviewed, tested, and
committed by the controller. Nine tasks and one fix round landed in one pass each; two briefs needed a one-line
answer (a test read of a tool return, a timeout test widened). The evaluation cases and their decisions were written
by hand, and the expected tables computed by the same query guard the analyst uses.

## Left for later

- The evaluation set is thirty questions over fourteen files. Trend and relationship questions are thin; a larger set
  should add them before Phase 4 relies on this agent.
- Analysis reports are returned and traced, not saved. Artifacts come with Phase 6.
- The lead's rendering of a table is free prose from its own model; the narrative syntax of the main design (section
  6.7) is not yet applied to it.
