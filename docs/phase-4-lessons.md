# Phase 4 lessons: the chart designer agent

What the third agent taught us, recorded as the design asked (section 17 of the Phase 4 design).

## The exit test

On at least twenty real questions, the first chart must be judged correct by a human at least seven times in
ten without revision, and every delivered spec must have passed `check_spec`.

| Measure | Result |
|---|---|
| Delivered specs that passed `check_spec` | 100 percent, on every model, by construction: delivery re-checks the spec |
| First chart judged correct, first pass, default model | 19 of 31 (61 percent) before the fix round |
| First chart judged correct after the two fix rounds, default model | 31 of 31 |

The judge for the first pass was the controller, with the six-criterion rubric in `evals/designer/agent/run.py`;
the owner's verdicts replace the controller's where they differ. Every verdict is in `evals/designer/agent/judgments.json`
with the spec it judged.

## What the pictures said

Twelve of the thirty-one first charts failed. Nine failures were Phase 3 code, not the model's judgment:

- The histogram drew its bins in order of first appearance (100, 1200, 300, 1000). Sorting the values did
  not help: the package orders discrete bins its own way. Resolving now computes the bins itself and draws
  them as columns in ascending order; that chart passed on the third look.
- Two charts whose categories were years got a continuous scale from the package: one column chart was coloured
  yellow to navy with one bar almost invisible, and one line chart had ticks at 2023.5. Category and time values
  now reach the package as text.
- Three time axes printed full timestamps, `2020-01-01T00:00:00+03:00` per year. Time buckets are now shortened
  to the finest unit that varies: the year, the month, or the day.
- Two tables printed thirteen-digit fractions under raw column names. Tables now carry the column meanings as
  headers and format numbers with the same formatter as the charts.
- A two-colour brand palette alternated across five bars of one series, which reads as two groups. Single-series
  charts now repeat the first colour.

Three failures were habits of the model that code can remove:

- On two horizontal bars the model titled the vertical axis with the value and the horizontal axis with the
  category, because the package's `axisXTitle` names the category axis even when a bar draws it vertically, and
  a rulebook line saying so did not help. Axis titles now follow the screen in the spec, and resolving maps them
  to the package.
- With thirteen bars the model switched data labels on and nine labels landed on the category names. The check
  now rejects labels on more than twelve marks on bars and columns.

The passes carried notes worth a rule: `count` printed as a unit on every count axis and label
("53,218 count"); an English unit word inside Arabic charts ("701 person" under a title in Arabic); an
explanation that did not say why a suggested chart was overridden; the last label of a line clipped at the
right edge. The first two are fixed in resolving and in the analyst's rulebook; the third is a rulebook line;
the fourth waits.

## The model benchmark

Thirty-one cases, each run twice, automatic scores only (the human judgment is on the default model's charts).
Delivered: a design when one was expected. Chart: the delivered chart type is one a person accepts. Language:
the spec's language and the title's script match the caller. Binding: the roles the case names are bound to the
expected columns. Passed: the delivered spec passes `check_spec`.

| Model | Delivered | Chart | Language | Binding | Passed | Requests | Check calls | Seconds |
|---|---|---|---|---|---|---|---|---|
| Gemma 4 31B (default) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 3.1 | 1.1 | 2.3 |
| Claude Haiku 4.5 | 0.97 | 0.97 | 0.97 | 0.97 | 1.00 | 2.9 | 0.9 | 6.3 |
| Qwen 3.8 27B | 0.97 | 0.97 | 0.97 | 0.97 | 1.00 | 3.0 | 1.0 | 8.0 |
| GPT-5.4 mini | 0.92 | 0.92 | 0.92 | 0.92 | 1.00 | 4.5 | 2.1 | 8.2 |
| Claude Sonnet 4.6 | 0.98 | 0.98 | 0.98 | 0.98 | 1.00 | 3.2 | 1.1 | 11.4 |

The misses are whole designs that never arrived, not wrong charts: GPT-5.4 mini failed the delivery checks
twice on four of its sixty-two designs, Haiku asked a clarification on the two-measure order case both times,
Qwen hit the request cap once on the fifty-five-district case, and Sonnet failed the delivery checks twice on
one age-group case. Gemma delivered every design, repaired once in
about one design in eight, and was three times faster than the next model and five times faster than Sonnet. It stays the default, as it did for
the profiler and the analyst.

## The repair turn

Gemma needed a second `check_spec` call on eight of sixty-two designs, and always on the same four cases in
both runs: the two ordinal age-group charts and the Arabic city ranking came back once, which is consistent
with a sort written on an ordinal axis (C4) and fixed to `sort none` in the delivered spec; the two-measure
order case came back twice before the model settled on a table. The other twenty-seven cases passed the
check first time. The delivery send-back was never needed on the default model.

## Time and cost per design

Gemma: 2.3 seconds and 3.1 requests per design on average; a design is one recommendation call, one check, and
one delivery. The renderer adds 0.1 to 0.4 seconds.

## Before the merge

The analyst's rulebook gained one line on this branch (no unit for counts), so its sixty-nine-question set ran
again: 67 of 69 tables right, every delivered result free of error-level checks, 8.6 seconds per question. The
two misses were clarifications on questions that passed in other runs, the same day-to-day variance recorded
before the Phase 3 merge. The profiler did not change.

## What changed in the rulebook

- A limit lifts the too-many-categories rejection, so a bar with `limit 20` is a valid answer to fifty-five
  districts.
- A code column beside its label column is not a group; bind the label.
- Axis titles follow the screen.
- Only real units go in brackets; a count has none.
- Data labels on twelve marks or fewer.

## What changed in Phase 3 because of Phase 4

Ranking the thirty real reports before any model ran found two rule gaps: a code column beside its label was
bound as a group (H13), and per-region shares were treated as parts of one whole (H14). The judged pictures then
found the resolving defects above. All are rules or resolving steps with tests and design rows, and the Phase 3
evaluation set grew from thirty-five to thirty-seven cases.

## Left for later

- The histogram's bins take the package's per-category colours; one colour would read better.
- The line chart's last data label could clip at the right edge before units were dropped; watch it.
- The model judge (`--judge`, Claude Haiku 4.5 reading the spec, the explanation, and the result description,
  not the picture) agreed with the controller on 12 of the 13 charts whose rerun produced the identical spec.
  That is a first reading for Phase 5, on a small sample; the reviewer there must see the picture, since nine
  of the twelve first-pass defects were visible only in it.
