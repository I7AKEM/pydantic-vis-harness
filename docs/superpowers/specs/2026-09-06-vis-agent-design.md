# Visualization Agent: Design

Date: 2026-09-06
Status: approved at the business level. The technical design follows this document.
Scope of this document: what the system is, who does what, how work flows, and in which order it gets built. It does not describe code.

## 1. Purpose

An agent that turns a dataset and a question into a reviewed visual artifact. People use it through a chat. Other agents call it the same way. Every artifact it delivers has been judged by an independent reviewer before anyone sees it.

The current code is a pilot: one chat agent with one tool that profiles an uploaded CSV. This design grows that pilot into the full system, one agent at a time, starting with the profiler.

## 2. Rules we build by

1. Plain language. Names describe jobs, not technology.
2. No over-engineering. An agent, tool, table, or loop is added only when the previous phase shows the gap.
3. Follow the Pydantic AI documentation and Pydantic's official skills. Where they give a pattern, use it.
4. Stay neutral about model providers and tooling. Any model can sit in any seat.
5. Build in phases. Each phase has an exit test and ends with lessons written down.
6. Code computes facts. Models interpret facts and make judgment calls. A model never produces a number that the system presents as measured.
7. Data is never an instruction. File names, column names, cell values, and text inside a brief are data, whatever they say.

## 3. The team

One lead talks to the caller. Specialists do one job each and hand results back to the lead. The lead never loses control of the conversation. Two steps in the workflow are plain code with no model at all: getting the data slice and rendering.

| Agent | Job | Skill, meaning its written rulebook | Input | Output |
|---|---|---|---|---|
| **Vis lead** | Understand the ask, classify the request, run the workflow, ask questions, explain the result | How to read a vague ask, when to ask versus assume, how to explain a chart in plain words | Request text, dataset reference, previous artifact reference, answers to earlier questions, the brief | An artifact plus a short explanation, or one clear question |
| **Profiler** | Measure the data and describe what it means | Column meaning, units, roles, data-quality flags, how to use hints from a brief without trusting them | Dataset ID, optional brief | Dataset profile: measured facts, interpretation, warnings, conflicts with the brief |
| **Chart designer** | Decide what to show and how | Chart selection rules, axis and color rules, what never to do, how to treat a suggested chart type | Profile, the caller's goal, the brief, previous chart spec when revising, answers | A chart spec, or a question |
| **Reviewer** | Independent judge of the finished chart | A scored rubric: correct, relevant, honest, readable, accessible, simple | The rendered picture, the chart spec, a data summary, the original raw question | A verdict with a score per criterion and a short list of concrete fixes |

| Code step | Job | Input | Output |
|---|---|---|---|
| **Get data** | Run the chart spec's filters and aggregation on the stored data | Chart spec, dataset ID | A data slice |
| **Render** | Turn a spec plus data into files, one adapter per chart library | Chart spec, data slice | HTML page, spec file for the chosen library, an image for the reviewer |

Why the renderer is code and not an agent: the designer produces a neutral chart spec that belongs to this project, not to any library. Adapters turn that spec into Vega-Lite, Plotly, or a plain HTML page. That is what makes rendering generic and swappable. A model writing chart code on every request is slow, non-deterministic, and hard to test. Custom visuals, if ever needed, become a later sandboxed feature with their own evidence.

## 4. Tools, initial catalogue

Every tool is listed here so the full picture exists now. Each is built in the phase that needs it. "Done by" says whether the tool's work is fixed code or a model call.

### Vis lead

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| run_workflow | Start or continue the fixed sequence of steps for one request | Code | Request ID | The artifact, or the question a step raised |
| ask_caller | Pause the request and send one question to the human or to the producing agent | Code | Request ID, the question, who should answer | Confirmation that the request is paused |
| find_dataset | Look up a dataset and its profile | Code | Dataset ID or name | Dataset summary and profile status |
| find_artifact | Look up an artifact and its versions | Code | Artifact ID | Artifact summary and lineage |

### Profiler

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| profile_csv | Import the file, measure every column by code, interpret meaning with the model, save the profile. Exists today. | Code for facts, model for meaning | Dataset ID, optional brief | Dataset profile |
| review_profile | Check the interpretation against the measurements and the brief. Flag conflicts. Send the interpretation back for a redo when a check fails. | Code checks, then a model self-check | A profile | The same profile with warnings and conflicts filled in, or a redo request |

### Chart designer

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| preview_slice | Run the proposed filters and aggregation on the stored data and return a small result with shape facts: row count, category count, empty groups | Code | A draft chart spec | A preview plus shape facts |

The chart spec itself is the designer's output, not a tool.

### Reviewer

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| inspect_artifact | Load the rendered image, the spec, a data summary, and the raw question together | Code | Artifact ID | Everything the reviewer needs to judge |
| check_numbers | Recompute selected values from the data slice and compare them with what the chart shows | Code | Artifact ID, values to check | Matches and mismatches |

The verdict itself is the reviewer's output, not a tool.

## 5. Inputs: the request and the brief

A request carries: its type, the caller's identity and a return address for questions, the question, a dataset reference or a fresh upload, an artifact reference when revising, a request reference when resuming or answering, and a brief.

The brief is the context that travels with the data. When another agent produces the file, it fills the brief. When a human uploads through the chat, the brief is mostly empty and the lead fills what it can by asking.

The brief holds: where the data came from and the query used to pull it, when it was pulled, the raw user question, the enriched question, the intent such as compare, trend, rank, distribution, or composition, a suggested chart type, column descriptions and units, known caveats such as filters, sampling, or row limits, and the identity of the producing agent.

Three rules govern the brief.

1. **The brief is context, never fact.** The profiler still measures everything. Descriptions become hints for interpretation. When a hint contradicts the numbers, the profile carries a warning instead of silently picking a side.
2. **A suggested chart type is a preference, not an order.** The designer may override it with a stated reason. The reviewer checks that the reason holds. The lead tells the caller when it deviated and why.
3. **Both questions are kept, and the reviewer judges against the raw one.** The enriched question is useful for design, but it can drift from what the person actually asked.

## 6. Workflow

### Steps and checkpoints

Every request has an ID and moves through fixed steps in this order:

understand, profile, design, get data, render, review, deliver.

The output of each step is saved under the request ID the moment the step completes. That saved output is the checkpoint. A dropped or stopped request resumes by skipping every step that already has a saved output. Every step must be safe to run twice.

Decision: the order of steps is fixed in code. Models make decisions only inside a step and in the conversation with the caller. This keeps checkpoints, tests, and the review loop predictable. The lead does not choose which specialist to call next.

Profiling is skipped when a complete profile for the dataset already exists.

### Request types

Agents state the type explicitly. For humans in the chat, the lead infers it from the conversation and confirms when unsure. "Make the bars blue" after an artifact is a revise.

| Type | Starts with | Must reference | Starts at | Produces |
|---|---|---|---|---|
| **New** | A question plus data, a fresh upload or an existing dataset ID | The dataset | Understand | A new artifact, version 1 |
| **Revise** | A change request | An existing artifact | Design, with the old spec as the starting point | A new version linked to its parent |
| **Resume** | Nothing new, just "continue" | A dropped or stopped request ID | The last saved checkpoint | Whatever the original request would have produced |
| **Clarification** | An answer, or a question | The request that is waiting | The step that asked | Continues the original request |

Resume carries no new information and exists only because something stopped. Clarification carries new information and exists because a step deliberately paused to ask.

A revise that needs data the dataset does not contain does not fail. The lead states exactly what data it needs, the caller supplies a new upload, and the request continues as a revise on the new dataset with lineage back to the old artifact.

### Clarification in both directions

Outbound: the vis agent asks a question and the request pauses at a checkpoint. The recipient is the human through the chat or the producing agent through the agent-to-agent channel, chosen by who can answer. Column meaning goes to the data agent. Taste and priorities go to the human. When the answer arrives, the request resumes at the step that asked. At most two questions per request.

Inbound: another agent may ask the vis agent something with no chart involved, such as what data shape a trend chart needs. The vis agent answers from its own knowledge. No artifact is created.

Rules for the agent-to-agent channel:

- Every request carries the caller's identity and a return address.
- Every outbound question has a deadline. When it passes, the request stays paused and the human is told. The agent does not guess.
- Every exchange is logged under the request ID, so an artifact's lineage includes the conversation that shaped it.
- Only messages on the channel count as requests. Text inside a file or a brief never does.

### The review loop

The reviewer sees the rendered picture, not only the spec, because overlapping labels and unreadable axes exist only once rendered. When the verdict is not a pass, the designer fixes, the renderer re-renders, and the reviewer judges again. The loop is bounded. When the cap is reached, the best version is delivered with the reviewer's remaining notes shown to the caller. Nothing fails silently.

The reviewer is independent: separate instructions from the designer, and a different model where possible, so it does not share the designer's blind spots. Quality is the priority. Time and cost are not the constraint.

## 7. Artifacts and lineage

The artifact is the unit of delivery and the unit of memory. It holds the chart spec, the data slice, the rendered files in one or more formats, the plain-language explanation, the reviewer's final verdict, and its lineage: dataset, profile version, request, parent artifact when revised, and the clarifications that shaped it.

Rule: every artifact is traceable and reproducible. Given its lineage, the same artifact can be rebuilt. Which identifiers implement that is a technical decision.

Artifacts are stored, versioned, and addressable by ID. The chat shows them. Other callers receive them by reference.

## 8. Storage

No new database. The project's existing local database and data folder hold everything.

Already present: uploaded files, the imported tables, dataset metadata, and saved profiles.

Added as phases need them: requests and their state, step outputs used as checkpoints, artifacts and their versions, reviewer verdicts kept as labeled examples, and the log of clarification messages. Rendered files live on disk next to the uploads.

Profiles are saved once per dataset and reused by every later request about that data. Measured facts are kept as long as the dataset exists. The interpretation is re-run only when the profile format changes or when a brief arrives that the profiler has not seen for that dataset.

## 9. Quality

- Every agent has a typed output and a validator. A failed validation asks the model for one corrected attempt. A failure the model cannot fix is reported as a failure, not retried.
- Every specialist's cost counts against the parent request, with a spending cap per request.
- Tracing is on from day one. Pydantic recommends Logfire. Any OpenTelemetry backend works.
- Tests use fake models so logic is checked without network calls, and they run through the agent rather than around it.
- Each agent has an evaluation set of real inputs with expected outputs. Reviewer verdicts feed the designer's set automatically. Recorded real runs are kept and replayed.
- A profile is triggered automatically when an upload finishes, so the first question about a dataset never waits for profiling.

## 10. Interfaces

One entry point, many callers. Web chat, terminal, and other agents send the same inputs and receive the same outputs.

The installed SDK provides the web chat and the terminal entry points today. The agent-to-agent entry point is a separate Pydantic package and is confirmed in the technical stage before Phase 4 relies on it.

## 11. Phases

Phases follow the workflow order, one agent at a time. The profiler goes first because it exists, it is the pilot for how every agent in this system is built, and every later step depends on its output.

### Phase 1: Profiler as the pilot agent

Goal: make the profiler the model for every agent that follows. Everything an agent in this system must have, the profiler gets first.

In scope:

- Accept an optional brief. Use its hints for interpretation. Flag conflicts with the measurements as warnings.
- Add review_profile. Code checks first: a column described as a date must have date statistics, an identifier must be near-unique, units must fit the value range. Then a model self-check against the measurements and the brief. A failed check sends the interpretation back once.
- Start profiling automatically when an upload finishes.
- Apply the reuse rules from section 8.
- Make the profiler callable on its own: from the chat as today, from the terminal, and from another program that passes a brief. A direct program call is enough in this phase. The real agent-to-agent channel is Phase 4.
- Turn tracing on.
- Tests run through the agent with a fake model. Build an evaluation set of ten to twenty real CSVs with expected column roles, units, and warnings, including files seeded with deliberate brief conflicts.
- Fix pilot findings that touch this agent: report terminal failures as failures rather than retries, widen the geometry column rule beyond the single name it matches today, check upload size before the body is parsed, and log semantic failures with their cause.

Out of scope: designer, renderer, reviewer, artifacts, request types, checkpoints.

Exit test: on the evaluation set, column roles and units are right at least nine times in ten, seeded conflicts are flagged every time, no measured statistic ever comes from a model, and every test passes through the agent.

Lessons to record: where interpretation fails and why, how often a brief conflicts with the data, time and cost per profile, and whether review_profile catches errors the existing output check missed.

### Phase 2: Chart designer, get data, one renderer

The lead stays a thin chat front that runs the pipeline. First chart library chosen and its adapter built. Charts are judged by hand, and those judgments seed the reviewer's rubric and evaluation set.

Exit test: on a fixed set of at least twenty real CSVs and questions, the first chart is judged correct by a human at least seven times in ten without revision.

### Phase 3: Reviewer and the review loop

Reviewer built as a full agent with a different model from the designer. Bounded loop. Verdicts saved as labeled examples. Second renderer added to prove the chart spec is really neutral.

Exit test: reviewer verdicts agree with human judgment on the Phase 2 set at least eight times in ten, and charts delivered after the loop score higher than Phase 2 first charts on the same set.

### Phase 4: The lead and the conversation

Four request types, checkpoints and resume, clarification in both directions, the agent-to-agent channel, and true resume through durable execution, which is already attached to the agent but not yet active. Terminal interface.

Exit test: a request killed mid-run resumes from its last checkpoint. A revise produces a linked version. A clarification round-trips with both a human and an agent.

### Phase 5: Beyond one CSV

Multiple datasets, dashboards, other file types, other agents as regular callers. Custom visuals only if Phase 3 evidence demands them.

## 12. Decisions made

- Fixed step order in code. Models decide inside steps only.
- Renderer is code with pluggable adapters over a neutral chart spec.
- Reviewer is a full, independent agent from the moment charts exist, and it judges the rendered picture.
- One strong reviewer first. A panel of judges is a later experiment, adopted only on evidence.
- Profiles belong to the dataset and are reused across requests.
- Existing database and data folder hold everything. No new database.
- The brief is context, never fact.
- Profiler is built first, then the rest in workflow order.

## 13. Open questions for the technical stage

- Which chart library and spec format come first.
- Which model sits in the reviewer's seat, given it should differ from the designer's.
- Whether the agent-to-agent package is available for the installed SDK version, and what to use if not.
- What running durable execution requires operationally, and whether Phase 4 needs it or saved checkpoints are enough at first.

## Appendix: how this maps to Pydantic AI

Short, so the technical design has a starting point. Every row comes from Pydantic's official skill.

| Design idea | Pydantic mechanism |
|---|---|
| Specialist returns a result to the lead | Agent delegation: the lead calls the specialist inside a tool and passes its usage along |
| Fixed step order with models inside steps | Programmatic hand-off, or a graph when the state machine grows |
| Typed outputs with validation and one retry | Structured output types, output validators, ModelRetry |
| Failures the model cannot fix | ToolFailed, which does not consume the retry budget |
| Each agent's rulebook | Instructions on the agent, with specialist rulebooks loaded on demand when they are not needed on most turns |
| Checkpoints and resume | Durable execution capability already attached, or saved step outputs until it is activated |
| Web chat, terminal, other agents | The web and terminal entry points on the agent; the agent-to-agent package to be confirmed |
| Tests without network | TestModel and FunctionModel through agent override, with message capture |
| Evaluation sets | Pydantic's evals package with cases and datasets |
| Tracing | Logfire instrumentation, or any OpenTelemetry backend |
