# Phase 3 lessons: the design foundation

What building the chart language, the catalogue, the rules, and the renderer taught us, recorded as the design
asked (section 16 of the Phase 3 design). No model was involved anywhere in this phase.

## The exit test

| Requirement | Result |
|---|---|
| `recommend_charts` returns the expected top candidate at least nine times in ten on a fixed set | 35 of 35 on the thirty-five-case set, after two rule changes the set itself demanded (32 of 35 before them) |
| Every edge case in section 8 of the main design that is a rule or a fix has a test | H1 to H12, S1 to S14, and C4 to C17 each have a violating and a satisfying test, mapped in section 7.4 of the design |
| The renderer draws every catalogue entry from a hand-written spec | All twenty entries render to a PNG of the expected size with a non-background share above the floor; the images were inspected by eye |

The suite grew from 108 to 408 tests, 24 seconds with the renders. A person can now go from a saved analysis
report to a picture with three terminal commands.

## What the evaluation set changed

The recommendation set was the last task, and its three misses were rule defects, not case defects:

- A valid suggested chart tied with the unsuggested default and lost on catalogue order. A suggestion is a
  preference, so it should win a tie: S2 went from +2 to +3.
- A seven-part share went to a treemap because the few-parts penalty stopped at six while the pie limit is also
  six. The gap between "too many for a pie" and "enough for a treemap" belongs to the sorted bar: S14 now covers
  seven or fewer parts.
- Earlier, the table had been receiving the intent bonus because its purposes list every intent for eligibility.
  It is the zero-score fallback, and S1 now skips it.

Every change is a line in the design, a rule, and a case. The set is the regression guard from here on.

## What the pictures caught that the tests did not

Codex cannot look at a PNG, so every task's images were inspected by the controller. Three defects appeared only
there:

- The histogram's count axis carried the measure's unit ("20 SAR"). A count has no unit.
- The dual-axes chart applied the first measure's unit to both axes and named its series by unit, so the legend
  read "visits" and "SAR". Each axis now has its own format and the series carry the column names.
- Charts without axis titles printed the raw field names "category" and "value". Axis titles now default to the
  bound column names, which the analyst already writes for people.

The browser caught two more on the page: the render promise never resolves in a background tab unless animation
is off, and a page without a background colour turns black inside a dark host.

## What the renderer is and is not

- The package draws the base vocabulary; everything of ours reaches G2 through one hook on the chart-creation
  call: axis ranges, the log scale, the right-to-left title and category order, label and legend switches, the
  subtitle, and the number formatting function. The version is pinned and the render tests guard the hook.
- Numbers are formatted once, from a description built in Python and executed by one shared JavaScript function
  in the script and in the page. The unit comes from the analyst's column by default; `format` overrides it;
  Arabic-Indic digits are a switch.
- The page draws the captured G2 configuration in a browser for the entries whose configuration holds no package
  functions. Scatter, histogram, radar, and dual axes still carry functions from the package, so their pages show
  the picture. That is recorded as a compromise on the render.
- A render costs 0.1 to 0.4 seconds in a fresh Node process, as the spike measured. A 800 by 450 request gives
  a 2400 by 1350 PNG.
- Right-to-left on bars and columns is real: the title is right-aligned and the first category is on the right.
  The legend stays where the package puts it, and that is the one degraded key.

## Rulings made during implementation

Recorded in the ledger as they happened, and now in the design:

- Hard rule H1 checks role kinds as well as presence, so a bar never binds a time axis; the catalogue is the
  authority on kinds.
- S9's penalty for unbound columns is uncapped: five unbound measures cost five points.
- C10 in `check_spec` reports every failing hard rule at once, through the rules module, not a second pass.
- Emphasis may name a group value on charts with a group role, not only a category value.
- Syntax errors stop the check; a spec that does not parse gets only its syntax violations.
- Values are typed by key: `1446` and `001` stay text when they are categories.

## Process

Eight tasks and three fix rounds, all implemented by Codex from written briefs, reviewed, tested, and committed
by the controller; the evaluation set was written by hand by the implementer from the analyst's real tables.
Two lessons about the briefs:

- Tests written into a plan must be checked against the plan's own prose. Tasks 1 and 2 stopped on
  contradictions between a test and a sentence a few lines above it, which cost a round trip each.
- From Task 3 on, the dispatch told the implementer to resolve small contradictions itself, follow the design,
  and list every decision in its report. No task stopped after that, and the reports' decision lists became the
  review material.

The Codex sandbox cannot reach npm, bind a port, or run `ps`, and it needed a private uv cache. The controller
installed the pinned package before Task 6 and ran the HTTP benchmark and the browser check itself.

## What the branch review found

The whole-branch review by a second model, after the eight tasks and three fix rounds, returned eight findings,
all real and all fixed in one round with a test each:

- A `sort value` on a scatter or a `sort category` on a histogram passed the check and crashed in resolving.
  The check now rejects a sort whose target role is not bound (C18).
- `limit 0` passed the check and failed at render time. The check now requires a limit of at least one (C19),
  and the terminal command reports a resolve error as a spec error instead of a traceback.
- A sixty-category result with `limit 20` was rejected by the too-many-categories rule, which counted the raw
  categories and so blocked the very remedy it recommends. The check now counts displayed marks after the limit
  and keeps every value statistic raw.
- `labels on` and `legend on` did nothing: only the off switches produced an override. Both now force the
  element on where the package's configuration can reach it and record a compromise where it cannot.
- The histogram's axis titles were swapped: the bound column on Y and nothing on X. X is now the column and Y is
  the count word in the spec's language.
- The palette rule counted categories on a grouped chart the package colours by group. It now counts the role
  that receives the colours.
- Compromises found at check time were dropped by the render, so a cropped axis reached the caller without its
  warning. The render now merges the check's compromises with its own.
- Radar axes are named `position`, not `y`, so number formats never reached their ticks. The formatter now
  applies to every position axis.

Five of the eight are the same lesson: a spec that passes the check must render. The reviewer found them by
writing specs that combined keys the tests had only tried alone. The evaluation set could not have caught them,
because it has no spec; the check tests are where such combinations belong.

## Before the merge

The profiler and analyst sets ran twice each on the branch, as the standing rule requires, although neither
agent changed. The profiler scored 10 of 12 on the first run, with two files that stalled for the full 90
seconds twice, and 12 of 12 on the rerun with one stall absorbed by the retry. The analyst scored 67 of 69 on
both runs, with every delivered result free of error-level checks, but a different pair of questions failed each
time: two hit the eight-request cap on the first run, and two came back as clarifications on the second. All four
passed on the other run. That is the day's variance of the routed open-weights model, not a regression, and it is
the reason the exit tests are thresholds rather than perfect scores.

## Left for later

- The test suite has not been run on Linux. The spike proved the fonts and the one missing library on Debian;
  the deployment image still needs that check with `vis doctor`.
- `vis` is `uv run python -m vis_agent.cli` until a console script is added to the project.
- The startup smoke render lives in `vis doctor`; the application will call it when Phase 4 wires rendering into
  a tool.
- Date formats, annotations, and hidden axes remain outside the vocabulary.
- Reference images are inspected by eye and kept out of git. If a platform-stable comparison is wanted, it has to
  be generated on Linux in a container.
