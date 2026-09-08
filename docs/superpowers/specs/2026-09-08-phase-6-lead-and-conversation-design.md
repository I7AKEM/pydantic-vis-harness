# Phase 6: The lead and the conversation

Date: 2026-09-08. Follows the Phase 1 design (docs/superpowers/specs/2026-09-06-vis-agent-design.md, sections 9
to 12 and 14, and Phase 6 in section 16), the Phase 4 designer, and the Phase 4b lessons. Phase 6 runs
before Phase 5 (the reviewer): everything the owner disliked in the web chat during Phase 4b was the lead's
conversation, not chart quality, and the reviewer can only improve charts that get drawn.

## 1. Purpose

Make the lead a conversation partner that draws by default, keeps every piece of work as a request with
saved checkpoints, revises a chart into a linked new version, resumes a dropped request, asks one question
and continues when it is answered, and takes the same requests from a human in the chat, a person in the
terminal, or another program over HTTP.

## 2. Scope

In scope:

- A request record with a fixed sequence of steps: understand, profile, analyze, design, render, review,
  deliver. Each step's output is saved the moment the step completes; that saved output is the checkpoint.
- The request types of the Phase 1 design: new, revise, resume, clarification. A resume carries nothing new;
  a clarification carries an answer.
- The artifact: the unit of delivery and memory, with its lineage and its versions.
- Clarification in both directions: outbound to the human or the calling program, inbound answers, and
  inbound questions from a program with no chart involved.
- The agent channel: a JSON API on the existing app for programs, with a return address for callbacks.
- The lead's tools and instructions: chart first, revise, resume, find artifacts, suggest questions.
- Terminal commands for every request type.
- Durable execution by saved step outputs, the Phase 1 appendix's fallback, with the Temporal capability
  left attached and inactive.
- A lead evaluation set: scripted conversations plus corpus questions through the lead.

Out of scope: the reviewer and the review loop (Phase 5; the review step exists and records "not
reviewed"), a second renderer, maps, dashboards, multiple datasets in one request, an external A2A
package, a workflow engine, changes to the chat page or the upload control, and any change to how the
analyst writes SQL or the designer chooses charts beyond the two inputs in section 11.

## 3. The request

A request is one piece of work about one dataset. Its record is saved in the existing DuckDB database
under a `rq_` ID and holds:

| Field | Meaning |
|---|---|
| `type` | `new` or `revise` |
| `dataset_id`, `question` | the dataset and the raw question; for a revision, `question` is the change asked for |
| `parent_artifact_id`, `redo_analysis` | for a revision: the artifact being revised, and whether the data must change |
| `caller` | who asked: `chat` with the conversation ID, `terminal`, or `agent` with an identity and an optional return address |
| `language` | the caller's language, detected once in the understand step |
| `status` | `running`, `waiting`, `done`, `failed`, `stopped` |
| `steps` | the saved output of every completed step, keyed by step name: the checkpoints |
| `clarifications` | every question the request asked, with the answer when it arrived |
| `artifact_id` | the delivered artifact |
| `error` | why the request failed, in plain words |

Resume and clarification are not types. They are operations on an existing request: continue it, or answer
its pending question and continue it. The Phase 1 table's "Starts at" column becomes the rule for which
step runs next: the first step with no saved output, or the step that asked.

## 4. Steps and checkpoints

`run_request` is code. It loads the request, runs the steps in fixed order, saves each step's output under
the request ID as soon as the step completes, and returns an outcome: the artifact, the question the
request is waiting on, or the failure. Models decide only inside the analyze and design steps.

| Step | Does | Saves | Skipped when |
|---|---|---|---|
| understand | Detects the language; for a revision, loads the parent artifact and copies its dataset and raw question | language, dataset, parent | never |
| profile | `profile_dataset`, which already returns a complete saved profile without a model call | profile status, created_at, brief fingerprint | a complete profile exists (inside `profile_dataset`) |
| analyze | The analyst, through `analyze_dataset`, with the request's clarifications and, for a revision with `redo_analysis`, the parent's SQL and columns and the change | the AnalysisReport | a revision without `redo_analysis`: the parent's report is copied as the step output |
| design | The designer, through `design_chart`, with the clarifications and, for a revision, the parent's spec and the change | the DesignReport | the result is a single number (one row, one measure): saved as skipped with the reason |
| render | `render_design` into `data/renders/<render_id>` | the Rendered files, the render ID and URLs | design was skipped or the renderer is unavailable (saved as skipped with the reason; the artifact then holds the table) |
| review | Nothing in this phase | `{"status": "not_reviewed", "reason": "Phase 5 adds the reviewer"}` | never |
| deliver | Writes the artifact and marks the request done | the artifact ID | never |

Every step is safe to run twice: profiling returns the saved profile, the analyst and designer are rerun
only when their step has no saved output, rendering is deterministic from the spec and the report, and
delivering an artifact twice for one request returns the same artifact.

A step that returns a clarification does not save an output. The request's status becomes `waiting`, the
question is appended to `clarifications` with the step that asked and a deadline, and the outcome carries
the question. A request may ask at most two questions; a third ends the request as `failed` with the
question as the reason, so the caller sees why.

A run killed from outside leaves the request `running` with the steps that completed; a step that raises
leaves it `failed` with the reason. Resuming treats both alike and skips the saved steps. A standalone run's
budget of model requests is counted on the request itself, so it holds across pauses and resumes.

## 5. Resume

`resume(request_id)` continues a request at the first step with no saved output. It works on `running`
(the process died), `waiting` (only with an answer, section 7), `failed` (the failure is cleared and the
step retried once more), and `stopped` requests. A `done` request is returned as is. A request that is
being run by this process right now is reported as still running, not run twice: the runner holds one
in-process lock per request ID.

In the chat, "continue" with no ID means the newest unfinished request of the same conversation. The
lead's `resume` tool takes an optional ID for that reason.

## 6. Revise

A revision is a `revise` request that names the artifact to change and states the change. The lead decides
whether the data must change (`redo_analysis`): a new filter, measure, grouping, period, or sort of the
numbers means yes; a title, colour, chart type, label, or layout change means no. The analyst gets the
parent's SQL and result columns plus the change when it reruns; the designer always gets the parent's spec
plus the change. The delivered artifact is version `parent.version + 1` with `parent_artifact_id` set, and
carries the change alongside the raw question of the lineage root.

## 7. Clarification in both directions

Outbound: when the analyst or the designer asks, the request pauses as described in section 4. Who answers
depends on the caller. A chat caller sees the question from the lead and answers in the next message; the
lead calls `resume(request_id, answer)`. A terminal caller runs `vis resume REQUEST --answer "..."`. A
program that gave a return address receives the question there and posts the answer to
`/requests/{id}/answer`; one without a return address polls `/requests/{id}`.

The answer is recorded on the pending clarification with who answered, and the request continues at the
step that asked. That step's specialist receives every question and answer of the request so far, as a
short list, and never a rewritten question: the raw question stays the raw question.

Every question carries a deadline, twenty-four hours by default. After it the request stays `waiting`; the
status shows `overdue`, and the lead says so when it finds such a request in a conversation.

Inbound: a program may ask the lead a question through `/agents/ask`. The lead answers from what it knows
and its tools, once, under the same cap as a channel request; a question that asks for a chart is drawn and
recorded as that program's request.

## 8. The agent channel

Plain JSON over HTTP on the existing Starlette app, next to the upload routes. No new package: the A2A
implementation that once lived in Pydantic AI moved to a separate project maintained elsewhere, so the
Phase 1 open question is closed by not adopting it.

| Route | Purpose |
|---|---|
| `POST /requests` | Create and start a request: `type`, `dataset_id`, `question`, `parent_artifact_id`, `redo_analysis`, `caller` (`identity`, `return_address`), `deadline_seconds`. Returns 202 with the request ID; the request runs in the background |
| `GET /requests/{id}` | The request record: status, pending question and whether it is overdue, completed steps, artifact ID, error |
| `POST /requests/{id}/answer` | Record the answer and continue in the background; 202 |
| `POST /requests/{id}/resume` | Continue a dropped or failed request in the background; 202 |
| `GET /artifacts/{id}` | The artifact with its report, design, render URLs, lineage, and clarifications |
| `GET /artifacts?dataset_id=` | Artifact summaries for a dataset, newest first, with versions and parents |
| `POST /agents/ask` | An inbound question: `question`, optional `dataset_id`, `caller`. Runs the lead once and returns its answer |

Rules, from the Phase 1 design: every request carries the caller's identity; a return address must be an
`http` or `https` URL; when a request reaches `waiting`, `done`, or `failed`, the app posts the request
record to the return address once, with a ten-second timeout, and logs a failure without retrying; every
exchange is stored on the request; POST bodies must carry `Content-Type: application/json`, the same
control the built-in chat endpoint uses, so a page in a browser cannot start a request.

## 9. Artifacts and lineage

An artifact is saved under an `art_` ID and holds: the request ID, the dataset ID, the version number and
the parent artifact, the raw question of its lineage root and the change that produced this version, the
analysis report (SQL, result columns, result table, summary, assumptions, checks), the design (spec, chart
type, explanation, compromises) when there is one and otherwise the reason there is no chart, the render ID
and the PNG and HTML URLs, the review (empty until Phase 5), the clarifications that shaped it, and the
lineage: the profile's creation time and brief fingerprint, the catalogue and rules versions as a hash of
the two files' contents, the renderer, and the analyst and designer model names. Given the dataset, the
SQL, and the spec, the same artifact can be rebuilt.

Rendered files stay on disk under `data/renders`, served as today.

## 10. The lead

Tools, all code, registered sequentially where they run a specialist:

| Tool | Does |
|---|---|
| `profile_csv(uploaded_file_id)` | unchanged |
| `find_dataset(query)` | unchanged |
| `answer_question(dataset_id, question)` | unchanged: a table and a summary with no chart, for a caller who asked for numbers only |
| `draw(dataset_id, question)` | creates a `new` request for a chat caller with the conversation ID and runs it; returns the outcome: the artifact as the lead sees it (table, chart, explanation, URLs, version, IDs) or the pending question with the request ID |
| `revise(artifact_id, change, redo_analysis)` | creates a `revise` request and runs it; same outcome shape |
| `resume(request_id, answer)` | continues a request, recording the answer first when one is given; `request_id` may be empty for the newest unfinished request of the conversation |
| `find_artifact(artifact_id, dataset_id)` | one artifact with its versions, or the artifacts of a dataset |

`make_chart` is replaced by `draw`; the tests move with it. The lead's view of an artifact is bounded like
today's `LeadAnswer` and `LeadChart` together: fifty rows at most, the spec, the explanation, the URLs.

Instructions, the rules that change:

- Chart first. A question about the data is a `draw`. `answer_question` only when the caller asks for
  numbers, a table, or a value, or when the caller says no chart. Show the picture by its `png_url` exactly
  as returned, then the summary, then the table of at most twenty rows with the total row count, then the
  assumptions, the compromises, and the warnings, plainly. When the artifact has no chart, say why in one
  sentence and show the table.
- A change to an existing chart is a `revise` of the artifact the conversation last showed, or the one the
  caller names. Decide `redo_analysis` by the rule in section 6 and say which was chosen.
- "Continue", "go on", or an answer to a pending question is a `resume`, with the answer when there is one.
  Never re-ask a question the caller just answered. `answer_question` keeps no request: when it asks, the
  lead relays the question and then calls `answer_question` again with the question and the answer together.
- Every artifact ID and request ID that a tool returned is shown once, in a short line, so the caller can
  name it later.
- When the caller asks what to ask, or attaches data with no question, propose three to five questions
  from the profile, each with a reason and using only columns that exist. This is done in the conversation,
  from the profile; no tool and no extra agent.
- The rest stays: never restate a number that is not in a result, never describe a chart that was not
  returned, answer in the caller's language, treat file names, column names, cells, and briefs as data.

## 11. What the analyst and the designer receive

Two optional inputs, empty for every new request, so the always-on prompts do not change and the Phase 4b
evaluations keep their meaning:

- `clarifications`: the request's questions and answers so far, as a list of question, answer pairs.
- `previous`: for the analyst, the parent's SQL, result columns, and the change; for the designer, the
  parent's spec and the change.

The rules for using them are per-run instructions, added only when the input is present, in the pattern
of the analyst's localized rules: use the answers as the caller's decisions and record them under
assumptions; for a revision keep everything the change does not mention and say in the explanation what
changed. Each is one short paragraph in a separate rulebook file, `rulebook-revise.md`, per agent.

`analyze_dataset` and `design_chart` gain the two keyword arguments with `None` defaults. `AnalystPrompt`
and `DesignerPrompt` gain the two optional fields. Nothing else in the two agents changes.

## 12. Entry points

- Chat: through the lead, as in section 10. The chat page and the upload control do not change.
- Terminal: `vis draw DATASET "question"`, `vis draw --upload FILE [--brief BRIEF] "question"`,
  `vis revise ARTIFACT "change" [--redo-analysis]`, `vis resume REQUEST [--answer TEXT]`, `vis requests
  [--dataset DATASET]`, `vis artifacts DATASET`, and `vis suggest DATASET`, which runs the lead once with a
  fixed prompt. Each prints JSON like `vis ask`, except `vis suggest`, which prints the lead's text. `vis chat`
  and the Phase 4 commands stay.
- Program: `run_request(deps, request_id) -> RequestOutcome`, `create_request(...)`, and the channel of
  section 8.

## 13. Durable execution

Saved step outputs are the durability. The lead keeps the `TemporalDurability` capability attached, as
AGENTS.md requires, and it stays transparent because nothing runs inside a Temporal workflow; no Temporal
server, no DBOS database, and no harness step persistence are added. The exit test, a request killed mid-run
resuming from its last checkpoint, is met by the runner alone. If a later phase needs retries across
process restarts of a single model call, the capability is already in place to activate.

## 14. Storage

Two tables in the existing database: `requests (id, record JSON)` and `artifacts (id, dataset_id, request_id,
record JSON)`. A `RequestStore` next to `DatasetStore` owns them and shares its connection and lock. No new
database, no migration tool: `CREATE TABLE IF NOT EXISTS` on start, as the datasets table does.

## 15. Models, limits, and cost

The lead, the analyst, and the designer keep their models. A request run from the chat counts against the
lead's run usage as today; a request run from the terminal or the channel gets its own usage with a cap of
forty model requests. The per-step timeouts stay. Two questions per request, section 4.

## 16. Tests

Through the agents with fake models, never around them, as in every phase:

- The runner: each step's output is saved when the step completes; a step that raises leaves the earlier
  steps saved; resuming does not rerun a saved step (the analyst's fake model counts its calls); a single
  number skips the designer; a renderer failure delivers the table; delivering twice returns one artifact.
- Clarification: a fake analyst that asks pauses the request with the question and the deadline; resuming
  with an answer passes the pair to the analyst's prompt and delivers; a third question fails the request.
- Revise: version two links to version one; without `redo_analysis` the analyst is not called and the
  designer receives the parent's spec and the change; with it the analyst receives the parent's SQL.
- The channel: `POST /requests` returns 202 and runs; the test app hosts the return address and records
  both callbacks, the question and then the artifact; the wrong content type is refused; a non-HTTP return
  address is refused.
- The lead: the seven tools are exposed; `draw`, `revise`, and `resume` are driven through the agent with
  `FunctionModel`, including the chat caller's conversation ID reaching the request record.
- The terminal: every new command prints JSON and exits zero, with the runner stubbed.
- The existing analyst and designer tests stay green with the two optional inputs absent.

## 17. The evaluation set and the exit test

The lead evaluation holds twenty-one cases: eleven scripted conversations in `evals/lead/cases.json` over
CSVs already in the repository, and ten corpus questions the runner adds with `--corpus`. A scripted case lists the messages
in the order the web chat would send them (the upload line included), the expected tool per message
(`draw`, `answer_question`, `revise` with the expected `redo_analysis`, `resume`), and the expected
outcome (an artifact, a table, a question). The corpus ten are the Phase 4b lead sample's questions over
result-table exports, so a corpus turn counts when the lead draws, asks, or answers with a table. The scripted
eleven are: numbers only, a chart then a colour change, a chart then a new filter, a question about a column the
file lacks that the analyst must ask about and then the answer, a vague term the analyst may ask about or state
an assumption for, "continue", a dataset with no question, an Arabic revision, a table then a chart, and artifact
recall. `evals/lead/run.py` runs them with real models and scores the tool choice and the outcome per turn and
per case.

Exit test, from the Phase 1 design plus the tool choice: a request killed mid-run resumes from its last
checkpoint; a revise produces a linked version; a clarification round-trips with a human in the chat and
with a program over the channel; and on the twenty-one cases the lead picks the expected tool in at least
eighteen cases.

## 18. Files

- New: `vis_agent/requests/__init__.py`, `models.py`, `store.py`, `runner.py`, `api.py`,
  `vis_agent/analyst/rulebook-revise.md`, `vis_agent/designer/rulebook-revise.md`, `tests/requests/`,
  `evals/lead/`, `docs/phase-6-lessons.md`.
- Changed: `vis_agent/lead.py`, `vis_agent/deps.py`, `vis_agent/app.py`, `vis_agent/cli.py`,
  `vis_agent/analyst/agent.py`, `vis_agent/designer/agent.py`, `tests/test_agents.py`, `tests/test_cli.py`,
  `README.md`, `AGENTS.md`.

## 19. Decisions taken before the plan

- The request runner is code with a fixed step order; the review step exists now and does nothing.
- Checkpoints are saved step outputs in the existing database. No workflow engine.
- The agent channel is JSON over HTTP on the existing app with a one-shot callback. The external A2A
  package is not adopted.
- Chart first: `draw` returns the table with the chart, so the numbers are never lost by drawing.
- The lead decides `redo_analysis` for a revision; the specialists receive the parent's work and the
  change as optional inputs with per-run rules.
- Question suggestions are a lead instruction from the profile, not a tool and not an agent.
- A single-number result skips the designer; a renderer failure delivers the table.
- Two questions per request, twenty-four-hour deadlines, overdue reported and never auto-resolved.
- `make_chart` becomes `draw`.

## 20. Lessons to record

Where the lead picks the wrong tool and why; how often revisions need the analyst; how many requests ask,
and whether the answers reach the specialist usefully; what a killed run looks like in the record; the cost
of a request through the channel against the chat; what the reviewer will need from the artifact.

## 21. Effort

Seven implementation tasks for Codex in three waves, plus the evaluation run and the web chat check by the
controller. Roughly the "10 to 15 days" of the Phase 1 estimate minus the engine and package work that
sections 8 and 13 decline.

## Appendix: how this maps to Pydantic AI

| Design idea | Pydantic mechanism |
|---|---|
| Fixed steps with models inside | Programmatic hand-off: code calls `analyze_dataset` and `design_chart`, each an agent run, in order |
| Specialist cost counted against the caller | `usage=ctx.usage` from the lead's `RunContext`; `UsageLimits(request_limit=...)` for standalone runs |
| Conversation identity for chat callers | `RunContext.conversation_id`, set by the web chat's adapter from the chat ID |
| Per-run rules only when an input is present | `@agent.instructions` functions on the analyst and the designer |
| Pausing and answering | The request record and its store; the pause is a tool result the lead relays, because the bundled chat can approve or deny a tool call but cannot take a free-text answer |
| Durability | Saved step outputs; `TemporalDurability` attached and inactive |
| Chat, terminal, program | `Agent.to_web`, `Agent.to_cli_sync`, and Starlette routes on the same app |
| Tests without network | `FunctionModel` and `TestModel` through `agent.override` |
