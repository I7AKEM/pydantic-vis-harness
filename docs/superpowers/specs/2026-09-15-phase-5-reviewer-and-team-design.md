# Phase 5: The reviewer and the team

Date: 2026-09-15
Status: draft for approval.
Builds on: the Phase 6 design (docs/superpowers/specs/2026-09-08-phase-6-lead-and-conversation-design.md) and the
analyst–designer repair (docs/superpowers/plans/2026-09-09-analyst-designer-repair.md, branch
`analyst-designer-repair`, which this phase branches from).

## 1. Purpose

Three things, in one phase, because each needs the other two:

1. **A reviewer.** An independent agent that looks at the rendered picture, the table, and what the team already
   knows about the chart, and says whether the chart can go to the user. Its findings go back to the designer, a
   bounded number of times. The review step in the runner has been a placeholder ("not reviewed") since Phase 6.
2. **The team.** Today each agent enforces its rules alone: a failure becomes a user question or a dropped chart.
   From this phase on, an error is handed to the agent that can fix it, and every warning travels with the
   artifact to the reviewer and to the user. The designer already hands back to the analyst (the repair);
   the reviewer hands back to the designer; nothing else changes in the fixed step order.
3. **One rule list per agent, with two levels.** The rules live in three copies that disagree: the code checks,
   the prose rulebooks, and the evaluation team's rubric. The evaluation run of 2026-09-13 graded the agents
   against the prose and failed them for promises the code never kept. This phase makes each rule live in one
   place, at one of two levels: an **error** stops delivery and is handed back; a **warning** travels with the
   artifact. Rules the code can decide leave the prose. Rules nobody enforces or measures leave the rulebooks.

Out of scope: a second renderer (Vega-Lite moves to Phase 5b, see section 12), the insight finder, maps,
dashboards, a message bus, a planner, and any free conversation between agents.

## 2. What the evaluation run showed

The evaluation team ran 283 cases against `dev` at 53c179b through OpenRouter (lead Sonnet 4.6, specialists
Gemma 4 31B) with two model judges, Claude Sonnet 4.6 and GPT-5.4, reading the rulebooks as their rubric.
The run is in `~/Downloads/20260913-183937/` (summary.json, one file per case with both judges' reasons, the
pictures) and its traces in the Logfire project `ali-y-alkhowaiter/llm-eva-viz`.

| Agent | Judged | Both judges pass | Both fail | Split | What failed, and the reading |
|---|---:|---:|---:|---:|---|
| Profiler | 279 | 2 | 270 | 7 | 274 on **units**: the string `'null'` (also `'count'`, `'unitless'`) written as a unit. One code bug. 54–66 on the **language** of descriptions and meanings (Arabic text for English headers with no brief). 13–32 on **roles** (place names as geography without geographic evidence): judgment calls. |
| Analyst | 157 | 29 | 138 | 101 | 74 on **columns**, nearly all "a percent column with unit null". 14 on **summary** ("two sentences" taken literally). 8–12 on **scope** and **assumptions**: a period named in the question with no filter and no assumption. 9 on **shape**: a trend ordered newest first; wide instead of long. **111 cases asked a question** instead of answering: 28 on one-row files, 51 on files of two to ten rows, 23 on larger ones. |
| Designer | 136 | 25 | 85 | 47 | 96 on **honest**: one colour per bar on a single series (a Phase 4b "left for later" item, now in the rubric). 49 on **picture**: truncated table headers. 51 on **title** (GPT-5.4 wants where and when; Sonnet failed one, for a number in the title). 23 on **units**: `person` on every tick, tiny values shown as `0`, swapped axis titles on horizontal bars. 15 on **type**: the rulebook's preferences (a donut for two parts) applied as requirements. |
| Lead | 58 | 1 | 39 | 18 | 56 on **shows**: the reply lacked the table (26), the row count (25), the IDs (23), the picture (21), assumptions (14), compromises (12), warnings (11). 31 on **numbers**: figures with no artifact behind them. 24 on **tool**: a data question answered from the profile. |

Two readings matter for the design. First, the biggest losses are code defects and reply format, not model
judgment: the unit string, the single colour, the percent unit, the lead's missing record. Second, the judges
held the agents to the prose: "the rulebook requires two sentences", "the rulebook prescribes a donut". A rule
that is written down is graded, whether or not anything enforces it. The rulebooks must therefore say only
what is enforced or genuinely left to judgment, and say which is which.

The run also shows what a reviewer will meet: compromises are recorded on 105 of 283 charts for `direction`
(the legend stays where the package puts it), which is noise a reviewer must not weigh as a defect.

## 3. The team

Six members. Five are model agents; the renderer is code. Each has a seat (a model), a scope, and a fixed set
of moves. "Hands back" is the only way one agent tells another it cannot proceed; "asks the user" is reserved
for a decision only the user can make.

| Member | Sees | Decides | Hands back to | Asks the user when | Never |
|---|---|---|---|---|---|
| **Profiler** (model) | Measured statistics per column, a bounded sample, the brief | Roles, meanings, units, code meanings, ordinal scales | Nobody (first step) | Never | Computes a number; passes long values to the model |
| **Analyst** (model) | Table name, row count, column facts and profile interpretation, the question, the brief, answers, a previous SQL and change or the designer's feedback | One SELECT, column descriptions, summary, assumptions | Nobody; it is the last stop upstream | The columns cannot answer, or a term has no definition | Sees raw rows; sums a percent; adds a filter silently; asks about presentation |
| **Designer** (model) | The question, the analyst's summary and assumptions, result columns with facts, a twelve-row preview, the brief's intent and colours, a previous spec and change, the analyst's revision reply, the reviewer's findings | Chart type, bindings, fold, sort, limit, titles, palette, labels | The analyst, once per request, for a table it cannot draw | Which of two columns; colours that cannot meet contrast | Writes a number; asks about its own check failures; requests a second table revision |
| **Renderer** (code) | The spec and the result | Nothing; it honours, degrades, or rejects each key and says which | Nobody; a rejection is a `check_spec` error before it runs | Never | Invents a compromise the designer did not make |
| **Reviewer** (model, new) | The picture, the spec, the question, the drawn rows, the record (assumptions, compromises, warnings, checks), the brief's caveats | Whether the chart can go to the user, with findings each tied to a rule | The designer, up to two rounds per request | Never | Fixes anything itself; sees the dataset; asks the user |
| **Lead** (model) | The conversation, the tool outcomes | Which tool to call, and the reply | Nobody | To relay a specialist's question, only | Designs a chart; answers a value from the profile; restates a number that is not in the card |

The lead is not the team's manager inside a request. Inside a request the runner is the manager: it runs the
steps, saves each output, enforces every bound, and decides what happens on a hand-back. The lead starts
requests, relays questions, and shows results.

### 3.1 Assessment of the instructions, agent by agent

Each rulebook was read in full on the repair branch, alongside its tools, and compared with what the
evaluation run graded. The findings below are what the ledger in section 5 acts on.

**Profiler** (`vis_agent/profiler/rulebook.md`, one output tool `review_profile` with code checks). Capability is
clear and well bounded: interpret, never compute; the brief is context. Gaps: (a) the rulebook says a unit is
null for non-measures but the model writes the word `null`, and the `unit_only_on_measures` check does not
catch the string; (b) "write descriptions in the language of the brief's question, otherwise of the column
names" leaves the model to guess when headers are English and values Arabic, and the profiler runs at upload
time, before any question exists; (c) the geography rules are long and conditional, and the judges applied
them as the rulebook states them; the failures there are judgment, not defects.

**Analyst** (`rulebook.md`, `rulebook-revise.md`, `rulebook-localized.md`, `rulebook-repair.md`; tools
`run_query` with a budget of three, outputs `deliver_analysis` and `ask_clarification`). The shape table is the
strongest part of any rulebook in the system. Gaps: (a) "write a unit for percent" is prose, and the model
leaves it null in 74 cases; (b) "two-sentence summary" is a style instruction graded as a rule; (c) "in
chronological order" for a trend is backed only by the `time_in_order` warning, while a reversed time axis
draws a misleading line; (d) a period the question names and the SQL omits is caught by nothing; (e) the
long-format rule is now redundant: the designer folds same-unit measures in code; (f) the two reasons to ask
are right, and on the corpus files (result-table exports, four in ten holding one cell) most questions are
honestly unanswerable; but a question that restates the user's question is still not refused by code.

**Designer** (`rulebook.md`, `rulebook-revise.md`; tools `recommend_charts` ×2 and `check_spec` ×3; outputs
`deliver_design`, `ask_clarification`, `request_analysis_revision`). Capability and scope are precise, and
the grammar and catalogue are the model's whole vocabulary. Gaps: (a) the rulebook implies one colour per
series and the renderer draws one per bar; (b) generic count markers written as units (`count`, `عدد`) reach the
axis, while a noun the data names (`person`, `شخص`) must stay; (c) values below the display precision print as `0`; (d) axis titles swap on horizontal bars; (e) the
"choosing when the rules cannot" list reads as preferences and is graded as requirements; (f) "no numbers in
the title" blocks a year the user asked for; (g) the table renderer truncates long headers and nothing records
it.

**Lead** (`LEAD_INSTRUCTIONS` in `vis_agent/lead.py`, 1,070 words after the DSPy round). Tool choice is good
(21 of 21 on the project's own evaluation). The gap is the reply: the instructions ask the model to assemble
the picture, the summary, a twenty-row table with the total count, assumptions, compromises, warnings, and
two IDs from a tool result, every time, and it drops one or more in 56 of 58 judged replies and invents a
figure in 31. That is a job for code.

**Reviewer**: none yet. Section 6.

## 4. Workflow

The fixed step order stays: understand, profile, analyze, design, render, review, deliver. A saved output per
step, resume from the first step without one. Two bounded hand-backs are the only exceptions:

```
understand → profile → analyze → design → render → review → deliver
                          ↑          |        ↑        |
                          └──────────┘        └────────┘
                       analysis revision     review round
                       (once per request)   (at most two per request)
```

**A review round.** When the reviewer returns an error-level finding and rounds remain, the runner runs the
design step again with the findings and the previous spec (`review`, the way `previous` and `revision` reach
the designer today), then render and review again. Inside that round the designer may still ask the analyst
for a revised table, if the request's single revision is unspent; the reviewer never reaches the analyst
directly (decision taken: one hop per agent). When the rounds are spent, or the reviewer passes the chart, the
request delivers. A chart that still carries error-level findings after the last round is delivered with the
findings as warnings on the artifact and in the lead's card, never as a question to the user, and never
dropped: a chart with a stated defect beats no chart, and the user sees the defect.

**Bounds, enforced in code and saved on the request:** one analysis revision (exists), two review rounds,
one fallback designer run (exists), the request's model-request budget (exists; each review round adds one
reviewer request and roughly three designer requests). All counts persist on the request, so a resume, a
crash, or the fallback designer never starts a fresh allowance.

**Checkpoints for rounds.** The current round's design, render, and review outputs stay under their step names;
when a round starts, the previous three move into `request.rounds` (a list, in order), and the rounds counter
comes from its length, never from a separate field. A killed run resumes at the first missing step of the
current round. The artifact keeps the final round and the list of earlier rounds in its `review` field, so
the lineage shows what the reviewer said and what changed.

**Where a hand-back may not go.** The designer never hands the reviewer's finding on to the analyst as a
question; it either changes the spec, requests the one revision with the finding as evidence, or delivers
the best chart the table allows and says so. The reviewer never asks a question; a finding it cannot tie to a
rule is a judgment finding with its own id (section 6).

**What the user sees.** The lead's tools return, beside the outcome, a **card**: the picture link, the
summary, the table (at most twenty rows) with the total row count, the assumptions, the compromises, the
warnings, the reviewer's verdict and open findings, and the artifact and request IDs, assembled by code in the
caller's language. The lead shows the card as returned and adds its words around it. This replaces the
paragraph of instructions that asked the model to assemble the same list.

## 5. Rules: two levels, one home each

**Definitions.**

- **Error**: the output would be wrong or misleading (a number, a label pairing, a unit, a shape, the order of
  time, a cropped axis, an unreadable picture). An error stops delivery at the agent that found it: it is
  fixed there, or handed back with the diagnosis, within the bounds. It is never turned into a user question.
- **Warning**: the output would read worse (colour count, long labels, title style, few points, a renderer
  compromise). A warning is recorded on the artifact, shown on the card, and weighed by the reviewer.
- **Judgment**: a rule that only a model can apply (which intent the question carries; whether a place-name
  column is geography). It stays in the rulebook, marked as judgment, and the reviewer's rubric treats it as
  "weigh", not "pass or fail".

Anything code can decide leaves the prose. A rule enforced by nobody and measured by nobody is deleted.

**One list per agent.** Each check result already carries a name, a level, and a message (the profiler's and
the analyst's `ProfileCheck`, the designer's `Violation` and `Compromise`). This phase adds one field, `owner`
(who can fix it: `analyst`, `designer`, `renderer`, `user`, `none`), and makes each agent's list the source of
three things: its checks, the rule lines in its rulebook, and the reviewer's rubric. No new rule format: the
designer's `H`, `S`, and `C` ids and the analyst's and profiler's check names stay. The rulebooks keep their
prose for judgment rules and the "how to work" steps, and lose every line the code now enforces except a
one-line pointer ("the checks enforce units; fix what they report").

**The ledger.** Every row below was found either in the evaluation run (with its count) or in reading the
instructions. Rows not listed keep their current level.

| Id | Agent | Rule | Today | Evidence | Decision |
|---|---|---|---|---|---|
| P-unit | Profiler | A unit is JSON null for non-measures and counts; never a placeholder word | Prose; check misses the string | 274 | Code normalises `null`, `none`, `n/a`, `count`, `unitless`, `-` to null before the checks; `unit_only_on_measures` tested with the string. Error, fixed in code |
| P-lang | Profiler | Descriptions and meanings follow one language | Prose, ambiguous | 54–66 | Code decides the language (the brief's question, else the headers) and passes it in the prompt; a `language_matches` warning check on the output |
| P-geo | Profiler | Place names are geography only with geographic evidence | Prose | 13–32 | Judgment; the failed cases join `evals/profiler` |
| A-pct | Analyst | A share declares its scale; a percent column carries `%` | Prose | 74 | Code turns percent aliases into `%`. A share with no declared scale is an error (`share_scale_declared`, from the indicator work): code cannot tell 0.45 from 45. The rulebook line becomes a pointer |
| A-two | Analyst | "Two-sentence summary" | Prose | 14 | Deleted; "one or two sentences" |
| A-time | Analyst | A trend is in chronological order | Warning `time_in_order` | 9 | Error when the SQL orders by the time column descending (the parser sees the ORDER BY): a reversed time axis draws a misleading line. A result ordered by a measure keeps the warning |
| A-period | Analyst | A period or year the question names appears in the SQL or in an assumption | Nothing | 8–12 | New warning `named_period_missing`, general: years and Hijri years found in the question text, in any script |
| A-long | Analyst | Same-unit measures in long format | Prose rule | fold exists | Prose only, downgraded: the designer folds in code |
| A-ask | Analyst | Ask only for a missing column or an undefined term | Prose | 111 asked | Kept. New error check: a clarification that restates the question is refused (one retry). The evaluation reports asks by row-count bucket |
| D-one | Designer | One colour for a single series | Prose; renderer ignores | 96 | Renderer default: a single series takes one colour unless the spec names a palette or emphasis. Error, fixed in code; leaves the rubric |
| D-count | Analyst (code) | A generic count marker is not a unit; a noun the data names is | Resolver drops a short word list | 7 | One list in `vis_agent/units.py`: the profiler and the analyst's query step drop `count`, `number`, `عدد`; `person`, `شخص`, `نسمة` stay and are shown beside the KPI number and in the axis title |
| D-zero | Designer | Values print with enough decimals to differ from zero | Nothing | in 23 | Resolver sets decimals from the smallest non-zero absolute value when `format` is unset. Fixed in code |
| D-axis | Designer | Axis titles follow the axis, not the direction | Bug | in 23 | Fixed in the resolver, with a test per direction |
| D-pref | Designer | The "choosing when the rules cannot" list | Prose | 15 | Marked as preferences in the rulebook and the rubric; they stay `S` warnings in recommendation scores |
| D-title | Designer | No numbers in the title | Prose | 1–51 | Warning `title_number` in `check_spec`, unless the number is a year the question names |
| D-head | Designer | Table headers are not truncated | Nothing | 49 | Renderer records a compromise `headers` when it shortens a header; widened columns where the package allows. Warning |
| D-dir | Designer | `direction` compromise | Recorded on 105 charts | 105 | Kept, but recorded only when the brief or the change asked for that direction; a designer default is not a compromise of the request |
| L-card | Lead | The reply shows the picture, summary, table, row count, assumptions, compromises, warnings, IDs | Prose, 8 items | 56 | The card, built by code. The instruction shrinks to "show the card" |
| L-num | Lead | No number that is not in the results or the user's words | Prose | 31 | An output validator on the lead, reusing the designer's and the analyst's number check: a number outside the card and the conversation is one `ModelRetry`; list ordinals, IDs, and dates are not numbers. Error |
| L-tool | Lead | A data question goes through a tool | Prose, measured by the lead evaluation | 24 | Kept; measured, not changed. The two one-cell corpus files remain known misses |
| R-1…R-5 | Reviewer | Section 6 | New | — | The reviewer's own rules |

**Where the evaluation team's rubric fits.** Their rubric was written from the rulebooks. After this phase,
each agent's rule list is the rubric; the team will be offered the lists so both sides grade the same thing.
Their stricter readings (the `count` word as a forbidden unit; "two sentences") are settled by the ledger, not
by argument.

## 6. The reviewer

**Seat.** A model different from the designer's, able to read an image, able to run on the cluster's LiteLLM
proxy. Probed on 2026-09-15: the proxy's `google/gemma-4-31B-it-qat-w4a16-ct` now returns tool calls and reads
images, so the specialists can run there; the reviewer's candidates on the proxy are `Qwen/Qwen3.8-27B`,
`MiniMaxAI/MiniMax-M2.5`, `zai-org/GLM-5.2-FP8`, and `google/gemma-4-31B-it` (unquantised, when its engine is
up), each to be probed for image input and picked by the agreement test in section 9. On OpenRouter the seat is
any image-reading model other than the designer's, chosen the same way. `PYDANTIC_AI_REVIEWER_MODEL` names it;
`providers.py` builds one reviewer per team, like the fallback designer.

**Input** (one prompt, no tools): the picture as `BinaryContent` (PNG), the question and the caller's
language, the spec as written, the rows the chart drew after limit and Other (at most one hundred), the
result columns with units, the analyst's summary and assumptions, the compromises and warnings so far, the
brief's caveats, and the rubric generated from the designer's and the analyst's rule lists. It never sees the
dataset, the SQL, or the profile.

**Output** (one output tool, `deliver_review`): a list of findings, each with `rule` (an id from the lists or
one of the reviewer's own), `level`, `owner`, and a `message` in the caller's language; plus a one-sentence
`summary`. Code derives the verdict: any error-level finding is `revise`; none is `pass`. The model does not
choose the verdict, so it cannot pass a chart it faulted. Malformed output is retried twice by the framework;
a third failure is a technical failure recorded as a warning, and the chart delivers unreviewed with that
warning, as today.

**The reviewer's own rules**, for what code cannot check:

| Id | Rule | Level |
|---|---|---|
| R-1 | The numbers and labels in the picture match the drawn rows: each mark pairs with its label, the axis range matches the values | Error |
| R-2 | The picture is readable: no truncated or overlapping labels, legible text, the legend matches the series | Error when a label cannot be read; warning otherwise |
| R-3 | The chart answers the question asked, for the place, period, and measure it names | Error |
| R-4 | The title, axis titles, and the explanation are true to the picture and in the caller's language | Warning; error when a title states something the picture does not show |
| R-5 | Nothing misleads: baseline, sort, emphasis, colour that implies a meaning it does not have | Error |

A finding that names a code rule the designer's checks should have caught (an `H` or `C` rule) is a defect in
the checks and is logged as such; the reviewer is not the place to enforce them, and the evaluation counts how
often it happens.

**Cost and time.** One model request per review, no tools, a picture of about 100 kB. Target under ten
seconds on the proxy. Every chart turn gains one request; a revise round gains roughly four.

**What the designer receives on a round.** `review`: the findings, the previous spec, and a per-run rulebook
`rulebook-review.md`: fix each finding in the spec; when a finding needs a different table and the revision
is unspent, request it with the finding as evidence; when a finding cannot be fixed within the catalogue, deliver
the best chart and say why, and the finding stays as a warning. Never dispute a finding in a question to the user.

## 7. Persistence and lineage

- `Request` gains `rounds: list[Round]` where a `Round` holds the design, render, and review outputs of an
  earlier round, and `review_feedback` (the findings the current design round works from). Defaults let every
  saved request load unchanged.
- `Artifact.review` (exists, a dict) holds the final review and the earlier rounds.
- Every review is saved as a labelled example: `evals/reviewer/verdicts/` receives the case key, the render id,
  the spec, the findings, and later the human verdict, the way the designer's `judgments.json` works today.
- The lineage records the reviewer's model beside the analyst's and the designer's.

## 8. Tests

Through the agents with fake models via `agent.override`, never a hand-built `RunContext`, as before.

- The normalisers and new checks, each with the evaluation run's real failing output as the fixture (the
  `'null'` unit, the null `%`, the `person` unit, the reversed trend, the truncated header).
- The renderer's single colour: a single-series bar and column render with one colour; a grouped one keeps
  its palette; an emphasis keeps the accent.
- The reviewer: a fake model that returns an error finding sends the request into a round; one that returns
  a warning delivers with the warning on the card; malformed output twice, then delivery unreviewed.
- The loop: a fake designer that never fixes the finding stops after two rounds and delivers with the finding
  as a warning; a kill between render and review resumes into the same round; the fallback designer inside a
  round does not gain a round; a review round that requests an analysis revision after one was spent is a
  failure the table answers.
- The card: assembled from a saved artifact in both languages; the lead's output validator retries a reply
  that adds a number and accepts one that quotes the card.
- The lead evaluation, the analyst evaluation (70 cases), the model-free designer set (37), and the designer
  agent set (31) run unchanged; the scale set's automatic scores must not fall.

## 9. Evaluation and exit test

**The labelled set.** The existing hand judgments are 59 charts with two fails, too few to measure agreement.
The set for this phase is 60 charts from the evaluation team's run, drawn from the 110 designer cases where
both judges agreed: the 25 passes and 35 of the 85 fails, with the owner or the evaluation team confirming each
verdict by eye against the picture; plus the 40 held-out scale renders. Verdicts and findings are stored as in
`evals/designer/agent/judgments.json`. The reviewer's evaluation runner (`evals/reviewer/run.py`) scores
agreement per chart and per finding, and reports which reviewer rules and which code rules fired.

**Exit test**, as the master design states it, with the numbers made concrete:

1. The reviewer agrees with the human verdict on at least eight in ten of the labelled set, for the chosen seat
   on the proxy and on OpenRouter.
2. Charts delivered after the loop score higher than first charts on the same set: the automatic scores do not
   fall, and the judged sample's pass share rises.
3. No new user questions: the count of clarifications on the lead and analyst evaluations does not rise.
4. Ordinary requests add exactly one model request (the review) and no round when nothing is wrong.
5. The evaluation team's rerun, with the same harness label rules, shows the profiler's unit failures and the
   designer's single-colour failures gone; the rest is reported, not targeted.

Before and after are measured on the same day, same models, same cases, on the proxy.

## 10. Models, limits, and cost

Specialists on the proxy's Gemma 4 31B qat (tool calls and images work as of 2026-09-15); the lead as
configured per team; the reviewer per section 6. The request budget rises by the review rounds' cost: default
`MAX_REVIEW_ROUNDS = 2`, `PYDANTIC_AI_REVIEW_ROUNDS` to change it, `0` turns the loop off and keeps the
verdict. Latency target: a chart turn under thirty seconds on the proxy including one review.

## 11. Files

- `vis_agent/reviewer/`: `agent.py` (prompt, `deliver_review`, `create_reviewer`, `review_chart`), `models.py`
  (`Finding`, `Review`), `rulebook.md`, `rubric.py` (the rubric text generated from the rule lists).
- `vis_agent/designer/rulebook-review.md`, the per-round designer rules; `check.py` and `resolve.py` for `C21`,
  `title_number`, decimals, axis titles; `catalogue.json` unchanged.
- `vis_agent/render/gptvis.py` and the renderer package config for the single colour and the `headers`
  compromise.
- `vis_agent/profiler/agent.py` and `review.py` for the unit normaliser and the language field;
  `vis_agent/analyst/checks.py` and `agent.py` for `%`, `time_in_order` level, `named_period_missing`, and
  the restated-question refusal.
- `vis_agent/requests/models.py`, `runner.py`, `store.py` for rounds and the review step; `vis_agent/lead.py`
  and a new `vis_agent/card.py` for the card and the output validator; `providers.py` for the reviewer seat.
- `evals/reviewer/` (runner, labelled set, verdict store); `tests/reviewer/`; `docs/phase-5-lessons.md`;
  `AGENTS.md` updated with the review round and the rule levels.

## 12. Decisions taken before the plan

- The reviewer hands back to the designer only; the designer decides whether the analyst is needed (owner's
  choice, 2026-09-15).
- Two rule levels, error and warning, plus prose-only judgment rules. No third severity.
- The rules ledger covers all four existing agents, not the designer alone.
- The reviewer must be able to run on the cluster proxy; OpenRouter models serve the evaluation judges and the
  laptop.
- Vega-Lite moves to Phase 5b: nothing in the evaluation asks for a second renderer, and the reviewer judges
  pictures, so it is renderer-neutral by construction. The neutrality proof waits for a renderer need.
- Fixed step order kept; hand-backs are the only exceptions, each bounded and persisted.
- The lead's reply record is assembled by code, not by the model.
- No message bus, planner, workflow engine, or new orchestration layer.

## 13. Lessons to record

Which reviewer rules fire and how often; how often a round fixes the finding versus delivers with it; how
often a finding names a rule the checks should have caught; agreement per seat and per language; asks per
row-count bucket; the cost and time per review round; and what the evaluation team's rerun shows once the
ledger is applied.

## Appendix: how this maps to Pydantic AI

| Design idea | Pydantic mechanism |
|---|---|
| The reviewer reads the picture | `BinaryContent(data=png, media_type="image/png")` in the user prompt |
| One output, no tools, retried on malformed output | `output_type=ToolOutput(deliver_review)`, `retries={"output": 2}` |
| The verdict derived by code from the findings | A plain function after the run; the model never sets the verdict |
| The lead cannot add a number | `@lead.output_validator` raising `ModelRetry` once |
| Bounds on rounds, revisions, and requests | Counts on the persisted request; `UsageLimits(request_limit=...)` per run |
| Per-round designer rules reach the model only on rounds | `instructions` built per run, as `rulebook-revise.md` and `rulebook-repair.md` are today |
| Tests with fake models | `agent.override(model=FunctionModel(...))`, never a hand-built `RunContext` |
