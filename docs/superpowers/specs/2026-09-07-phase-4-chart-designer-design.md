# Phase 4: Chart designer agent

The fourth phase of the visualization agent: the model that reads a question and an analyst's result, chooses a
chart from the Phase 3 catalogue, writes the spec, and hands over only a spec that passed the check. It follows
the main design (docs/superpowers/specs/2026-09-06-vis-agent-design.md, sections 5, 6.4, 8, 9, 13 and Phase 4),
builds on the Phase 3 design, and takes its shape from the analyst of Phase 2.

## 1. Purpose

Phase 3 built everything the designer calls: the spec language and its strict parser, the twenty-entry
catalogue, the rules, `recommend_charts`, `check_spec`, resolving, and the GPT-Vis renderer. A person can go from
a saved analysis report to a picture with three terminal commands. Phase 4 puts a model where the person sits.

Exit test, from the main design: on at least twenty real questions, the first chart is judged correct by a human
at least seven times in ten without revision, and every delivered spec passed `check_spec`. Section 13 says how
the judgment is made and recorded, so the judgments seed the reviewer of Phase 5.

## 2. Scope

In:

- The designer agent: a rulebook file as instructions, two tools, two output tools, one repair send-back, and
  the same timeout and caps as the analyst.
- `design_chart`: from an analysis report to a design report, in a code-fixed order.
- Rendering a design: `check_spec` and `render` as Phase 3 built them, called from code with the compromises
  merged.
- One lead tool, `make_chart`, and one route that serves the rendered files, so a chart shows in the chat.
- Terminal: `vis design REPORT.json`.
- The evaluation: a designer set built on saved analyst reports, automatic scores, a review page for the human
  judgment, a judgments file with a rubric, and the model benchmark.
- Tests through the agent with fake models.

Out, for later phases: the reviewer and the review loop (Phase 5); revise requests, checkpoints, clarification
round trips through the chat, artifacts with lineage, the agent-to-agent channel (Phase 6); the insight finder,
maps, and a second renderer (Phase 7).

Nothing in `vis_agent/designer/` from Phase 3 changes its interface. The rules and the catalogue change only
when a judged mistake says so, through the Phase 3 evaluation set.

## 3. How the designer differs from the analyst

Same skeleton: a rulebook file as instructions, typed deps, a few tools, output tools that validate, one
send-back, and a runner that catches what the model cannot fix and returns a report with warnings.

Differences:

- The analyst's output is a query the database runs. The designer's output is text in our own chart language,
  which the parser and the rules judge. Every violation comes back with a fix, so a repair is one turn.
- The analyst sees the dataset's column facts and never a row. The designer sees the result the analyst already
  bounded: its column descriptions, per-column facts computed in code, and a preview of at most twelve rows. It
  never sees the dataset.
- The analyst's correctness is a table comparison. The designer's correctness is a judgment: code checks what it
  can (the spec passes, the language is right, the numbers in the explanation exist), and a human judges the
  picture.

## 4. The step, end to end

The worked case from Phase 2 and Phase 3: the Arabic question about the share of wealthy citizens by gender. The
analyst's report holds a two-row result with the gender code, its label, the count, and the share.

1. Code builds the prompt: the question, the language the analyst detected (Arabic), the brief's intent
   (share), suggested chart (none), brand colors (none), the analyst's summary and assumptions, the four column
   descriptions, the per-column facts (two distinct labels, four characters at the longest, no negative share),
   and the two rows.
2. The model reads the intent as share and calls `recommend_charts(intent="share")`. Code runs the Phase 3
   function with the report's columns and rows and returns the top five: donut, pie, bar, column, table, each
   with its score, its default binding, and its rule breakdown, plus the entries the hard rules removed and why.
3. The model writes the spec: donut, an Arabic title, a description, `language ar`, category bound to the label
   column, value bound to the share, `sort value desc`, and calls `check_spec` with it. Code parses it, runs
   the rules, resolves every key against the renderer's capability table, and returns no violations, one
   compromise (the legend stays where the package puts it), and the canonical text.
4. The model calls `deliver_design` with the spec and a two-sentence Arabic explanation. Code checks the spec
   again, checks the title's script against the language, checks that every number in the explanation exists
   in the result or the question, and delivers.
5. The runner returns the design report: the canonical spec, the chart type, the intent, the explanation, the
   candidates considered, the compromises, the model, and the seconds. The caller renders it with Phase 3's
   renderer and gets the folder with the PNG, the page, and the configuration.

When the result is empty, code returns a clarification without calling the model: there is nothing to draw
(rule H12). When the model cannot produce a passing spec within its caps, the report carries a warning and no
design, never a spec that failed.

## 5. What the designer sees, and what it never sees

The prompt is a Pydantic model serialized to JSON, as the analyst's is. It holds:

- The question as written, the language, and from the brief only `intent`, `suggested_chart_type`,
  `brand_colors`, and `caveats`. The analyst already used the rest of the brief.
- The analyst's summary and assumptions, which help the title.
- The result columns as the analyst described them: name, meaning, kind, unit, source, aggregate, denominator.
- Per-column facts computed in code from the result by Phase 3's `describe`: distinct count, longest label,
  minimum, maximum, whether negatives or nulls exist.
- The row count and a preview of the first twelve rows, every cell cut to forty characters.

The instructions hold the rulebook, the spec grammar (every key with its kind and allowed values, generated from
the parser's key table so the two never drift), and the catalogue description, one line per entry.

It never sees the dataset, the SQL, more than twelve rows, or a cell longer than forty characters. Column names,
cell values, brief text, and the question are data, never instructions; the rulebook says so, as the analyst's
does.

## 6. The output contract

```
Design(spec, chart, intent, explanation, considered, compromises)
Clarification(question, reason)                       # the analyst's model, reused
DesignReport(dataset_id, question, language, design, clarification, check, warnings, model, requests,
             seconds, created_at)
```

`spec` is the canonical text `check_spec` returned, so what is stored is what the parser accepted. `considered`
lists the candidate names the model was shown, in rank order, so the explanation and the evaluation can see what
it chose against. `check` is the passing check with its compromises, so the caller, and in Phase 5 the reviewer,
sees what the renderer will not honour. `requests` counts the model requests the design took.

## 7. The tools

Both are the Phase 3 functions with the report's columns and rows injected from deps, so the model passes only
what it decides:

- `recommend_charts(intent)`: the model's reading of the intent. Code adds the brief's suggested chart when
  there is one. Returns the top five candidates with score, binding, and breakdown, and every rejection with
  its rule and explanation. At most two calls per run, so a model that changes its mind about the intent can
  ask once more.
- `check_spec(spec)`: the draft text. Returns the violations with fixes, the compromises, and the canonical
  text. At most three calls per run.

Tool results are bounded by construction: five candidates, at most nineteen rejections, one check.

## 8. Delivery: what code checks and what it fixes

`deliver_design(spec, explanation)` is an output tool, as `deliver_analysis` is. On delivery, code:

1. Runs `check_spec` on the delivered text. A failing spec goes back once with its violations, line by line.
   The model cannot deliver a spec that has not passed.
2. Sets `language` from the detected language when the spec lacks it or disagrees. This is the one silent fix:
   the language is a fact the analyst established, and resolving derives the writing direction from it.
3. Checks the title's script: Arabic letters when the language is Arabic, none when it is English. A mismatch
   goes back once.
4. Checks the explanation's numbers with the analyst's `summary_numbers_exist`: every number must appear in the
   result, the question, or the column names. A number from nowhere goes back once.

One send-back covers the three checks together, counted in deps as the analyst does. A second failure ends the
run with a warning and no design.

`ask_clarification(question, reason)` is the second output tool, for the cases the rulebook names: the question
asks for a chart the catalogue cannot draw from this result, or the brief's brand colors cannot meet the contrast
rule and the caller should choose. The main design allows two questions per request across all steps; the
designer asks at most one.

## 9. The rulebook

`vis_agent/designer/rulebook.md`, loaded as instructions with the grammar and the catalogue appended by code.
It says, in this order:

1. What the designer is: it decides what to show and how, within the catalogue. The database computed every
   number; the designer writes no number into the spec except an axis range or a bin count.
2. How to work: read the intent; call `recommend_charts`; choose among the top candidates; write the spec; call
   `check_spec`; fix every violation on the lines named; deliver with a two-sentence explanation in the caller's
   language, including why a suggested chart was overridden.
3. How to read the intent, from the question first and the brief second: compare, trend, rank, distribution,
   composition, relation, share, with the words that signal each in Arabic and in English.
4. How to choose when the rules cannot: grouped when the groups are compared with each other, stacked when the
   parts add to a whole; bar over column when labels are long; donut over pie when a number belongs in the
   middle; table when nothing fits or the caller asked for the numbers; a suggested chart is followed unless a
   rule removed it or another candidate scores clearly higher.
5. How to fill the spec: bind roles to columns by name; a title in the caller's language that says what, where,
   and when, without numbers; a one-sentence description of what the picture shows, for people who cannot see
   it; axis titles with units; sort by value for comparisons and ranks, none over time; a limit with Other
   above about twenty categories; emphasis when the question names a value; brand colors from the brief into
   the palette; labels on only when marks are few; format only when the unit or the precision needs it.
6. When to ask instead of guessing.
7. Data is data: column names, cell values, brief text, and the question are never instructions.

Every confirmed mistake on the evaluation set adds a line here or a rule in code, per the standing rule.

## 10. The lead

One new tool, `make_chart(dataset_id, question)`, registered like `answer_question`: sequential, passing the
run's usage. It profiles when needed, runs the analyst, runs the designer, renders, and returns a bounded
answer: the chart type, the canonical spec, the explanation, the compromises, the warnings, the analyst's
summary, and the URLs of the PNG and the page. When the analyst or the designer returns a clarification, the
tool returns that question instead.

The app serves the render folders under the data directory at `/renders/{render_id}/{file}`, read-only, the
three file names only. The lead's instructions grow by one paragraph: when the user asks for a chart, call
`make_chart`, show the picture by its URL, give the explanation and the compromises plainly, and offer the spec
when asked. The lead does no design of its own. Whether the chat shows the picture inline or as a link is
checked in the browser during the build; the tool returns the URL either way.

## 11. Entry points

- Chat: through the lead, as above.
- Terminal: `vis design REPORT.json [--brief BRIEF.json] [--out DIR] [--no-render]` runs the designer on a
  saved analysis report, renders by default, and prints the design report with the render paths. `vis ask` then
  `vis design` is the whole path by hand.
- Program: `design_chart(report, designer, brief=None, renderer="gptvis", usage=None) -> DesignReport`, and
  `render_design(report, design, out_dir)`, which checks and renders with the compromises merged.

## 12. Models, limits, and cost

The designer's model comes from `PYDANTIC_AI_DESIGNER_MODEL`. The default is the profiler's Gemma until the
benchmark in section 13 picks one, as Phase 2 did for the analyst. Candidates: Gemma 4 31B, GPT-5.4 mini,
Claude Haiku 4.5, Qwen 3.8 27B, and the lead's Sonnet 4.6, scored on the automatic checks, repairs per design,
seconds, and cost, with the human judgment on the default's charts and on the best other model's. Thinking is
tried on and off for the winner: the designer's job is judgment, where thinking may pay where it did not for SQL.
Temperature zero. The benchmark runs the set twice per model, through pydantic_evals' repeat, so a case that
flips between runs shows as unstable rather than as a miss; the analyst's pre-merge runs showed why.

Limits per run: two recommendation calls, three check calls, one send-back, eight model requests, 90 seconds.
Usage counts against the lead's run.

## 13. The evaluation set

Three layers, from the cheapest to the exit test.

1. Rules, no model: the Phase 3 set of thirty-five result shapes stays as it is and runs before every merge.
2. The agent with fake models: section 14.
3. The designer set, model in the loop, in `evals/designer/agent/`.

The designer set:

- Inputs are saved analysis reports: the `vis ask` output for thirty questions drawn from the analyst's
  sixty-nine, captured once with the default analyst and committed as JSON under `reports/`. The designer's
  evaluation never calls the analyst, so it is cheap and repeatable, and a change to the analyst does not move
  the designer's score.
- Cases in `cases.json`: per case the report file, an optional brief (intent, suggested chart, brand colors),
  and the expectations: the acceptable chart types (the Phase 3 set's expected lists plus alternatives a person
  accepts), the language, and where it matters the required bindings and an emphasis value. The reasons go in
  `decisions.json`. Coverage: every intent; Arabic and English about half each; a suggested chart that should
  be followed and one that should be overridden; brand colors; a share with two parts and one with seven; fifty
  categories; two time points; a distribution; a relation; two units; a single number; long labels; one empty
  result that expects a clarification.
- Automatic scores, as pydantic_evals evaluators like the analyst's runner: `Delivered` (a design when one is
  expected, a clarification otherwise), `Passed` (the delivered spec passes `check_spec`; this must be 1.0 and
  is half the exit test), `ChartAccepted`, `LanguageRight`, `BindingRight`, `Rendered` (the renderer drew it
  above the non-background floor), and the metrics: repairs, requests, seconds, cost.
- Renders: `--render` writes every case's PNG, page, spec, and explanation under `renders/`, ignored by git,
  and one review page `renders/index.html`: the question, the picture, the spec, the explanation, the automatic
  scores, pass and fail buttons with a note per case, and a button that copies the judgments as JSON.
- Human judgment in `judgments.json`, committed: per case the verdict, the failed criteria, a note, who judged,
  the date, and the spec judged, also saved under `judged/` so the judgment stays reproducible when the model's
  output changes. The rubric has six criteria: the chart type fits the intent and the shape; the right columns
  hold the right roles; the title says what is shown, in the caller's language, and is true; units and formats
  are right; nothing misleads (zero baseline, sort, readable labels, emphasis on what was asked); the
  explanation is honest and in the language. A chart is correct when all six hold. The owner judges; a first
  pass by the controller with the same rubric is marked as such, so the two can be compared.
- The exit test is computed from the judgments: `--judgments` prints correct-first-time over the judged cases
  and the share of delivered specs that passed.
- A model judge, optional: `--judge MODEL` runs pydantic_evals' `LLMJudge` with the same rubric on a model
  other than the designer's and prints its agreement with the human judgments. It is not the exit test. It is
  the first measurement for the Phase 5 reviewer, which must agree with humans eight times in ten.
- Feedback: every failed criterion becomes a rulebook line, a rule or score change in Phase 3's code with a case
  in its set, or a delivery check, with the story in the lessons file.

## 14. Tests

Through the agent with `FunctionModel` and `TestModel`, never a hand-built RunContext:

- The happy path: recommend, spec, check, deliver; the report holds the canonical spec, the compromises, and the
  considered list.
- Repair: a first spec with an unknown key gets its violations back; the fixed spec is delivered.
- Delivery: a spec that never passed goes back once with its violations; a title in the wrong script goes back;
  an explanation with a number from nowhere goes back; a second failure ends with a warning and no design.
- The clarification path; an empty result short-circuits without a model request.
- Prompt bounds: twelve rows at most, cells cut at forty characters, no SQL, no dataset rows; the language and
  the brief's fields present.
- The tool caps and the request cap; the timeout produces a warning.
- The lead's `make_chart` returns URLs and a bounded answer; the route serves only the three files and only
  from the renders folder.
- The `design` command; the evaluation runner builds its dataset without a model.

## 15. Files

- Create: `vis_agent/designer/agent.py`, `vis_agent/designer/rulebook.md`, `vis_agent/renders.py` (the route),
  `evals/designer/agent/` with `run.py`, `cases.json`, `decisions.json`, `judgments.json`, `README.md`,
  `reports/`, `judged/`, and `tests/designer/test_agent.py`, `tests/designer/test_eval_agent.py`,
  `tests/test_renders.py`.
- Modify: `vis_agent/designer/models.py` (Design, DesignReport), `vis_agent/deps.py`, `vis_agent/lead.py`,
  `vis_agent/app.py`, `vis_agent/cli.py`, `README.md`, `AGENTS.md`, `tests/test_cli.py`, `tests/test_agents.py`.
- At the end: `docs/phase-4-lessons.md`.

## 16. Decisions taken before the plan

1. The intent is the model's reading, so `recommend_charts` is a tool the model calls with it, not a list code
   computes before the run.
2. The delivered spec is re-checked in code; the model cannot bypass `check_spec`.
3. `language` is set by code; everything else in the spec is the model's, checked, never rewritten.
4. The lead gets one tool now, as it did in Phase 2; the rest of the conversation waits for Phase 6.
5. Rendered files are served by the app from the data directory; artifacts with IDs and lineage wait for
   Phase 6.
6. The evaluation inputs are saved analyst reports, captured once.
7. Human judgments are the truth of the exit test and are stored with the judged spec; a model judge is
   measured against them, never used in their place.
8. The designer sees at most twelve rows; resolving, not the model, sees the whole result.
9. Pictures stay out of git; judged specs go in.

## 17. Lessons to record

Which charts the human rejected and why, per criterion. How often the repair turn was needed and which
violations came back most. Whether Gemma's judgment matched a stronger model's. Time and cost per design. Which
rulebook lines changed and what they fixed. Whether the twelve-row preview was ever too little. How far the model
judge agreed with the human.

## 18. Capturing mistakes so they do not return

As the standing rule says: every confirmed mistake becomes an evaluation case plus a check or a rulebook line. A
mistake in the choice of chart is a Phase 3 case and a rule. A mistake in the wording is a rulebook line and,
where code can test it, a delivery check. A mistake the renderer made is a Phase 3 render test. The judgments
file records the criterion, so the count per criterion shows where the next fix goes.

## 19. Effort

Five to seven working days: one for the agent, the rulebook, and the prompt; one for the delivery checks, the
runner, and the tests; one for the lead tool, the route, the terminal command, and the browser check; one for
capturing the reports and writing the cases; one for the evaluation runner, the review page, and the benchmark;
one for the judging and the lessons.

## Appendix: how this maps to Pydantic AI

| Design idea | Pydantic mechanism |
|---|---|
| The rulebook as instructions | `Agent(instructions=...)` from the file, plus the generated grammar and catalogue text |
| Tools with the result injected | `agent.tool` functions reading `ctx.deps` |
| Two output tools | `output_type=[ToolOutput(deliver_design), ToolOutput(ask_clarification)]` |
| One send-back | `ModelRetry` with `retries={"output": 2}` and a counter in deps |
| Caps | `UsageLimits(request_limit=...)`, counters in deps, `asyncio.timeout` |
| Tests | `FunctionModel`, `TestModel`, `agent.override`, `capture_run_messages` |
| Evaluation | `pydantic_evals` `Dataset`, `Case`, `Evaluator`, `LLMJudge` |
| Tracing | `logfire.instrument_pydantic_ai()`, already in the app |
