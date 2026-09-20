# Visualization team

A Pydantic AI lead turns an upstream data agent's CSV into a chart using the question or intent in its brief.
The CSV is authoritative. The lead directs specialist tools and decides when the chart is ready.

## Setup

What you need first:

| Tool | Version | Why |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | any current release | Python dependencies. It installs Python 3.12 itself, from `.python-version`. |
| Node and npm | Node 22 LTS or newer | The chart renderer runs on Node. |
| A model provider | — | An OpenRouter API key, or the LiteLLM proxy's URL, token, and model name. |

Then, from the repository root:

```bash
uv sync
npm ci --prefix vis_agent/render/gptvis
cp .env.example .env
```

Open `.env` and set `OPENROUTER_API_KEY`. A provider is the only thing you have to fill in; every other
line has a working default. For the cluster proxy instead, set `LITELLM_BASE_URL`, `LITELLM_TOKEN`, and
`LOCAL_LLM`. [Configuration](#configuration) describes the models each role uses.

Check the renderer. `vis` is the project's command, installed by `uv sync`; this call reads no credentials:

```bash
uv run vis doctor
```

It prints the Node version, whether the pinned renderer is installed, and whether a smoke chart with
Arabic labels came out. All three lines must say `ok`; anything else is in [Troubleshooting](#troubleshooting).

Run the tests. They use fake models, so they pass with no provider configured:

```bash
uv run pytest -q
```

Draw a first chart from a sample CSV in the repository. This one calls the provider:

```bash
uv run vis draw \
  --upload evals/profiler/cases/sales.csv \
  --brief evals/profiler/cases/sales.brief.json \
  "Sales by region"
```

Start the app and open [the chat](http://127.0.0.1:7932):

```bash
uv run uvicorn vis_agent.app:app --host 127.0.0.1 --port 7932 --reload
```

The app uses Pydantic AI's built-in Web Chat UI. Uploads, the DuckDB file, and published charts are
written to `./data`, which is created on first use and stays out of git. Keep the app on `127.0.0.1`:
its routes are not authenticated.

Two notes. The DSPy instruction optimizer used by some evaluations lives in a separate dependency
group: run `uv sync --group optimize` before you use it, and remember that a later plain `uv sync`
removes it again. And never edit the pinned renderer's `node_modules`: `npm ci` owns that tree.

## Configuration

`.env.example` documents every setting and is the file to keep current. The short version:

| Setting | Default | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | Enables the OpenRouter team. |
| `LITELLM_BASE_URL`, `LITELLM_TOKEN`, `LOCAL_LLM` | — | Enable the LiteLLM proxy team. |
| `PYDANTIC_AI_MODEL` | `openrouter:z-ai/glm-5.3` | The lead. |
| `PYDANTIC_AI_LEAD_REASONING_EFFORT` | `low` | The lead's thinking effort. |
| `PYDANTIC_AI_PROFILER_MODEL`, `PYDANTIC_AI_ANALYST_MODEL` | `openrouter:z-ai/glm-5.3` | Profiling and analysis. |
| `PYDANTIC_AI_DESIGNER_MODEL` | `openrouter:deepseek/deepseek-v4-pro` | Chart design. |
| `PYDANTIC_AI_REVIEWER_MODEL` | `openrouter:google/gemma-4-31b-it` | The visual inspector; must read images. |
| `PYDANTIC_AI_ADVISOR_MODEL` | unset | The optional Advisor capability, off unless set. |
| `DATA_DIRECTORY`, `DUCKDB_PATH`, `MAX_UPLOAD_MB` | `./data`, `./data/datasets.duckdb`, `20` | Local storage. |
| `LOG_LEVEL`, `LOGFIRE_TOKEN` | `INFO`, unset | Logging, and traces when a token is present. |

The chat's dropdown lists each provider that is configured, and selects the whole team. OpenRouter comes
first when both are configured, and the first team also serves the agent API. A lead override must support
tool calls but does not need image input: rendered images go only to the scoped visual inspector, and the
lead receives its findings instead of image bytes. An existing `.env` value always wins over the default.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `No provider is configured: set LITELLM_BASE_URL…` on startup | `.env` is missing or has no provider. Copy `.env.example` and set a key. |
| `doctor` says `Node is not installed` | Install Node 22 LTS or newer and open a new shell so `node` is on `PATH`. |
| `doctor` says `GPT-Vis SSR is not installed` | Run `npm ci --prefix vis_agent/render/gptvis`. |
| `doctor` says `fonts: Arabic text did not render` | Install the fonts. On Debian: `sudo apt install libexpat1 fontconfig fonts-noto-core`. |
| `401` or `No auth credentials` from the provider | The key in `.env` is empty or no longer valid. |
| `Address already in use` | Another copy is on port 7932. Stop it, or pass a different `--port`. |
| `IO Error: Could not set lock on file …duckdb` | DuckDB allows one writer. Close the database in your SQL client, or stop the other copy of the app. |
| The renderer breaks after an npm command | Restore the pinned tree with `npm ci --prefix vis_agent/render/gptvis`. |
| A chart request stops with a question | Exit code 3 means the lead is waiting on a presentation choice. Answer it with `resume` or the answer route. |

## Supply a CSV and brief

Upload through the chat or the upload API:

```bash
curl -F file=@regional_totals.csv \
  -F 'brief={"producer_agent":"data-agent","raw_question":"Compare regional sales","intent":"compare","units":{"amount":"SAR"}}' \
  http://127.0.0.1:7932/datasets/upload
```

The brief supplies intent, column descriptions, units, and presentation preferences. The CSV supplies
values. Uploads do not start a profiling model. Prepared totals, rates, dates, and identifiers remain
as supplied; the visualization team does not repeat the upstream data analysis or ask for missing data.

For coded categories, send `code_meanings` with the brief. Optional `display_labels.ar` or `.en` supplies
approved column and category labels used consistently across charts and displayed tables. See the
[data agent handoff contract](docs/data-agent-handoff.md) for an upload example and label precedence.

The direct path reads all rows, with a resource limit of 10,000 rows. Above that limit it reports a
technical limitation instead of silently sampling or aggregating. Geometry and oversized cell values
stay local. Hijri dates and leading-zero identifiers stay text. A lead-provided column annotation
can clarify meaning, units, or chart roles without changing the table's values.

## How the lead manages the team

| Tool | Responsibility |
| --- | --- |
| `draw` | Open a saved request and read the supplied table and brief. No specialist call. |
| `design_visualization` | Delegate chart design with the lead's domain guidance. |
| `render_visualization` | Render the saved spec when the lead chooses; reuse an existing preview. |
| `review_visualization` | Send the picture to the scoped visual inspector before publication. |
| `consult_analyst` | Perform an explicitly requested calculation or filter over existing data. |
| `publish_visualization` | Save the chosen preview as an artifact and return its picture and source table. |
| `revise` | Open a linked version, reusing the existing table by default. |
| `resume` | Inspect saved results and continue without rerunning completed work automatically. |
| `find_dataset`, `find_artifact` | Discover uploads or retrieve previous work. |
| `ask_user` | Pause for an essential presentation choice. |
| `profile_csv`, `answer_question` | Optional explicit file profiling or numbers-only requests. |

A routine prepared CSV needs one designer run. The designer can deliver a spec in one model response;
there is no mandatory recommendation/check dialogue. Syntax, existing bindings, renderer contracts,
and source preservation remain checked. Chart choice, aesthetics, review, repairs, and fallback selection
belong to the lead and specialists. Historical chart policy checks remain available to offline evaluation
and explicit `check`/`recommend` commands; they do not control runtime design.

Review returns advice to the lead. It never schedules another round. A specialist failure returns
diagnostics to the lead. It never automatically calls the analyst, fallback designer, or user.
A changed design invalidates its old render and review before external work begins, so a failure cannot
publish an obsolete preview. Publishing is idempotent for a saved request.

The implementation follows [Pydantic AI agent delegation](https://ai.pydantic.dev/multi-agent-applications/):
async tools await specialist runs, return control to the lead, share usage, and use framework usage limits.
Chat and API runs have a limit of 24 model requests and 16 tool calls. Saved API/CLI requests retain their
request usage across resumes. There is no workflow engine or fixed step dispatcher.

## Revise, resume, and retrieve

Ask for a title, color, layout, or chart type change. The lead reuses the table and produces a new artifact
version. For a requested data change, it may explicitly delegate a calculation to the analyst. The original
CSV stays unchanged. Every delivered result includes an artifact ID (`art_…`) and request ID (`rq_…`).

Say “continue” to resume unfinished work, or name its request ID. Ask “What did we make?” to retrieve saved
artifacts. Only a presentation choice that cannot reasonably be inferred should require a user answer.

```bash
uv run vis draw --upload regional_totals.csv --brief brief.json "Compare regional sales"
uv run vis revise ARTIFACT_ID "Use dark blue"
uv run vis resume REQUEST_ID
uv run vis requests --dataset DATASET_ID
uv run vis artifacts DATASET_ID
uv run vis chat
```

`ask` is the explicit numbers-only command. `profile` explicitly requests semantic file profiling.
`design`, `render`, `check`, and `recommend` remain available for standalone development/evaluation.
The `draw`, `revise`, and `resume` commands exit 0 on delivery, 3 when awaiting a presentation choice,
1 on failure, and 2 for invalid input.

## Agent API

Upload the CSV first, then use its dataset ID:

```bash
curl http://127.0.0.1:7932/requests -H 'Content-Type: application/json' \
  -d '{"dataset_id":"DATASET_ID","question":"Compare regional sales","caller":{"identity":"data-agent"}}'
```

| Route | Purpose |
| --- | --- |
| `POST /requests` | Start a chart request or revision; return HTTP 202 and its ID. |
| `GET /requests/{request_id}` | Read status and saved tool results. |
| `POST /requests/{request_id}/answer` | Submit `{"answer":"…"}` for a pending presentation choice. |
| `POST /requests/{request_id}/resume` | Continue through the same lead. |
| `GET /artifacts?dataset_id=DATASET_ID` | List artifacts. |
| `GET /artifacts/{artifact_id}` | Read a complete artifact, table, and lineage. |
| `POST /agents/ask` | Ask the lead using `question`, optional `dataset_id`, and `caller`. |

The optional `caller.return_address` receives one callback after a request run. Callback failures are
logged without retries; clients can poll. POST control routes require JSON. Keep this local application
on `127.0.0.1`: its routes are not authenticated. The same lead and tools serve chat, API, and CLI.

## Verification

```bash
uv run pytest -q
uv run python -m evals.designer.run
uv run python -m evals.designer.agent.run
uv run python -m evals.lead.run
```

Real-model evaluations need provider credentials and the renderer. `pytest` needs neither, but the
renderer tests skip themselves when the renderer is missing, so install it before trusting a green run. Historical
analyst/designer corpora also cover explicit calculation and the old policy checks. They are separate from
prepared-CSV fidelity and latency measurements. Two evaluations need files that are not in the repository:
`evals.lead.run --corpus` samples the development CSV corpus from a local path set in
`evals/designer/agent/corpus_tools/select.py`, and review evaluation needs the human-labelled pictures
built as [evals/reviewer/README.md](evals/reviewer/README.md) describes:

```bash
uv run python -m evals.reviewer.run
```

## Code map

| File | Responsibility |
| --- | --- |
| `vis_agent/lead.py` | Lead instructions and specialist delegation tools. |
| `vis_agent/providers.py` | Provider models, thinking settings, team wiring, chat usage limits. |
| `vis_agent/analyst/source.py` | Read the authoritative CSV without model calls or new measurements. |
| `vis_agent/requests/service.py` | Persistence, artifact publication, and API/CLI lead entry point. |
| `vis_agent/requests/store.py` | DuckDB request and artifact records. |
| `vis_agent/requests/runner.py` | Compatibility imports only; no runner. |
| `vis_agent/designer/` | Chart specialist, executable spec validation, rendering preparation. |
| `vis_agent/reviewer/` | Optional image review. |
| `vis_agent/analyst/` | Explicit calculations through read-only, validated DuckDB SELECTs. |
| `vis_agent/profiler/` | Optional semantic profiling and local measurements. |
| `vis_agent/render/` | Pinned GPT-Vis renderer and capability descriptions. |
| `vis_agent/app.py` | Stores, team, built-in web UI, upload and artifact routes. |

Earlier phase designs under `docs/superpowers/` record the previous architecture. The current design is
[lead-directed visualization](docs/lead-directed-team.md). `TemporalDurability` remains attached as a
capability; ordinary web runs do not use a Temporal worker.
