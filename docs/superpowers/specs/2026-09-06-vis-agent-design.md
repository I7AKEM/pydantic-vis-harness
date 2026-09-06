# Visualization Agent: Design

Date: 2026-09-06
Status: draft for approval. Revised after studying AntV AVA and surveying rendering libraries.
Scope of this document: what the system is, who does what, how work flows, how the chart designer actually works, and in which order it gets built. It does not describe code.

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
8. Knowledge lives in data and code, not in a model's memory. What charts exist, what data each needs, and what makes a chart bad are written down where they can be tested and versioned.

## 3. The team

One lead talks to the caller. Specialists do one job each and hand results back to the lead. The lead never loses control of the conversation. Two steps in the workflow are plain code with no model at all: getting the data slice and rendering.

| Agent | Job | Skill, meaning its written rulebook | Input | Output |
|---|---|---|---|---|
| **Vis lead** | Understand the ask, classify the request, run the workflow, ask questions, explain the result | How to read a vague ask, when to ask versus assume, how to explain a chart in plain words | Request text, dataset reference, previous artifact reference, answers to earlier questions, the brief | An artifact plus a short explanation, or one clear question |
| **Profiler** | Measure the data and describe what it means | Column meaning, units, roles, measurement levels, geography, data-quality flags, how to use hints from a brief without trusting them | Dataset ID, optional brief | Dataset profile: measured facts, interpretation, warnings, conflicts with the brief |
| **Chart designer** | Decide what to show and how, within what the catalogue and rules allow | Reading intent, choosing among candidates, assigning columns to visual roles, titles, labels, annotations, color intent, repairing a failed check | Profile, the caller's goal, the brief, ranked chart candidates, previous chart spec when revising, answers | A chart spec that passed the check, or a question |
| **Reviewer** | Independent judge of the finished chart | A scored rubric: correct, relevant, honest, readable, accessible, simple | The rendered picture, the chart spec, a data summary, the original raw question, the list of known rendering compromises | A verdict with a score per criterion and a short list of concrete fixes |
| **Insight finder** (later phase) | Find what is interesting in the data before anyone asks | Which findings deserve an annotation or a sentence, which are noise | Profile, data slice | Ranked findings, each with the evidence and a suggested annotation |

| Code step | Job | Input | Output |
|---|---|---|---|
| **Get data** | Run the chart spec's filters, grouping, binning, and aggregation on the stored data | Chart spec, dataset ID | A data slice |
| **Render** | Turn a spec plus data into files, one renderer per chart library | Chart spec, data slice | HTML page, spec file for the chosen library, an image for the reviewer |

Why the renderer is code and not an agent: the designer produces a neutral chart spec that belongs to this project, not to any library. One renderer per library turns that spec into the library's own format. That is what makes rendering generic and swappable. A model writing chart code on every request is slow, non-deterministic, and hard to test. AVA's own history confirms this the hard way: its spec was tied to one library, and as a result 33 of its 52 catalogued chart types never got a renderer.

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
| recommend_charts | Match the profile and the intent against the chart catalogue, apply the rules, return ranked candidates with the reason for each score | Code | Profile, intent, chosen columns | Ranked candidates with reasons, or "no chart fits, use a table or a single number" |
| preview_slice | Run the proposed filters and aggregation on the stored data and return a small result with shape facts: row count, category count, empty groups, value range | Code | A draft chart spec | A preview plus shape facts |
| check_spec | Check a draft spec against the rules and against what the chosen renderer supports. Return violations, each with a suggested fix, and the list of compromises the renderer will make | Code | A draft chart spec, renderer name | Pass, or violations with fixes |

The chart spec itself is the designer's output, not a tool.

### Reviewer

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| inspect_artifact | Load the rendered image, the spec, a data summary, the raw question, and the known rendering compromises together | Code | Artifact ID | Everything the reviewer needs to judge |
| check_numbers | Recompute selected values from the data slice and compare them with what the chart shows | Code | Artifact ID, values to check | Matches and mismatches |

The verdict itself is the reviewer's output, not a tool.

### Insight finder, later phase

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| find_patterns | Run fixed statistical tests: trend, change point, outlier, majority, low variance, correlation. Score and rank them | Code | Data slice | Ranked findings with evidence |

The narrative and the choice of what to annotate are the model's output, not a tool.

## 5. How the chart designer works

This is the hardest step in the workflow, and the model is the smallest part of it. The designer does not know how to render anything. Knowledge lives in four places that are data or code, and the model works only with what those give it.

### 5.1 The chart catalogue

A list of chart types written as data, not code. Each entry says: the chart's name and aliases, its family, what it is for using a fixed vocabulary such as comparison, trend, distribution, rank, proportion, composition, relation, spatial, and anomaly, what data it needs expressed as how many columns of which measurement level, which visual channels it uses, and a rating: recommended, use with caution, not recommended. Pie charts are "use with caution" in the catalogue itself, as an editorial stance, not a runtime decision.

The catalogue is both the designer's reference and the checker's rulebook. It versions on its own. It starts with the charts the first renderer can draw, roughly twenty, and grows only as renderers grow.

Measurement levels are the trick that makes matching work. Every column in the profile carries one or more of: nominal, ordinal, interval, discrete, continuous, time, geographic. A column can wear several labels at once. An integer column is both interval and discrete. A catalogue entry that needs "one time or ordinal column and one interval column" is matched by counting how many profile columns satisfy each requirement. This is why the profiler must produce measurement levels in Phase 1.

### 5.2 The chart spec

Our own neutral description of a chart. It is the designer's output, the checker's input, and what every renderer reads. It belongs to no library. It must be able to say:

- Chart type from the catalogue, and which column goes to which visual role: position, color, size, shape, facet.
- Transforms done by code before rendering: filter, group, aggregate, bin, sort, top-N with "Other", pivot from wide to long.
- Scales: linear or log, zero baseline forced or not, independent axes when there are two.
- Axes and legend: shown or hidden, title, number and date format, tick density, label rotation or wrapping.
- Data labels: on or off, which values, format.
- Annotations: reference line, band, point callout, text note. Each in data coordinates or as a fraction of the plot, with a label. The renderer converts.
- Color as a rule, never as a list of rendered colors: one constant color, a palette by column with categorical, sequential, or diverging intent, or emphasis on specific marks with the rest muted. Brand colors from the brief override the palette.
- Theme, size, aspect ratio, light or dark.
- Accessibility: description text, colorblind-safe requirement.
- A map branch, used only when a geographic column exists: choropleth over static boundaries, or points on a base map, with the region or coordinate columns named.
- Interaction hints such as tooltips, kept out of the render-critical path because they are invisible in the reviewer's picture.

### 5.3 The rules

Small pure functions, each with an ID, a type, a human explanation, and a suggested fix. Three types:

- **Hard rules** filter. A chart that fails one is out. Examples: the data does not satisfy the chart's requirements, a column would be silently dropped, a stated purpose is not in the chart's purpose set.
- **Soft rules** score. Examples: pie and donut need two to six slices and slices should be unequal, bars with more than twenty categories lose points, line and area strongly prefer a time or ordinal column on the horizontal axis, a second categorical column loses points as its cardinality grows unless the chart is a heatmap.
- **Design rules** fix. They run on a draft spec and return a patch. Examples: never truncate a bar's value axis, allow a non-zero baseline on a line chart only when the value range is narrow and say so in a note, hide data labels when there are too many marks.

Scores are bounded and additive so they can be explained and tuned. Every scored candidate keeps the per-rule breakdown. That breakdown is what the designer sees, what the explanation to the caller is built from, and what the evaluation set measures.

### 5.4 The renderers and what each supports

One renderer per library, in code, tested with fixed specs and reference images. Each renderer declares what it supports: facets, dual axis, log scale, annotation bands, emphasis colors, sorting, number formats, maps. Before rendering, check_spec resolves every feature the spec uses to one of three outcomes: supported, degraded with a documented fallback such as facets composited into a grid, or rejected with a message the designer can act on. The list of degradations travels with the artifact to the reviewer, so the reviewer does not penalize the chart for a compromise the designer never chose.

### 5.5 The model's job

Everything the code cannot do, and nothing else.

1. Read the intent from the raw question, the enriched question, and the brief: what is being compared, over what, filtered how, and what the caller wants to feel from the chart. Turn it into the fixed purpose vocabulary plus the columns involved.
2. Call recommend_charts and choose among the top candidates. Rules cannot tell a grouped bar from a stacked bar when both score well. Only a model reads column names and knows that "region" groups and "cost type" stacks.
3. Assign columns to visual roles when several columns satisfy the same requirement.
4. Write the title, subtitle, axis titles, units, and annotation text. Decide sort direction and ordering.
5. Choose color intent: which column drives color, whether one mark is emphasized, whether the brief's brand colors apply.
6. Run check_spec and preview_slice. Repair once when they report violations. Hand over only a spec that passed.
7. Explain the choice in two sentences the lead can pass to the caller, including why a suggested chart type was overridden.

### 5.6 What AVA taught us, and what we chose differently

AVA, AntV's visual analytics framework, is the strongest open example of this design: a catalogue of 52 chart types as data, four hard rules, seven soft rules, two design rules, a check step that runs the rules on an existing spec and returns patches, and a separate insight module. We copy the catalogue, the measurement levels, the rules split, and the check-before-render step.

Two things we do differently. AVA multiplied scores with bonuses up to ten times, which made rankings impossible to explain. We keep scores bounded and additive. AVA tied its spec to one library. We keep a neutral spec.

One thing to know. In 2026 AntV rewrote AVA around a language model: the catalogue became prompt text, the rules became bullet points, and the check step disappeared. That is a legitimate choice for a chat toy. It is the wrong choice for a system whose promise is a reviewed chart, because the check step is the safety net. We keep the catalogue as data used in both the prompt and the code, and we keep the check.

AntV's newer chart server takes a third approach: one tool per chart type, where the tool's input schema carries the data contract and the model chooses a chart by choosing a tool. It is a clean fit for the Pydantic tool model. We do not adopt it, because a single spec with a chart-type field and validators gives the same guarantee with one schema, and cross-chart scoring needs all candidates in one place. It remains an option if the catalogue grows past what one schema can carry.

## 6. Rendering targets

The reviewer must see a picture. That makes "can this library draw an image on a server without a browser" the deciding question, ahead of feature lists.

| Library | Image without a browser | License | Verdict |
|---|---|---|---|
| Vega-Lite | Yes, one Python package, no browser, no JavaScript runtime | Open | **First renderer** |
| Plotly | Yes, needs a bundled headless Chrome | Open | **Second renderer**, covers 3D, sankey, candlestick, gauges |
| MapLibre | Yes, native package or headless browser | Open | **Map renderer** when a base map is needed |
| AntV G2 | Official server-side package exists but is at version zero with a native dependency and very few users; upstream has slowed | Open | Later, optional |
| ApexCharts | Yes, official server-side rendering, recent | Commercial since mid-2025: free only under a revenue threshold, paid above it, and faceting is a paid feature | Later, optional, subject to license review |
| Mapbox | Static image service renders only styles published in their studio, not arbitrary specs; usage is billed per map load | Proprietary | Not used. MapLibre is the open equivalent |

Two facts worth knowing about maps. A choropleth over static boundaries needs no map service at all: Vega-Lite draws it from boundary files on the first renderer. A tiled base map is needed only for zoomable context, points over streets, or dense heat layers. So the map branch starts on the first renderer and moves to MapLibre only when a base map is needed.

Features that resist neutral expression, and how the spec handles them: annotations use different coordinate conventions in every library, so the spec carries data coordinates and each renderer converts. Per-mark colors are an explicit list in one library, a scale in another, and a flag in a third, so the spec carries a color rule and never a color list. Number formats are declarative everywhere except ApexCharts, so the spec carries a format string and the ApexCharts renderer, if built, pre-formats values in code. Faceting is native in two libraries, synthesized in one, and paid in another, hence the degradation list.

## 7. Edge cases the designer must handle

Each of these is a rule, a design fix, a transform, or a profiler flag. None is left to the model's judgment alone.

**Categories**
- More than about twenty categories on a bar: sort and keep the top N with "Other", or switch to a table.
- Pie or donut with more than six slices, or slices too close in size: use a sorted bar instead.
- A second categorical column with high cardinality: heatmap, facets, or top N. Never dozens of colors.
- Long category labels: horizontal bars, wrapped or rotated labels, full text in the tooltip.
- A categorical column whose values are unique per row is an identifier, not a grouping.

**Time**
- Line and area charts need time or ordinal on the horizontal axis. A nominal column on a line chart is a bug.
- Mixed granularity: regularize to one unit before rendering. Missing periods show as gaps, never as zero.
- Time zones and fiscal calendars come from the brief. Absent that, state the assumption in the explanation.
- Fewer than three time points is not a trend. Use a bar.

**Values**
- Never truncate a bar's value axis. A line may start above zero only when the range is narrow, with a note.
- Negative values rule out pie, percent-stacked, and log scale.
- Log scale only for positive values spanning orders of magnitude, and always labeled.
- Dual axes only when units differ and the brief asks. Prefer two stacked panels.
- Units and number formats come from the profile and the brief: currency, percent, thousands separators, decimals.
- A single aggregated number is a stat card, not a chart. A table is always a valid fallback.

**Data shape**
- Wide data is reshaped to long by code before design.
- Nulls: drop, gap, or explicit "unknown" group, chosen per chart and stated in the explanation.
- Large data is aggregated, binned, or sampled by code. Raw rows never reach a model.
- Empty result after filtering: ask, do not draw an empty chart.

**Labels, annotations, color**
- Data labels only when marks are few enough to read. Otherwise rely on axes and tooltips.
- Annotations are for evidence: a target line, an average, a highlighted outlier, a period band. Not decoration.
- Categorical palettes cap at about ten colors and must be colorblind-safe. Sequential for ordered values. Diverging only around a meaningful midpoint.
- Emphasis color on one or a few marks with the rest muted, when the question is about those marks.
- Brand colors from the brief are honored and checked for contrast.
- Hiding an axis is allowed for sparklines and stat cards. Never hide the value axis of a chart that makes a comparison.

**Maps**
- A map needs coordinates or region codes that match a known boundary set. Otherwise it is not a map.
- Choropleths use sequential or diverging color with a legend. Classed breaks are stated.
- Points on a map cluster or sample above a size threshold.

**Layout and accessibility**
- Portrait canvases favor horizontal bars. Landscape favors columns.
- Every artifact carries a text description of what it shows.
- Contrast and font sizes meet the accessibility floor in every theme.

## 8. Inputs: the request and the brief

A request carries: its type, the caller's identity and a return address for questions, the question, a dataset reference or a fresh upload, an artifact reference when revising, a request reference when resuming or answering, and a brief.

The brief is the context that travels with the data. When another agent produces the file, it fills the brief. When a human uploads through the chat, the brief is mostly empty and the lead fills what it can by asking.

The brief holds: where the data came from and the query used to pull it, when it was pulled, the raw user question, the enriched question, the intent such as compare, trend, rank, distribution, or composition, a suggested chart type, column descriptions and units, known caveats such as filters, sampling, or row limits, brand colors or theme, and the identity of the producing agent.

Three rules govern the brief.

1. **The brief is context, never fact.** The profiler still measures everything. Descriptions become hints for interpretation. When a hint contradicts the numbers, the profile carries a warning instead of silently picking a side.
2. **A suggested chart type is a preference, not an order.** The designer may override it with a stated reason. The reviewer checks that the reason holds. The lead tells the caller when it deviated and why.
3. **Both questions are kept, and the reviewer judges against the raw one.** The enriched question is useful for design, but it can drift from what the person actually asked.

## 9. Workflow

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

The reviewer sees the rendered picture, not only the spec, because overlapping labels and unreadable axes exist only once rendered. It also sees the list of rendering compromises so it judges the designer's choices, not the renderer's limits. When the verdict is not a pass, the designer fixes, the renderer re-renders, and the reviewer judges again. The loop is bounded. When the cap is reached, the best version is delivered with the reviewer's remaining notes shown to the caller. Nothing fails silently.

The reviewer is independent: separate instructions from the designer, and a different model where possible, so it does not share the designer's blind spots. Quality is the priority. Time and cost are not the constraint.

## 10. Artifacts and lineage

The artifact is the unit of delivery and the unit of memory. It holds the chart spec, the data slice, the rendered files in one or more formats, the plain-language explanation, the reviewer's final verdict, the rule breakdown behind the chart choice, and its lineage: dataset, profile version, catalogue and rules version, renderer, request, parent artifact when revised, and the clarifications that shaped it.

Rule: every artifact is traceable and reproducible. Given its lineage, the same artifact can be rebuilt. Which identifiers implement that is a technical decision.

Artifacts are stored, versioned, and addressable by ID. The chat shows them. Other callers receive them by reference.

## 11. Storage

No new database. The project's existing local database and data folder hold everything.

Already present: uploaded files, the imported tables, dataset metadata, and saved profiles.

Added as phases need them: the chart catalogue and rules as versioned files, requests and their state, step outputs used as checkpoints, artifacts and their versions, reviewer verdicts kept as labeled examples, and the log of clarification messages. Rendered files live on disk next to the uploads.

Profiles are saved once per dataset and reused by every later request about that data. Measured facts are kept as long as the dataset exists. The interpretation is re-run only when the profile format changes or when a brief arrives that the profiler has not seen for that dataset.

## 12. Quality

- Every agent has a typed output and a validator. A failed validation asks the model for one corrected attempt. A failure the model cannot fix is reported as a failure, not retried.
- Every specialist's cost counts against the parent request, with a spending cap per request.
- Tracing is on from day one. Pydantic recommends Logfire. Any OpenTelemetry backend works.
- Tests use fake models so logic is checked without network calls, and they run through the agent rather than around it.
- Catalogue, rules, spec check, and renderers are tested with no model at all: fixed inputs, expected candidates, expected violations, reference images.
- Each agent has an evaluation set of real inputs with expected outputs. Reviewer verdicts feed the designer's set automatically. Recorded real runs are kept and replayed.
- A profile is triggered automatically when an upload finishes, so the first question about a dataset never waits for profiling.

## 13. Interfaces

One entry point, many callers. Web chat, terminal, and other agents send the same inputs and receive the same outputs.

The installed SDK provides the web chat and the terminal entry points today. The agent-to-agent entry point is a separate Pydantic package and is confirmed in the technical stage before Phase 5 relies on it.

## 14. Effort and risk

Honest sizes for an experienced engineer, in working days, excluding tuning time on real data. The designer and its rendering foundation are close to half of the total. That is where the value is and where the risk is.

| Piece | Days | Main risk |
|---|---|---|
| Profiler upgrades: brief, review step, measurement levels, geography, auto-profile, tracing, evals | 5 to 8 | Interpretation quality on messy real files |
| Design foundation: neutral spec, catalogue, rules, spec check, first renderer with images | 12 to 18 | Getting the spec right the first time; every later renderer depends on it |
| Designer agent: intent, candidate choice, spec filling, repair, evaluation set | 8 to 12 plus ongoing tuning | Model quality on ambiguous asks; this is where "best in the world" is won or lost |
| Reviewer: rubric, picture inspection, number checks, loop, verdict store, agreement measurement | 6 to 10 | Agreement with human judgment |
| Lead and conversation: request types, checkpoints, resume, clarification, agent channel, durability | 10 to 15 plus operations for durability | The agent-to-agent package and running durable execution |
| Second renderer | 8 to 12 | Synthesizing facets |
| Map renderer with base map | 12 to 18 | Legends, palettes, and headless rendering are all manual |
| Insight finder | 6 to 10 | Distinguishing findings from noise |

Total for the first five pieces: roughly 40 to 65 days before a second renderer or maps.

## 15. Phases

Phases follow the workflow order, one agent at a time. The profiler goes first because it exists, it is the pilot for how every agent in this system is built, and every later step depends on its output. The designer is split into a code-only foundation phase and an agent phase, because the foundation must be trusted before a model is put on top of it.

### Phase 1: Profiler as the pilot agent

Goal: make the profiler the model for every agent that follows, and produce what the designer will need.

In scope:

- Accept an optional brief. Use its hints for interpretation. Flag conflicts with the measurements as warnings.
- Add measurement levels per column: nominal, ordinal, interval, discrete, continuous, time, geographic. A column may carry several. Detect ordinal patterns such as Q1 to Q4 or Week 1, boolean vocabularies, and geography: latitude and longitude pairs, region names, country codes, WKT.
- Add review_profile. Code checks first: a column described as a date must have date statistics, an identifier must be near-unique, units must fit the value range, a geographic column must have valid coordinates or matchable names. Then a model self-check against the measurements and the brief. A failed check sends the interpretation back once.
- Start profiling automatically when an upload finishes.
- Apply the reuse rules from section 11.
- Make the profiler callable on its own: from the chat as today, from the terminal, and from another program that passes a brief. A direct program call is enough in this phase.
- Turn tracing on.
- Tests run through the agent with a fake model. Build an evaluation set of ten to twenty real CSVs with expected column roles, units, measurement levels, and warnings, including files seeded with deliberate brief conflicts.
- Fix pilot findings that touch this agent: report terminal failures as failures rather than retries, widen the geometry column rule beyond the single name it matches today, check upload size before the body is parsed, and log semantic failures with their cause.

Out of scope: designer, renderer, reviewer, artifacts, request types, checkpoints.

Exit test: on the evaluation set, column roles, units, and measurement levels are right at least nine times in ten, seeded conflicts are flagged every time, no measured statistic ever comes from a model, and every test passes through the agent.

Lessons to record: where interpretation fails and why, how often a brief conflicts with the data, time and cost per profile, and whether review_profile catches errors the existing output check missed.

### Phase 2: Design foundation, no model

The neutral chart spec, the chart catalogue with about twenty entries, the hard, soft, and design rules, recommend_charts and check_spec as code, the get-data step, and the first renderer producing HTML and an image without a browser. All tested with fixed inputs and reference images. A human can hand-write a spec and get a correct picture.

Exit test: for a fixed set of profiles and intents, recommend_charts returns the expected top candidate at least nine times in ten. Every edge case in section 7 that is a rule or a fix has a test. The renderer draws every catalogue entry from a hand-written spec.

Lessons to record: which spec features were hard to express, which rules needed tuning, rendering time per chart.

### Phase 3: Chart designer agent

The model on top of the foundation: intent reading, choosing among candidates, filling the spec, one repair after a failed check, the explanation. The lead stays a thin chat front that runs the pipeline. Charts are judged by hand, and those judgments seed the reviewer's rubric and evaluation set.

Exit test: on a fixed set of at least twenty real CSVs and questions, the first chart is judged correct by a human at least seven times in ten without revision, and every delivered spec passed check_spec.

Lessons to record: where intent reading fails, how often the model overrides the top candidate and whether it was right, how often the repair turn is needed.

### Phase 4: Reviewer and the review loop

Reviewer built as a full agent with a different model from the designer. Bounded loop. Verdicts saved as labeled examples. Second renderer added to prove the chart spec is really neutral.

Exit test: reviewer verdicts agree with human judgment on the Phase 3 set at least eight times in ten, and charts delivered after the loop score higher than Phase 3 first charts on the same set.

### Phase 5: The lead and the conversation

Four request types, checkpoints and resume, clarification in both directions, the agent-to-agent channel, and true resume through durable execution, which is already attached to the agent but not yet active. Terminal interface.

Exit test: a request killed mid-run resumes from its last checkpoint. A revise produces a linked version. A clarification round-trips with both a human and an agent.

### Phase 6: Beyond one chart

Maps with a base map, the insight finder feeding annotations and narrative, multiple datasets, dashboards, other file types, other agents as regular callers. Additional renderers such as AntV G2 or ApexCharts only on demand and after license review.

## 16. Decisions made

- Fixed step order in code. Models decide inside steps only.
- The designer's knowledge lives in a catalogue as data, rules as code, and renderers as code. The model reads intent, chooses among candidates, fills the spec, and repairs after a failed check.
- Neutral chart spec with one renderer per library, each declaring what it supports. A check runs before every render.
- First renderer Vega-Lite, second Plotly, maps on the first renderer until a base map is needed, then MapLibre. Mapbox not used. AntV G2 and ApexCharts optional and later.
- Reviewer is a full, independent agent from the moment charts exist, judges the rendered picture, and sees the rendering compromises.
- One strong reviewer first. A panel of judges is a later experiment, adopted only on evidence.
- Profiles belong to the dataset and are reused across requests. The profiler emits measurement levels and geography for the designer.
- Existing database and data folder hold everything. No new database.
- The brief is context, never fact.
- Profiler first, then the design foundation without a model, then the designer agent, then the rest in workflow order.

## 17. Open questions for the technical stage

- The exact shape of the chart spec and how much of it the first renderer must support on day one.
- Which model sits in the reviewer's seat, given it should differ from the designer's.
- Whether the agent-to-agent package is available for the installed SDK version, and what to use if not.
- What running durable execution requires operationally, and whether Phase 5 needs it or saved checkpoints are enough at first.
- Font availability for server-side image rendering in the deployment environment.

## Appendix: how this maps to Pydantic AI

Short, so the technical design has a starting point. Every row comes from Pydantic's official skill.

| Design idea | Pydantic mechanism |
|---|---|
| Specialist returns a result to the lead | Agent delegation: the lead calls the specialist inside a tool and passes its usage along |
| Fixed step order with models inside steps | Programmatic hand-off, or a graph when the state machine grows |
| Typed outputs with validation and one retry | Structured output types, output validators, ModelRetry |
| Failures the model cannot fix | ToolFailed, which does not consume the retry budget |
| Chart spec the model must fill | A Pydantic model as the designer's output type, with field descriptions and validators that encode the hard rules |
| Catalogue and rules used by the model | Rulebook instructions loaded on demand, plus recommend_charts and check_spec as tools the model must call |
| Each agent's rulebook | Instructions on the agent, with specialist rulebooks loaded on demand when they are not needed on most turns |
| Checkpoints and resume | Durable execution capability already attached, or saved step outputs until it is activated |
| Web chat, terminal, other agents | The web and terminal entry points on the agent; the agent-to-agent package to be confirmed |
| Tests without network | TestModel and FunctionModel through agent override, with message capture |
| Evaluation sets | Pydantic's evals package with cases and datasets |
| Tracing | Logfire instrumentation, or any OpenTelemetry backend |
