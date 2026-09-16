# Visualization team

A Pydantic AI lead turns an upstream data agent's CSV into a chart using the question or intent in its brief.
The CSV is authoritative. The lead directs specialist tools and decides when the chart is ready.

## Run

Use Python 3.12, `uv`, and Node 22 LTS:

```bash
uv sync
npm ci --prefix vis_agent/render/gptvis
cp .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env`. The default lead is the multimodal model
`openrouter:z-ai/glm-5.3-flash`, with low reasoning effort and OpenRouter latency routing. It receives each
rendered chart as image input before deciding whether to repair, review, or publish it.
`PYDANTIC_AI_MODEL` and `PYDANTIC_AI_LEAD_REASONING_EFFORT` override these settings; a lead override must
support image input and tool calls.
An existing `.env` model override takes precedence over the default.

A LiteLLM team remains available through `LITELLM_BASE_URL`, `LITELLM_TOKEN`, and `LOCAL_LLM`.
When both providers are configured, OpenRouter is selected first and serves the agent API.
The chat dropdown selects the whole team. Each role has its own model configuration in `.env.example`.
The optional Advisor capability is enabled only when `PYDANTIC_AI_ADVISOR_MODEL` is set.

```bash
uv run python -m vis_agent.cli doctor
uv run uvicorn vis_agent.app:app --host 127.0.0.1 --port 7932 --reload
```

Open [the chat](http://127.0.0.1:7932). The app uses Pydantic AI's built-in Web Chat UI.
On Debian, the renderer also needs `libexpat1`, `fontconfig`, and `fonts-noto-core`.
Do not edit the pinned renderer's `node_modules`.

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
| `review_visualization` | Ask the reviewer to inspect the picture when the lead chooses. |
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
uv run python -m vis_agent.cli draw --upload regional_totals.csv --brief brief.json "Compare regional sales"
uv run python -m vis_agent.cli revise ARTIFACT_ID "Use dark blue"
uv run python -m vis_agent.cli resume REQUEST_ID
uv run python -m vis_agent.cli requests --dataset DATASET_ID
uv run python -m vis_agent.cli artifacts DATASET_ID
uv run python -m vis_agent.cli chat
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

Real-model evaluations need provider credentials and the renderer. Historical analyst/designer corpora
also cover explicit calculation and the old policy checks. They are separate from prepared-CSV fidelity
and latency measurements. Review evaluation needs the human-labelled set:

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
