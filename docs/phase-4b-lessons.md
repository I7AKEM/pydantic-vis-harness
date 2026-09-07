# Phase 4b lessons: evaluation at scale

What two hundred real questions, twenty seeded edge cases, and an offline optimizer taught us, recorded as the
Phase 4b design asked.

## The exit test

| Measure | Result |
|---|---|
| The set runs end to end with every automatic score recorded | Yes: 220 cases, 162 answered by the analyst and scored, 58 listed as unanswered |
| Held-out cases judged correct first time, unseeded | 24 of 26 |
| Held-out cases judged correct first time, seeded included | 26 of 28 |
| Hijri and Arabic baseline table | below |
| Optimized rulebook adopted | No: with the real runner it drew the same chart on all 66 dev and held-out designs, same scores; the seed stays |

## The set

Two hundred datasets from the Insightor dev corpus, chosen for coverage over the orchestrator's task, the result
shape, row-count buckets, Arabic categories, temporal columns, nulls, negatives, and long text, with the first
persisted question of each dataset as the question: 180 Arabic and 20 English, the English ones being Phase 4's
captured cases. Twenty seeded cases derive from three corpus files that hold full dates and from files with
Arabic categories: eight Hijri dates in three written forms, four measures in Arabic-Indic digits, six Arabic
category variants (diacritics, tatweel, mixed direction, digits in labels, labels past forty characters), and
two Hijri year columns beside a Gregorian date. Splits by source dataset: 132 train, 44 dev, 44 held-out.

The corpus is query results, not source tables: each CSV is the table one Insightor chart was drawn from, while
the producing question was asked of the database behind it. The analyst therefore asked a clarification on 58
of the 220 cases, almost always rightly ("citizens only in 2025", "the top five cities", "what about Jeddah?"
against a table that has no such column). Those cases are listed by the runner and left out of the designer's
scores; they are a finding about the corpus, not about the analyst.

## The baseline

The default designer model, Gemma 4 31B through OpenRouter, one run over the 162 answered cases, before any
fix of this phase:

| Score | Value |
|---|---|
| Delivered | 0.994 |
| Passed (check_spec, and the explanation's numbers exist) | 1.00 |
| ChartAccepted (agreement with the rules' reference list) | 0.963 |
| LanguageRight | 0.994 |
| BindingRight | 0.994 |
| IntentPlausible (against the orchestrator task) | 0.994 |
| Rendered | 0.969 |
| Requests per case | 3.16 |
| Seconds per case | 3.03 |

The one undelivered case ran out of output retries on a long conditional question (higher degrees against
lower, violations from 2023 to 2025, ages 30 to 50). Every delivered spec passed check_spec. Six designs fell
outside the reference list; the ones checked by eye were tables where the rules would have drawn a chart,
defensible choices, which is why ChartAccepted measures agreement with the rules and not correctness. Five
designs scored zero on Rendered: the undelivered one, and four line charts whose thin strokes cover 1.8 to
1.9 percent of the picture, under the runner's two percent blank threshold; the pictures were fine, and the
threshold for line charts is now one percent. Two seeded Arabic-digit cases failed outside the scores: their
measure column came back as text because the analyst read the digits as labels, and resolving rejects a text
measure.

### Held-out judgment

The held-out split holds 44 cases; the analyst answered 28 (the other 16 asked a clarification against the
exported tables, as above). The controller judged all 28 designs from the rendered picture and the spec with
the Phase 4 rubric, before any fix of this phase: 26 pass, 2 fail. Without the seeded cases, 24 of 26; the two
seeded held-out cases (Arabic labels past forty characters) both pass. The verdicts are in
`evals/designer/agent/scale/judgments.json`; `--split heldout --judgments` prints them.

The two failures:

- A growth-rate line ran from 2026 back to 2007. The analyst returned the years descending and typed them
  ordinal; the designer bound them as time with sort none, as the rulebook says; resolving kept the analyst's
  order. Fixed in this phase: resolving now draws Gregorian time text in chronological order whatever order
  the rows came in, and leaves Hijri and other non-Gregorian text alone.
- A one-number table read "20 null": the analyst wrote the word null as the unit and the table printed it.
  Fixed in this phase: a placeholder unit (null, none, n/a, a dash) becomes a real null in the analyst's
  result model, which also cleans saved reports when they load.

Passed with a note: three single-number shares shown without a percent sign because the analyst gave no
unit; one colour per column on single-series charts, the renderer's default; a legend showing the F and M codes
the data holds; seventeen long labels taking half the width of a bar chart, whole and readable.

### The Hijri and Arabic baseline

Measured before any fix, from the captured reports and the baseline designs. The stage named is the first
one whose output was wrong; the root cause of every Hijri row is one stage earlier, the profiler, which read
each Hijri text column as plain text with no time evidence, so the analyst had nothing to bucket on.

| Case | Seed kind | First stage that broke, or the design | Detail |
|---|---|---|---|
| seeded-01-hijri-date | hijri_date | designer: line | bind {'value': 'متوسط المخالفات المدفوعة', 'time': 'الشهر'}, sort none |
| seeded-02-hijri-date | hijri_date | analyst: Hijri column typed category | ١٤٤٥, ١٤٤٦ |
| seeded-03-hijri-date | hijri_date | analyst: no table | هل يمكنك تزويدي بتنسيق التاريخ الهجري المستخدم في عمود «violation_date» أو طريقة تحويله إل |
| seeded-04-hijri-date | hijri_date | designer: column with no time role | bind {'category': 'السنة', 'value': 'متوسط الوفيات'} |
| seeded-05-hijri-date | hijri_date | analyst: dropped the Hijri column | الشهر, متوسط المخالفات المدفوعة |
| seeded-06-hijri-date | hijri_date | analyst: Hijri column typed ordinal | 1383, 1384, 1385 |
| seeded-07-hijri-date | hijri_date | analyst: Hijri column typed category | 1383-08, 1383-09, 1383-10 |
| seeded-08-hijri-date | hijri_date | analyst: Hijri column typed category | ١٣٨٣, ١٣٨٤, ١٣٨٥ |
| seeded-09-arabic-digits | arabic_digits | render: no picture | column, bind {'category': 'region', 'value': 'population_count'} |
| seeded-10-arabic-digits | arabic_digits | analyst: digits not read as a measure | education_group, total_violations |
| seeded-11-arabic-digits | arabic_digits | render: no picture | column, bind {'category': 'age_group', 'value': 'count'} |
| seeded-12-arabic-digits | arabic_digits | analyst: digits not read as a measure | university_name, avg_days_to_graduate |
| seeded-13-arabic-categories | arabic_categories | designer: bar | bind {'category': 'region', 'value': 'population_count'}, sort value desc |
| seeded-14-arabic-categories | arabic_categories | designer: bar | bind {'category': 'education_group', 'value': 'total_violations'}, sort value desc |
| seeded-15-arabic-categories | arabic_categories | designer: bar | bind {'category': 'age_group', 'value': 'count'}, sort none |
| seeded-16-arabic-categories | arabic_categories | designer: bar | bind {'category': 'university_name', 'value': 'avg_days_to_graduate'}, sort value desc |
| seeded-17-arabic-categories | arabic_categories | designer: bar | bind {'category': 'city', 'value': 'إجمالي عدد السكان'}, sort value desc |
| seeded-18-arabic-categories | arabic_categories | designer: bar | bind {'category': 'violation_type_description', 'value': 'actual_fine'}, sort value desc |
| seeded-19-hijri-year | hijri_year | designer: line | bind {'value': 'متوسط المخالفات المدفوعة', 'time': 'hijri_year'}, sort none |
| seeded-20-hijri-year | hijri_year | designer: column with no time role | bind {'category': 'hijri_year', 'value': 'avg_death_count'} |

By kind: Hijri dates, six of eight broke at the analyst (one clarification about the date format, one
dropped column, four columns typed category or ordinal) and the two that reached the designer were drawn, one
as a line over time and one as columns with no time role. Arabic-Indic digits, two of four were not read as a
measure, and the two that reached the designer crashed in resolving because the measure column was text.
Arabic categories, all six reached the designer and were drawn. Hijri year beside a Gregorian date, both
reached the designer through the added column, one as a line over time and one as columns.

## DSPy on the rulebook

The optimizer is `evals/designer/agent/optimize_instructions.py`: a single-shot DSPy program whose
instructions are the rulebook plus the generated grammar and catalogue, scored by check_spec, the
explanation's numbers, the reference list, the language, and the binding, with every violation turned into
feedback for GEPA's reflection. Light budget, Gemma as the task model at temperature zero, Sonnet 4.6
reflecting, 132 train cases, the 37 answered dev cases as validation: 23 iterations, 528 rollouts, 25 minutes.

| Measure | Seed | Optimized |
|---|---|---|
| Proxy score on dev (single shot, no tools) | 0.858 | 0.932 |
| Real runner, dev: ChartAccepted | 0.946 | 0.946 |
| Real runner, dev: every other automatic score | 1.00 | 1.00 |
| Real runner, held-out: every automatic score | 1.00 | 1.00 |
| Chart types that differ between the two runs, dev and held-out | 0 of 66 | |
| Requests per case, dev and held-out | 3.00 and 3.14 | 3.05 and 3.03 |

Rendered aside, which differed by one thin line under the old threshold. What GEPA wrote (8.8 thousand
characters against the seed's 5.1) restates what the tools already enforce: stacked charts need additive
values, one row means a table, grouped columns need three different roles, sort none on ordinal axes, no
colons in the grammar, the explanation's numbers must appear in the result. In the single-shot proxy those
lines prevent violations the program has no tool to catch, hence the seven-point gain; in the runtime agent,
recommend_charts, check_spec and the retry already catch them, and the two rulebooks produced the same chart
for every one of the 66 dev and held-out designs. Not adopted: the exit test asks for a gain on both splits
with the real runner, and there is none. The seed rulebook stays and the optimized text is not committed.
The optimizer's value here is its feedback log, a list of the mistakes the model makes without tools, which
is where rulebook lines should go the next time the tools change.

## The Hijri fix round

One round, scoped by the table above, in pipeline order.

- Profiler: two measurement levels, each a DuckDB query. `hijri` for text that matches the three written
  forms once Arabic-Indic digits are translated (`1447-03-12`, `1447/03/12`, `12 ربيع الأول 1447`, or the
  year or year-month alone), kept on a column DuckDB had already parsed as a DATE from the ISO form, and given
  to an integer column of years between 1300 and 1500 that sits beside a Gregorian date or carries hijri in
  its name. `arabic_digits` for text that becomes a number once its digits are translated, with the numeric
  statistics computed on the translated value; plain ASCII numeric text keeps its old labels. The review
  accepts `hijri` as time evidence, and two rulebook lines give the roles.
- Analyst: the column facts carry the measurement levels, and two rulebook lines say how to bucket Hijri
  text (substr on the numeric forms, a CASE over the month names, never a cast) and how to translate
  Arabic-Indic digits before aggregating. The total check now sums a text column after the same translation;
  the merged test suite caught that it cast the raw text.
- Resolving: ISO shortening matches ASCII digits only and leaves the column alone when any year is below
  1600, so Hijri labels stay whole and in the analyst's order, with one rulebook line on binding Hijri
  buckets to time.

The seeded cases after the round, recaptured with the same models under the per-run rules and designed
again:

| Case | Seed kind | First stage that broke, or the design | Detail |
|---|---|---|---|
| seeded-01-hijri-date | hijri_date | designer: line | bind {'value': 'متوسط المخالفات المسددة', 'time': 'الشهر الهجري'}, sort none |
| seeded-02-hijri-date | hijri_date | designer: column with no time role | bind {'category': 'السنة الهجرية', 'value': 'متوسط الوفيات'} |
| seeded-03-hijri-date | hijri_date | analyst: month and year in two columns, not one bucket | month_num, year, متوسط المخالفات المسددة |
| seeded-04-hijri-date | hijri_date | designer: column with no time role | bind {'category': 'السنة الهجرية', 'value': 'متوسط عدد الوفيات'} |
| seeded-05-hijri-date | hijri_date | designer: line | bind {'value': 'متوسط المخالفات المسددة', 'time': 'الشهر الهجري'}, sort none |
| seeded-06-hijri-date | hijri_date | designer: line | bind {'value': 'متوسط المخالفات المدفوعة', 'time': 'السنة الهجرية'}, sort none |
| seeded-07-hijri-date | hijri_date | designer: line | bind {'value': 'متوسط المخالفات المدفوعة', 'time': 'الشهر الهجري'}, sort none |
| seeded-08-hijri-date | hijri_date | designer: line | bind {'value': 'متوسط المخالفات المسددة', 'time': 'السنة الهجرية'}, sort none |
| seeded-09-arabic-digits | arabic_digits | designer: column | bind {'category': 'region', 'value': 'population_count'}, sort value desc |
| seeded-10-arabic-digits | arabic_digits | designer: bar | bind {'category': 'education_group', 'value': 'إجمالي المخالفات'}, sort value desc |
| seeded-11-arabic-digits | arabic_digits | designer: column | bind {'category': 'age_group', 'value': 'العدد'}, sort none |
| seeded-12-arabic-digits | arabic_digits | designer: bar | bind {'category': 'university_name', 'value': 'avg_days_to_graduate'}, sort value desc |
| seeded-13-arabic-categories | arabic_categories | designer: bar | bind {'category': 'region', 'value': 'population_count'}, sort value desc |
| seeded-14-arabic-categories | arabic_categories | designer: bar | bind {'category': 'education_group', 'value': 'total_violations'}, sort value desc |
| seeded-15-arabic-categories | arabic_categories | designer: bar | bind {'category': 'age_group', 'value': 'count'}, sort none |
| seeded-16-arabic-categories | arabic_categories | designer: bar | bind {'category': 'university_name', 'value': 'avg_days_to_graduate'}, sort value desc |
| seeded-17-arabic-categories | arabic_categories | designer: bar | bind {'category': 'city', 'value': 'إجمالي العدد'}, sort value desc |
| seeded-18-arabic-categories | arabic_categories | designer: bar | bind {'category': 'violation_type_description', 'value': 'total_fine'}, sort value desc |
| seeded-19-hijri-year | hijri_year | designer: line | bind {'value': 'avg_paid_violations', 'time': 'hijri_year'}, sort none |
| seeded-20-hijri-year | hijri_year | designer: column with no time role | bind {'category': 'hijri_year', 'value': 'avg_death_count'} |

Every seeded case delivers, passes, matches the reference list, and renders: all automatic scores 1.00,
3.10 requests and 2.86 seconds per case. Hijri dates: seven of eight reach the designer, five drawn as lines
over year-month or year buckets in order and two as columns of years without a time role, a defensible
choice for two or three periods. The month-name form is the one that still breaks, and it broke differently
on each of three captures: month and year split into two ordinal columns; one bucket with every month
written 01 because the model tested `regexp_extract` against null, which DuckDB never returns (the recipe
now says to test the names with LIKE); and, last, every month mapped correctly but month and year in two
columns again instead of one year-month bucket. A recipe in prose is not deterministic enough for that form;
a SQL helper is the fix (see Left for later). Arabic-Indic digits: all four are measures now and all four
render. Hijri years beside a Gregorian date were never dropped and are unchanged.

A whole-branch Codex review then found three gaps in the round, all fixed: an integer column beside a
Gregorian date was taken for Hijri years whatever its name (now only a column called a year, or hijri,
qualifies); the analyst's rule prescribed text functions that fail on a DATE or integer column (it now casts
to text first); and the Hijri bounds were lexical (now reported only for one zero-padded numeric form, where
text order is date order).

The pre-merge analyst eval then caught a cost the scale set could not see: 64 to 65 of 69 on the branch
against 68 on main the same day, with the misses moving between runs and three of them the model looping
past its request budget. Removing the profiler's two new lines changed nothing (65); removing the analyst's
Hijri and digit lines restored 67, the pre-phase level; after the change below the eval scored 69 of 69,
with no request loops. Long SQL recipes in the always-on instructions cost
ordinary questions, so those rules now reach the model per run only when a column carries one of the two
levels, through a Pydantic AI instructions function, and the seeded cases were captured again under that
arrangement.

## What changed

- Evaluation: `corpus_tools` (select, seed, capture); the scale set under `evals/designer/agent/scale/`
  (200 corpus cases, 20 seeded, splits, reports, decisions, judgments); the runner's `--split`, reference
  list, IntentPlausible and unanswered listing; the DSPy optimizer; the `optimize` dependency group gains
  dspy and hijridate; the Rendered score's blank threshold is one percent for line, area and scatter charts.
- Profiler: `hijri` and `arabic_digits` measurement levels, the review accepting hijri as time evidence, two
  rulebook lines.
- Analyst: the `hijri` and `arabic_digits` levels in the column facts, the Hijri and digit rules in
  `rulebook-localized.md` added per run only when a column carries one of those levels, the total check
  translating digits before it sums text, placeholder units becoming null, described column names accepted
  with the SQL alias quotes around them, and a spent query budget with no passing query ending in a
  clarification instead of a loop to the request limit.
- Designer: resolving keeps non-Gregorian time text whole and in the analyst's order, draws Gregorian time in
  chronological order, and one rulebook line binds Hijri buckets to time.
- Docs: README (scale set, levels, analyst rules), AGENTS (Phase 4b, Hijri conventions), the Phase 3
  design's resolving sentence, this document.

## Testing through the web UI

The eval runners call the analyst and the designer directly, so a last check went through the lead in the
web chat: upload the ISO-form seeded Hijri file, ask for the monthly averages. The analyst asked which of
four narrower views to draw, since the file holds over 700 Hijri months; the yearly view was chosen, and
`make_chart` came back with the table and no picture. The cause was a loop the runners never see because
their questions are short: the analyst described its result columns with the SQL alias quotes still around
the Arabic names, the description check refused them, its repair dropped the quotes from the SQL and could
not parse, the three-query budget ran out, and it then alternated a refused delivery with a refused query
until the request limit. Two code guards close that class: a described name that differs from the result
column only by surrounding quotes is accepted, and a spent budget with nothing passed returns a clarification
that names the failed checks. The same question then delivers on the first query and the designer draws a
line over the Hijri years. The owner's own session then hit the designer's version of the same dead end: a
donut with one colour for every slice fails the palette rule on every check, and once the three check calls
were spent the model kept calling refused tools until the request limit. The designer now answers a spent
check budget with nothing passed by a clarification that names the last violations, and the refusal message
says so. Lesson: run one real question through the lead before a merge; the runners test the agents, not
the conversation.

### Ten corpus questions through the lead

The owner saw the analyst asking back and forth in the web chat, so ten corpus files with their own
questions (seed 11) went through the lead the way the UI runs them, and through the analyst alone. Through
the lead: seven answered, two of them with charts; one clarification (a geometry-only file asked for "the
path": list all hundred or one?); one honest "this file cannot answer that" (a one-cell count of customs
records asked for yearly export growth); and one lead misfire, "no file uploaded" without calling
find_dataset. The analyst alone answered nine and asked once, on the customs file. So the asking is not the
analyst's habit; it is the corpus: each file is the result of a warehouse query with joins and filters, and
a question that names a filter the result no longer holds (a city, a year, an age, "the largest five") can
only be asked back. On the 220-case scale set that was 57 questions, and reading them all gives one pattern:
"the table has only X; can you provide Y?". Two lead defects came out of the same ten and are fixed in the
lead's instructions: it once rewrote the returned relative image path into an invented host, and it once
declared nothing uploaded without looking. Two observations stay: the upload button sends the composer's
text together with the attachment link, so typing the question first and then attaching is the intended
flow; and on one-row files the lead sometimes answers from the profile's statistics without calling the
analyst, which is right for a single number but skips the analyst's checks.

A second machine then showed a needless question on a file that holds a percentage column beside the count
and the total: "do you mean the percentage column, or the count over the total?", two readings with the same
numbers. Here the same file answered ten times out of ten, so the difference between machines was not
reproduced, but the rulebook now says so explicitly: do not ask when the readings give the same numbers;
use the column the question names and record the choice under assumptions. The analyst eval stays at 69 of
69 with that line, the eight cases that must still ask included.

## Left for later

- A single-series line, area, column, or bar whose axis values repeat, with no group role, should fail
  check_spec with "add a group or bucket the axis". The month-name Hijri case showed the gap: the analyst
  returned month and year as two columns and the designer drew one line over repeated months.
- Hijri bucketing rests on the analyst following a recipe in prose. A code helper the analyst can call from
  SQL (a macro that turns any of the three written forms into a year-month bucket) would make it
  deterministic; one of three month-name cases missed the recipe.
- Units the analyst invents for counts (person, شخص) reach the axis and the labels, and a unit can come
  back in the wrong language; the resolver drops only a short list of count words. A share with no unit
  prints without a percent sign; the designer could add it from the column's kind.
- Single-series bars and columns take one colour per category, the renderer's default; a single-colour
  style would read better.
- Fifty-eight of the corpus questions cannot be answered from the exported CSVs because the CSVs are the
  result tables, not the source tables. An export that keeps the source table beside each question would
  let the analyst answer them and make the set a test of the analyst as well.
- The optimizer's proxy is a single shot with no tools, so it rewards instruction text that repeats what the
  tools would have enforced; whether that transfers to the runtime agent is the measurement above.
