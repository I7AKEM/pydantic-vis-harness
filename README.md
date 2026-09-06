# Visualization agent: CSV profiling

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
uv run uvicorn main:app --host 127.0.0.1 --port 7932 --reload
```

Open the browser at http://127.0.0.1:7932.

The app continues to use `Agent.to_web()`. Its `html_source` setting loads a
pinned release of Pydantic's chat UI with the local CSV control added to the
composer, following the [Pydantic Web Chat UI documentation](https://pydantic.dev/docs/ai/guides/web/#custom-html-source).

In PyCharm, use **Run → Edit Configurations → + → Python**:

- Interpreter: the project's `.venv` (Python 3.12).
- Target: **Module name**, `uvicorn`.
- Parameters: `main:app --host 127.0.0.1 --port 7932 --reload`.
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
uv run python cli.py profile --upload sales.csv --brief brief.json
uv run python cli.py chat
```

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

## Configuration

`DUCKDB_PATH` selects the DuckDB file, default `data/datasets.duckdb`. `PYDANTIC_AI_ADVISOR_MODEL`
selects the Advisor model; empty disables it. Set `LOGFIRE_TOKEN` to send traces to Logfire;
without it, tracing stays local.

## Code

| File | Purpose |
| --- | --- |
| `main.py` | Environment wiring: store, profiler, lead, tracing, web app |
| `lead.py` | The lead agent and its instructions |
| `profiler.py` | Profiler agent, `review_profile`, `profile_dataset`, lead tools |
| `measurements.py` | Every statistic and measurement label, via DuckDB |
| `profile_review.py` | Code checks of an interpretation |
| `profile_models.py` | Contracts: brief, statistics, semantics, checks, profile |
| `dataset_store.py` | Uploads, DuckDB tables, briefs, profiles, listing |
| `uploads.py` | Upload API, dataset list, profile JSON, background profiling |
| `cli.py` | Terminal chat and one-shot profiling |
| `evals/profiler/` | Evaluation set and real-model runner |

Run the tests without model API calls:

```bash
uv run pytest -q
```

Run the profiler evaluation set against a real model:

```bash
uv run python -m evals.profiler.run
```

> Temporal support is installed and `TemporalDurability()` is attached. At this stage, Web Chat calls the agent normally, so runs are not yet durable. True durable execution starts when the agent is called inside a Temporal workflow and worker, which is intentionally deferred to the next design phase.
