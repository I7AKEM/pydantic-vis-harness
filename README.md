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

`PYDANTIC_AI_PROFILER_MODEL` optionally selects a different OpenRouter model for
semantic profiling. When empty, it uses `PYDANTIC_AI_MODEL`. `MAX_UPLOAD_MB`
defaults to 20. `DATA_DIRECTORY` defaults to the project's `data/` directory.

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

1. Click **Upload CSV** in the chat and choose your file.
2. The chat sends the file reference automatically.
3. The agent calls `profile_csv` and summarizes the result. Follow its JSON link
   to view the complete structured profile.

The chat upload control stores the file locally; the one agent tool imports it into DuckDB,
computes statistics, calls the semantic profiler, and saves the combined
`DatasetProfile`. Completed profiles are reused. If semantic profiling fails,
statistics are saved as a partial profile; asking again retries the semantic stage.

CSV files must be UTF-8, comma-separated, with unique, nonempty headers and up to
100 columns. Inconsistent row widths and broken quoting are rejected. DuckDB
infers types from the entire file; the original CSV and original column names
are retained. Empty fields are interpreted as null.

Statistics cover every imported row: row and duplicate counts, missing and distinct
values, numeric aggregates, date ranges, and common categorical values. Numeric
aggregates use double precision, finite values, and population standard deviation.
The semantic model receives these statistics and the first five rows. Sample and
common-value text is capped at 120 characters per value, and any column containing
a value over 256 UTF-8 bytes is excluded from both. Meaning, units, and
confidence are interpretations and may need your confirmation.

Oversized values, including WKT geometry, stay in DuckDB and are excluded entirely
from both agents' inputs. Their profile entries contain metadata and counts with
`values_omitted: true`. WKT columns are always excluded, even when their current
values are short. Older cached profiles are recomputed when the profile format changes.

Uploaded CSVs live in `data/uploads/`; tables, metadata, and profile JSON live in
`data/datasets.duckdb`. This is a local, single-user app. Files are selected by
their explicit IDs, so profiling another upload does not change a shared current
dataset. The data survives server restarts and is ignored by Git.

## Code

| File | Purpose |
| --- | --- |
| `main.py` | Agent, dependencies, tool registration, and web app |
| `profile_models.py` | Validated profile schemas |
| `dataset_store.py` | CSV validation, local files, and DuckDB storage |
| `profiler.py` | The profiling tool, fixed queries, and semantic agent |
| `chat.html` | Pydantic's documented custom HTML source |
| `chat_upload.js` | CSV control inside Pydantic's chat composer |
| `uploads.py` | Upload API and saved profile JSON endpoint |

Run the tests without model API calls:

```bash
uv run python -m pytest
```

> Temporal support is installed and `TemporalDurability()` is attached. At this stage, Web Chat calls the agent normally, so runs are not yet durable. True durable execution starts when the agent is called inside a Temporal workflow and worker, which is intentionally deferred to the next design phase.
