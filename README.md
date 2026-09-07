# Visualization agent: CSV profiling and questions

Install Python 3.12 and `uv`, then install the project dependencies:

```bash
uv sync
```

Copy the environment template:

```bash
cp .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env` to your OpenRouter API key. Set
`PYDANTIC_AI_MODEL` to choose a model; the default is
`openrouter:anthropic/claude-sonnet-4.6`.

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

After uploading a CSV, ask a question about it in the chat. Name the file or its dataset ID
if you have uploaded more than one. The lead passes your question to the analyst.
The dataset is profiled first if needed.

The chat shows a table of up to twenty rows and the total row count. It gives a two-sentence
summary in your language, the assumptions, and any warnings. Ask to see the SQL.
There are no charts yet.

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

## How profiling works

Every statistic and every measurement label is a DuckDB query: counts, distinct values, numeric
aggregates, date ranges, top values, integer-ness, ordinal patterns such as `Q1`, yes/no vocabularies,
short codes such as `F` and `M`, latitude and longitude by name and range, WKT content, and place-name
columns. Python only issues the queries and assigns labels from the results.

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
the prompt contains no raw rows.

Before running the SQL, code parses it. It allows one SELECT on the dataset's table and the
query's own named subqueries (CTEs) only. It rejects other tables, schema-qualified tables,
and all table functions, including file readers. A query is interrupted after 10 seconds.
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
query calls. Code attaches the last query that passed its error checks to the answer.
It checks the summary numbers at submission and sends a failure back once. If that check
still fails, the report records it and includes a warning.

If the data cannot answer the question, or a term such as "recent" has no definition,
the analyst returns one clarification question and a reason. The lead asks that question
and waits for your answer.

## Configuration

`DUCKDB_PATH` selects the DuckDB file, default `data/datasets.duckdb`. `PYDANTIC_AI_ADVISOR_MODEL`
selects the Advisor model; empty disables it. Set `LOGFIRE_TOKEN` to send traces to Logfire;
without it, tracing stays local.

`PYDANTIC_AI_ANALYST_MODEL` selects the analyst model. When empty, it uses
`openrouter:google/gemma-4-31b-it:nitro`, pending the Phase 2 benchmark.
The analyst runs with reasoning switched off and temperature zero.

## Code

| File | Purpose |
| --- | --- |
| `vis_agent/app.py` | Environment wiring: store, profiler, analyst, lead, tracing, web app |
| `vis_agent/lead.py` | The lead agent, its instructions, and dataset listing |
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
| `vis_agent/store.py` | Uploads, DuckDB tables, briefs, profiles, listing |
| `vis_agent/uploads.py` | Upload API, dataset list, profile JSON, background profiling |
| `vis_agent/cli.py` | Terminal chat, profiling, and questions; `vis failures` (`uv run python -m vis_agent.cli failures`) lists failed checks in saved profiles |
| `evals/profiler/` | Evaluation set and real-model runner |
| `evals/analyst/` | Analyst evaluation set and real-model runner |

Run the tests without model API calls:

```bash
uv run pytest -q
```

Run the profiler and analyst evaluation sets against real models:

```bash
uv run python -m evals.profiler.run
uv run python -m evals.analyst.run
```

> Temporal support is installed and `TemporalDurability()` is attached. At this stage, Web Chat calls the agent normally, so runs are not yet durable. True durable execution starts when the agent is called inside a Temporal workflow and worker, which is intentionally deferred to the next design phase.
