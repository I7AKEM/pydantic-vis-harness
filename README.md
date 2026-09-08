# Visualization agent: CSV profiling, questions, and charts

Install Python 3.12 and `uv`, then install the project dependencies:

```bash
uv sync
```

Copy the environment template:

```bash
cp .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env` to your OpenRouter API key. Set
`PYDANTIC_AI_MODEL` to choose the lead's model; the default is the specialists' model,
`openrouter:google/gemma-4-31b-it:nitro`, which scored 18 of 21 on the lead evaluation at three
seconds per turn (2026-09-09); `openrouter:anthropic/claude-sonnet-4.6` was the previous default.

Evaluation sets live under `evals/profiler`: twelve hand-made cases, fifty held-out corpus cases, and 150
corpus training cases; `docs/phase-1-lessons.md` records every result. The profiler's instructions were
optimized for the default model with DSPy (`evals/profiler/optimize_instructions.py`, optional dependency
group `optimize`); rerun it after changing the model.

`PYDANTIC_AI_PROFILER_MODEL` selects the OpenRouter model for semantic profiling.
When empty, it uses `openrouter:google/gemma-4-31b-it:nitro`, the fastest model in the
Phase 1 benchmark (see `docs/phase-1-lessons.md`), routed to the highest-throughput host;
the profiler runs with reasoning switched off. `MAX_UPLOAD_MB` defaults to 20. `DATA_DIRECTORY` defaults to the project's `data/` directory.

Run the built-in Web Chat UI:

```bash
uv run uvicorn vis_agent.app:app --host 127.0.0.1 --port 7932 --reload
```

Open the browser at http://127.0.0.1:7932.

The app continues to use `Agent.to_web()`. Its `html_source` setting loads a
pinned release of Pydantic's chat UI with the local CSV control added to the
composer, following the [Pydantic Web Chat UI documentation](https://pydantic.dev/docs/ai/guides/web/#custom-html-source).

In PyCharm, use **Run → Edit Configurations → + → Python**:

- Interpreter: the project's `.venv` (Python 3.12).
- Target: **Module name**, `uvicorn`.
- Parameters: `vis_agent.app:app --host 127.0.0.1 --port 7932 --reload`.
- Working directory: this project directory.

Click **Run**. The app loads `.env` automatically.

## Profile a CSV

1. Click **Upload CSV** in the chat and choose your file. Profiling starts in the background
   as soon as the upload finishes.
2. The chat sends the file reference automatically.
3. The lead agent calls `profile_csv`, which returns the saved profile, and summarizes it.
   Follow its JSON link to view the complete structured profile.

Another program can upload with a brief, the context that travels with the data:

```bash
curl -F file=@sales.csv -F 'brief={"raw_question":"Sales by region","units":{"amount":"USD"}}' \
  http://127.0.0.1:7932/datasets/upload
```

The brief is context, never fact. Its hints feed the interpretation; conflicts with the
measurements become warnings in the profile. `GET /datasets` lists uploads and their profile status.

From the terminal:

```bash
uv run python -m vis_agent.cli profile --upload sales.csv --brief brief.json
uv run python -m vis_agent.cli chat
```

## Ask a question

For numbers only, ask explicitly for a table, a value, or no chart. Name the file or its
dataset ID if you have uploaded more than one. The lead calls `answer_question`; the
dataset is profiled first if needed. Other data questions default to a chart.

The chat shows a table of up to twenty rows and the total row count. It gives a two-sentence
summary in your language, the assumptions, and any warnings. Ask to see the SQL.
Charts can be designed and rendered from the terminal or requested in the chat.

From the terminal, use an existing dataset ID or upload a file:

```bash
uv run python -m vis_agent.cli ask DATASET_ID "question"
uv run python -m vis_agent.cli ask --upload sales.csv "What are total sales by region?"
uv run python -m vis_agent.cli ask --upload sales.csv --brief brief.json "What are total sales by region?"
```

The terminal prints the report as JSON, including the result table, summary, assumptions,
checks, warnings, and SQL. Analysis reports are returned but are not saved.

The analyst's rules forbid inventing numbers or adding filters that the question or brief
did not state. Its query tool cannot read files. If a term is unclear or a needed column
is missing, it asks you a question instead of guessing.

## Ask for a chart

Upload a CSV and ask, for example, “Chart average income by gender.” The lead calls
`draw`: it profiles the file if needed, computes the answer, and returns a chart with
the table behind it, a summary, assumptions, compromises, and warnings. A single number
or a result that cannot be charted comes back as a table with an explanation.

The reply shows an artifact ID (`art_…`) and request ID (`rq_…`). Name the artifact to
revise it, or simply say “Change the colours to dark blue.” A title, colour, or layout
change reuses the saved analysis; a new filter, grouping, measure, or period recomputes
it. Each revision creates a linked artifact version.

If the request asks a question, answer in the next message. Say “continue” to resume
unfinished work, or name its request ID. Completed steps are saved and reused. Ask
“What did we make?” to look up saved artifacts. Attaching data without a question
gets three to five suggested questions based on its profile.

The terminal exposes the same operations. Replace the example IDs with returned IDs;
`draw` also accepts an existing dataset ID and optional `--brief brief.json`:

```bash
uv run python -m vis_agent.cli draw --upload evals/profiler/cases/citizens.csv "Chart average income by gender."
uv run python -m vis_agent.cli revise ARTIFACT_ID "Change the colours to dark blue."
uv run python -m vis_agent.cli revise ARTIFACT_ID "Include only wealthy citizens." --redo-analysis
uv run python -m vis_agent.cli resume REQUEST_ID --answer "Use income greater than 50000."
uv run python -m vis_agent.cli resume REQUEST_ID
uv run python -m vis_agent.cli requests --dataset DATASET_ID
uv run python -m vis_agent.cli artifacts DATASET_ID
uv run python -m vis_agent.cli suggest DATASET_ID
```

These commands print JSON; `suggest` prints the lead's reply. `ask` remains the
numbers-only command. `revise` reuses analysis unless `--redo-analysis` is supplied.
`draw`, `revise`, and `resume` exit 0 when the request is done, 3 while it waits for an answer, 1 when
it failed, and 2 for an input error printed as JSON.

## Agent channel

Programs use these seven JSON routes on the same application:

| Method and route | Purpose |
| --- | --- |
| `POST /requests` | Create a new chart request or a revision; return its ID with HTTP 202. |
| `GET /requests/{request_id}` | Read status, saved steps, artifact ID, and any pending question. |
| `POST /requests/{request_id}/answer` | Submit `{"answer":"…"}` to a waiting request. |
| `POST /requests/{request_id}/resume` | Continue saved work; a waiting request needs an answer first. |
| `GET /artifacts?dataset_id=DATASET_ID` | List the dataset's artifact summaries. |
| `GET /artifacts/{artifact_id}` | Read a complete artifact and its lineage. |
| `POST /agents/ask` | Ask the lead with `question`, optional `dataset_id`, and `caller`; return its reply. |

Upload a CSV through `/datasets/upload` first, then use its dataset ID. For example,
create a request with a return address:

```bash
curl http://127.0.0.1:7932/requests \
  -H 'Content-Type: application/json' \
  -d '{"type":"new","dataset_id":"DATASET_ID","question":"Chart average income by gender.","caller":{"identity":"report-agent","return_address":"http://127.0.0.1:9000/results"}}'
```

The request runs in the background. After each create, answer, or resume background
run, the channel posts the request record to the return address once. Callback failures
are logged without retry; callers can poll the request. A pending question includes a
deadline and an overdue flag. POST routes require `Content-Type: application/json`.

The routes carry no authentication, and the record posted to a return address holds the
result rows and the SQL, so keep the server on `127.0.0.1` as shown above and give return
addresses only to programs on the same machine. `/agents/ask` runs the lead once under the
same cap of forty model requests as a channel request; a question that asks for a chart is
drawn, and its request is recorded as the program's, not the chat's.

## Evaluate the lead

Run the eleven scripted conversations before merging a change to the lead:

```bash
uv run python -m evals.lead.run
uv run python -m evals.lead.run --corpus --out results.json
uv run python -m evals.lead.run --only colour-change --out colour-results.json
```

The runner uses real models and the renderer setup below. It runs three cases at a
time, each with a fresh temporary dataset and request store. `--corpus` appends ten
manifest questions sampled with seed 11 from `CORPUS` in
`evals/designer/agent/corpus_tools/select.py`; that external corpus must exist locally.
`--help` imports and parses arguments without a model call.

Each turn scores the first data tool, the revision's `redo_analysis` flag when relevant,
and its returned outcome. `results.json` saves replies, tool calls and returns, request
records, artifact summaries, and IDs. An artifact score requires a returned artifact,
not a successful PNG; inspect its `no_chart_reason` and the web chat separately. Temporary
CSV, database, and render files are removed after each case. Results and manual checks
belong in `docs/phase-6-lessons.md`.

## Render a chart

The chart commands use a saved analysis report and call no model. Install Node 22 LTS on
PATH, then install the pinned renderer package:

```bash
npm ci --prefix vis_agent/render/gptvis
```

On Debian, also install the runtime libraries and Arabic fonts:

```bash
sudo apt-get install libexpat1 fontconfig fonts-noto-core
```

Check Node, package availability, and an Arabic smoke render (one line each):

```bash
uv run python -m vis_agent.cli doctor
```

The command exits 1 if the renderer is unavailable or the smoke render fails. No extra
system packages are needed on macOS. The renderer package is pinned; never edit `node_modules`.
Below, `uv run python -m vis_agent.cli` is the runnable form of the design's `vis` command.

Save the JSON from `ask` (this step uses the analyst model), then request chart candidates:

```bash
uv run python -m vis_agent.cli ask DATASET_ID "ما نسبة المواطنين الأثرياء حسب الجنس؟" > report.json
uv run python -m vis_agent.cli recommend report.json --intent share --suggested donut
```

The intent vocabulary is `compare`, `trend`, `rank`, `distribution`, `composition`,
`relation`, and `share`. A suggested chart name or alias is a scoring preference.
A clarification without an analysis, or a report without a result, exits 2 with a JSON error.

Save the design's worked donut spec as `donut.vis`. Its bindings must match the report's
column names exactly; adapt the description to the actual result (61.6% and 38.4% are the
worked example, not values to assume for another dataset):

```text
vis donut
title نسبة المواطنين الأثرياء حسب الجنس
description حلقة تُظهر نسبة الأثرياء لكل جنس: الذكور 61.6% والإناث 38.4%
language ar
bind
  category الجنس
  value النسبة
sort value desc
```

Check it and render the same spec with the same report:

```bash
uv run python -m vis_agent.cli check donut.vis --report report.json
uv run python -m vis_agent.cli render donut.vis --report report.json --out chart-output
```

`check` prints violations with fixes, compromises, and canonical text when valid. It exits
0 even when the spec fails. Without `--report`, it only parses the text; the JSON `note`
states that every other rule and renderer capability check was skipped. Both `check` and
`render` accept `--renderer gptvis`, the default and only renderer.

`render` checks first and exits 2 with the failed check as JSON before drawing anything.
Success prints the `png`, `html`, and `config` paths, pixel `width` and `height`, `seconds`,
compromises, and rendering metrics. Runtime renderer failures exit 1 with a JSON error.
The files are `chart.png`, `chart.html`, and `config.json`. Without `--out`, they go under
`DATA_DIRECTORY/renders/` in a folder named by the first 12 hex characters of
SHA-256 of the UTF-8 spec text followed by the original report bytes.

## Design a chart

`vis design REPORT.json [--brief BRIEF.json] [--out DIR] [--no-render]` asks the designer
to choose and specify a chart from a saved analysis report, then renders it by default:

```bash
uv run python -m vis_agent.cli design report.json --brief brief.json --out chart-output
uv run python -m vis_agent.cli design report.json --no-render
```

The printed JSON holds the design's canonical spec, chart type, intent, explanation,
candidates considered, and compromises, plus the passing check, warnings, model, request
and check-call counts, timing, and creation time. Its `render` holds the three paths
(`png`, `html`, `config`) and rendering metrics. With `--no-render`, `render` is null.
A clarification or an unsuccessful design has no design or render; read the clarification
or warnings. These reports exit 0. Incomplete analysis reports exit 2 with a JSON error;
renderer runtime failures exit 1.

Without `--out`, files go to `DATA_DIRECTORY/renders/<render_id>/`, where the ID is the
first twelve hex characters of SHA-256 of the UTF-8 spec followed by the serialized
analysis report JSON. `--renderer gptvis` selects the default and only renderer.

`PYDANTIC_AI_DESIGNER_MODEL` selects the designer model. When empty, it uses the profiler's
default, `openrouter:google/gemma-4-31b-it:nitro`, pending the Phase 4 benchmark.

## Evaluate at scale

The Phase 4b set under `evals/designer/agent/scale/` holds two hundred corpus cases plus twenty
seeded ones, split by source dataset into train (132), dev (44), and heldout (44). Real questions from the
Insightor dev corpus cover result shapes and Arabic data, with English Phase 4 cases
reused for language coverage. Labelled derivatives add Hijri dates, Arabic-Indic digits,
and Arabic label edge cases. Saved analyst reports are fixed inputs to the designer.
The original thirty-one-case Phase 4 set remains the smoke set.

From the repository root, install the optional dependencies and select and seed cases
from the local, read-only corpus:

```bash
uv sync --group optimize
uv run python -m evals.designer.agent.corpus_tools.select --corpus /path/to/corpus
uv run python -m evals.designer.agent.corpus_tools.seed --corpus /path/to/corpus
```

Selection accepts `--count` (default 200); seeding accepts `--out` and `--seed` (default 7).
Before capture, the controller reconciles selected and seeded cases to the two-hundred-case
total and regenerates `splits.json` with `corpus_tools.select.splits`, including seeded
names and keeping source datasets together. The two commands do not do that final step.
Capture requires `OPENROUTER_API_KEY` and writes reports, `cases.json`, and provenance in
`decisions.json`; it reuses existing valid reports:

```bash
uv run python -m evals.designer.agent.corpus_tools.capture --concurrency 4
```

Use `--only NAME [NAME ...]` to capture a subset. Insightor's chosen chart and requested
type are metadata only, never acceptable-chart labels or suggestions to the designer.
For cases with `charts: null`, the reference list uses the designer's declared intent:
nonnegative recommendation candidates within one point of the top score, plus eligible
bar/column, grouped and stacked orientation, and pie/donut swaps. Swaps must remain
nonnegative candidates. `ChartAccepted` measures agreement with these rules, not human
correctness. `IntentPlausible` separately compares intent with a saved orchestrator task.

Run the saved cases with the configured designer model and API key:

```bash
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split train
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split dev
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split heldout --render
```

Omit `--split` for the complete set. Rendering needs the setup above and writes an HTML
review page beside the cases under `renders/<model>/<split>/`. A person judges the held-out
forty for chart type, column roles, truthful title and language, units and formats, honest
presentation, and explanation. Enter verdicts and notes on the page, then copy the exported
JSON into the `judgments` key of `scale/judgments.json`, preserving its `rubric`.

```bash
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split heldout --judgments
```

This reads saved judgments without a model call. The exit test is at least seven in ten
judged correct, reported with and without seeded cases; a pass with a failed rubric
criterion does not count. An optional `--judge MODEL` must use a different model from the
designer and does not replace the person's judgment.

DSPy GEPA optimizes instructions on train and validates on dev; it never loads heldout.
Both commands below need `OPENROUTER_API_KEY`, including the four-example `check`:

```bash
uv run python -m evals.designer.agent.optimize_instructions check
uv run python -m evals.designer.agent.optimize_instructions run light chart-optimization --split train
```

Start with `light`; `medium` is also supported. `PYDANTIC_AI_DESIGNER_MODEL` selects the
task model and `OPTIMIZE_REFLECTION_MODEL` selects the reflection model (Sonnet 4.6 by
default). The output directory holds the optimized program and `instructions-light.txt`,
including the grammar and catalogue. This single-shot program cannot call the runtime
agent's tools. The controller reviews the text, transfers instruction changes into
`vis_agent/designer/rulebook.md` without duplicating the generated grammar and catalogue,
and measures the real agent with its tools. Keep the changes only if automatic scores
beat the seed rulebook on both dev and heldout without lowering the judged sample;
otherwise keep the seed rulebook and record why.

## How profiling works

Every statistic and every measurement label is a DuckDB query: counts, distinct values, numeric
aggregates, date ranges, top values, integer-ness, ordinal patterns such as `Q1`, yes/no vocabularies,
short codes such as `F` and `M`, latitude and longitude by name and range, WKT content, and place-name
columns. Python only issues the queries and assigns labels from the results. Two levels cover Arabic
data: `hijri` for dates written in the Hijri calendar as text (`1447-03-12`, `١٤٤٧/٠٣/١٢`,
`12 ربيع الأول 1447`) and for integer Hijri years beside a Gregorian date, and `arabic_digits` for numbers
written in Arabic-Indic digits, which get numeric statistics after the digits are translated.

The profiler agent interprets those measurements: meaning, role, unit, code meanings, and conflicts
with the brief. It returns the profile through `review_profile`, its only output tool, which runs the
code checks: a time role needs date statistics, an identifier must be near-unique, a measure must be
numeric, units belong only on measures, code meanings must match the codes in the data, ordinal
evidence must be used. A failed check is sent back once. What still fails is recorded in the profile's
`review` and `warnings`.

Complete profiles are reused. A new brief re-runs the interpretation only; the measurements are kept.
Profiles in an older format are recomputed.

## How answering works

The analyst reads the profile, question, and brief. It writes one SELECT and describes each
result column. DuckDB computes the answer. The model receives column facts and query results;
the prompt contains no raw rows. The facts name the columns that carry the `hijri` or `arabic_digits`
level, and only then the rules in `vis_agent/analyst/rulebook-localized.md` join the instructions for that
run: a `hijri` column is bucketed as text (`substr` for the numeric forms, a `CASE` over month names) and
never read as a Gregorian date, and an `arabic_digits` column is translated to Western digits before it
is summed.

Before running the SQL, code parses it. It allows one SELECT on the dataset's table and the
query's own named subqueries (CTEs) only. It rejects other tables, schema-qualified tables,
and all table functions, including file readers.
Columns the profile marked as omitted (long text, WKT, geometry) cannot be queried; the guard rejects them and `*`.
A query is interrupted after 10 seconds.
A result over 1,000 rows is rejected so the analyst can group it further or return fewer rows.

Code checks the result against the data and profile:

| Check | What it checks |
| --- | --- |
| `result_not_empty` | The query returned at least one row. |
| `column_descriptions_match_result` | Each result column has one description with its exact name. |
| `source_column_exists` | Each named source column exists in the dataset. |
| `labels_faithful` | Group labels match source values, or keep a source code beside the label. Applies to unaggregated, non-time groups with at most 200 distinct source values whose values were not omitted. |
| `code_labels_match_profile` | Code and label pairs match the profile or brief. |
| `shares_add_up` | Shares sum to 100 or 1 within tolerance. A mismatch is a warning. |
| `aggregate_in_bounds` | Averages, minima, and maxima stay within the source's numeric range. |
| `total_explained` | Sums and counts match the raw total. A difference produces a warning about excluded rows. |
| `time_in_order` | Time values are chronological. A mismatch is a warning. |
| `summary_numbers_exist` | Summary numbers occur in the result or its row count, allowing rounding and percentages. Western and Arabic-Indic digits are supported. |

Query errors and failed error checks go back to the analyst for repair. It has at most three
query calls. The tool is withdrawn once they are spent. Code attaches the last query that passed
its error checks to the answer.
It checks the summary numbers at submission and sends a failure back once. If that check
still fails, the report records it and includes a warning.

If the data cannot answer the question, or a term such as "recent" has no definition,
the analyst returns one clarification question and a reason. The lead asks that question
and waits for your answer.

## How charts are chosen and checked

The Phase 3 recommendation and checking functions remain deterministic. The validated
`vis_agent/designer/catalogue.json` lists twenty chart types, their aliases, purposes,
accepted roles and column kinds, limits, supported keys, ratings, and renderer mappings.
`recommend_charts` binds described result columns, filters candidates with hard rules,
then adds soft scores. Every candidate keeps its binding and rule breakdown; rejected
charts keep a reason. Ties follow catalogue order.

| Hard rule | Requirement |
| --- | --- |
| H1 | Required roles have columns of allowed kinds. |
| H2 | Keep the result's time column bound, or use a table. |
| H3 | Parts of a whole and stacks need additive values. |
| H4 | Parts of a whole and stacks reject negatives. |
| H5 | Category counts fit the catalogue limits, including two to six pie/donut slices. |
| H6 | Group counts fit the catalogue limit. |
| H7 | Time charts have enough points. |
| H8 | Line/area axes use time or ordinal values. |
| H9 | Histograms and box plots have enough raw, unaggregated values. |
| H10 | Dual axes use different units. |
| H11 | Bars and columns have at most fifty categories. |
| H12 | An empty result has no candidates. |

| Soft rule | Ranking preference |
| --- | --- |
| S1 | Match the intent. |
| S2 | Match the suggested chart or alias. |
| S3 | Penalize catalogue entries rated use with caution. |
| S4 | Prefer readable category counts on bars/columns. |
| S5 | Prefer horizontal bars for long labels. |
| S6 | Penalize slices too similar in size. |
| S7 | Prefer line/area for time. |
| S8 | Prefer stacks for composition and groups for comparison. |
| S9 | Penalize unbound information, with exemptions for identifiers and matching code columns. |
| S10 | Penalize scatter plots with few points. |
| S11 | Penalize sparse word clouds. |
| S12 | Keep a table as the zero-score fallback before other rules. |
| S13 | Prefer a table for one number. |
| S14 | Penalize treemaps with few parts. |

`check_spec` parses the strict indented spec, validates the bindings and chart keys, runs
all applicable checks, and consults the renderer's capabilities. Violations carry rule IDs
and suggested fixes; syntax errors also carry line numbers.

| Check | Requirement |
| --- | --- |
| C1 | The catalogue type is supported by the renderer. |
| C2 | Bound columns exist, match role kinds, and cover required roles. |
| C3 | Keys are accepted by this chart type. |
| C4 | Time/ordinal axes keep their order. |
| C5 | Top N with Other uses a value sort and an additive value. |
| C6 | Palettes contain enough valid hex colors. |
| C7 | Palette/accent colors have at least 3:1 background contrast. |
| C8 | Title and description are present. |
| C9 | Emphasised categories exist. |
| C10 | All hard rules pass. |
| C11 | Axis ranges are allowed for the type, ordered, and contain plotted values. |
| C12 | Cropped line axes require a narrow positive range and disclose their start. |
| C13 | Percent stacks use additive, nonnegative values. |
| C14 | Log scales use supported types and positive values spanning at least 100-fold. |
| C15 | Explicit data labels cover at most fifty marks. |
| C16 | `zero true` does not contradict a nonzero axis minimum. |
| C17 | Number formats follow the grammar; invalid patterns are reported as syntax errors. |

Compromises disclose accepted limitations: for example, an RTL legend stays where the
package puts it, a cropped axis states its start, and a percent format on a non-share
warns that formatting does not calculate a share. The renderer honours RTL title alignment
and category order. Tables have their own capability limitations.

The spec contains bindings, never rows. Code inserts the result's cells, sorts, folds
additive top-N tails into Other, handles nulls, and applies formats and units. A fresh Node
process draws the PNG; `config.json` saves the captured G2 configuration and the resolved
settings. `chart.html` uses that configuration and a pinned G2 browser build, with shared
number formatting and animation disabled so rendering can finish in a background tab.
The page has a white background and dark text, follows the requested reading direction,
and embeds the PNG as an accessible offline fallback. Tables get an HTML table. If the
captured configuration contains unsupported functions, the page keeps the PNG and the
render result discloses that compromise.

## How designing works

The designer reads the question, detected language, the brief's design hints, the analyst's
summary and assumptions, result-column descriptions, and facts measured from the full result.
It sees at most twelve result rows, with string cells cut to forty characters, and never sees
the dataset or SQL. The question, brief, column names, and cells are data, never instructions.

Its two tools are `recommend_charts(intent)`, which returns the top five candidates with
bindings and rule scores plus rejected candidates, and `check_spec(spec)`, which returns
violations with fixes, compromises, and canonical text. Both use the Phase 3 functions.

The `deliver_design` output tool checks the spec again, sets its language from the analysis,
checks the title's script, and checks that explanation numbers occur in the result or question
context. Failures go back once; a second failed delivery returns warnings and no design.
The designer can instead use `ask_clarification` to ask one question. Rendering rechecks
the spec and carries the checker compromises into the rendered result.

Each run allows two recommendation calls, three check calls, one repair send-back, eight model
requests, and ninety seconds. An empty result returns a clarification without calling a model.
Model failures or exhausted limits return warnings without a design. A tool is withdrawn once
its calls are spent; a model that still names it gets one retry and then the run ends. When the
designer fails, the design step runs once more on the fallback model
(`PYDANTIC_AI_DESIGNER_FALLBACK_MODEL`, the lead's model by default) and the chart carries a
warning saying so.

The rulebook lives in `vis_agent/designer/rulebook.md`; code appends the grammar and catalogue
to its instructions. Confirmed mistakes become evaluation cases and checks or rulebook lines.

## Configuration

`DUCKDB_PATH` selects the DuckDB file, default `data/datasets.duckdb`. `PYDANTIC_AI_ADVISOR_MODEL`
selects the Advisor model; empty disables it. Set `LOGFIRE_TOKEN` to send traces to Logfire;
without it, tracing stays local.

`PYDANTIC_AI_ANALYST_MODEL` selects the analyst model. When empty, it uses
`openrouter:google/gemma-4-31b-it:nitro`, pending the Phase 2 benchmark.
The analyst runs with reasoning switched off and temperature zero.

`PYDANTIC_AI_DESIGNER_MODEL` selects the designer model. When empty, it uses the profiler's
default. `PYDANTIC_AI_DESIGNER_FALLBACK_MODEL` selects the model used for one retry of a failed
design step. When empty, it uses `PYDANTIC_AI_MODEL`.

## Code

| File | Purpose |
| --- | --- |
| `vis_agent/app.py` | Environment wiring: store, profiler, analyst, lead, tracing, web app |
| `vis_agent/lead.py` | Chart-first lead, revisions, resume, numbers-only answers, and dataset/artifact lookup |
| `vis_agent/requests/models.py` | Request, checkpoint, clarification, caller, and artifact contracts |
| `vis_agent/requests/store.py` | Requests and artifact versions in the datasets database |
| `vis_agent/requests/runner.py` | Fixed steps, saved outputs, clarification answers, and resume |
| `vis_agent/requests/api.py` | Seven agent-channel routes and one callback per background run |
| `vis_agent/deps.py` | What the lead's tools receive |
| `vis_agent/models.py` | Contracts shared by the store, the lead, and every agent |
| `vis_agent/profiler/agent.py` | Profiler agent, `review_profile`, `profile_dataset`, `profile_csv` |
| `vis_agent/profiler/measurements.py` | Every statistic and measurement label, via DuckDB |
| `vis_agent/profiler/review.py` | Code checks of an interpretation |
| `vis_agent/profiler/models.py` | Contracts: statistics, semantics, checks, profile |
| `vis_agent/analyst/agent.py` | Analyst, query and output tools, `analyze_dataset`, `answer_question` |
| `vis_agent/analyst/query.py` | SQL parser guard, query execution, timeout, row and cell limits |
| `vis_agent/analyst/checks.py` | Result checks and summary number check |
| `vis_agent/analyst/models.py` | Result columns, query results, analyses, clarifications, reports |
| `vis_agent/analyst/rulebook.md` | Analyst instructions and query rules |
| `vis_agent/designer/agent.py` | Designer agent, bounded prompt, checked delivery, `design_chart`, `render_id`, `render_design` |
| `vis_agent/designer/rulebook.md` | Designer instructions for intent, chart choice, spec writing, and clarification |
| `vis_agent/designer/models.py` | Specs, recommendations, violations, checks, and compromises |
| `vis_agent/designer/syntax.py` | Strict spec parser, canonical serializer, number-format grammar |
| `vis_agent/designer/catalogue.py`, `vis_agent/designer/catalogue.json` | Validated twenty-chart catalogue |
| `vis_agent/designer/shape.py` | Result shapes used by design rules |
| `vis_agent/designer/rules.py` | Hard filters, soft scores, and written-spec checks |
| `vis_agent/designer/recommend.py` | Bindings and ranked chart candidates |
| `vis_agent/designer/check.py` | Spec validation and renderer compromises |
| `vis_agent/designer/resolve.py` | Bind result cells, sort, fold, format, and build renderer settings |
| `vis_agent/render/base.py` | Renderer contracts, capabilities, and failures |
| `vis_agent/render/gptvis.py` | Node wrapper, output files, availability, Arabic smoke test |
| `vis_agent/render/gptvis/render.mjs` | PNG rendering and G2 overrides |
| `vis_agent/render/gptvis/format.js` | Shared number formatting |
| `vis_agent/render/gptvis/page.html` | Standalone chart page with embedded PNG fallback |
| `vis_agent/render/gptvis/conformance.mjs` | Compare base specs with the package parser |
| `vis_agent/render/gptvis/package.json`, `vis_agent/render/gptvis/package-lock.json` | Pinned renderer dependency and lock file |
| `tests/designer/`, `tests/render/`, `tests/test_cli.py` | Deterministic design, real rendering, and terminal tests |
| `vis_agent/store.py` | Uploads, DuckDB tables, briefs, profiles, listing |
| `vis_agent/uploads.py` | Upload API, dataset list, profile JSON, background profiling |
| `vis_agent/renders.py` | Read-only routes for chart PNGs, pages, and configurations |
| `vis_agent/cli.py` | Terminal chat, profiling, questions, `draw`, `revise`, `resume`, `requests`, `artifacts`, `suggest`, `recommend`, `check`, `render`, `design`, `doctor`; `vis failures` (`uv run python -m vis_agent.cli failures`) lists failed checks in saved profiles |
| `evals/lead/` | Scripted conversation cases, corpus sample, and lead evaluation runner |
| `evals/profiler/` | Evaluation set and real-model runner |
| `evals/analyst/` | Analyst evaluation set and real-model runner |
| `evals/designer/agent/` | Designer model evaluation on saved analysis reports and chart judgments |
| `evals/designer/agent/corpus_tools/select.py` | Deterministic corpus selection, coverage, and dataset-disjoint split assignment |
| `evals/designer/agent/corpus_tools/seed.py` | Reproducible Hijri and Arabic transformations of real CSVs |
| `evals/designer/agent/corpus_tools/capture.py` | Capture fixed analyst reports and record cases and provenance |
| `evals/designer/agent/run.py` | Smoke and scale evaluation, split filtering, rule references, rendering, and judgments |
| `evals/designer/agent/optimize_instructions.py` | DSPy GEPA instruction optimization on train and dev |
| `evals/designer/agent/scale/` | Scale cases, saved reports, provenance, splits, seeded files, and human judgments |

Run the tests without model API calls:

```bash
uv run pytest -q
```

Run the profiler and analyst evaluation sets against real models:

```bash
uv run python -m evals.profiler.run
uv run python -m evals.analyst.run
```

> Temporal support is installed and `TemporalDurability()` is attached. At this stage, Web Chat calls the agent normally, so runs are not yet durable. True durable execution starts when the agent is called inside a Temporal workflow and worker, which remains deferred. Phase 6 saves request step outputs in DuckDB; it does not add a Temporal worker.
