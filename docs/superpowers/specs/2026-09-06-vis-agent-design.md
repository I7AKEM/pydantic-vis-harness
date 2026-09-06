# Visualization Agent: Design

Date: 2026-09-06
Status: draft for approval. Revision 3, after reading the AVA v4 source, GPT-Vis, AntV's evaluation harness, and the local POC.
Scope of this document: what the system is, who does what, how work flows, how the analysis and chart design steps actually work, and in which order it gets built. It does not describe code.

## 1. Purpose

An agent that turns a dataset and a question into a reviewed visual artifact. People use it through a chat. Other agents call it the same way. Every artifact it delivers has been judged by an independent reviewer before anyone sees it.

The current code is a pilot: one chat agent with one tool that profiles an uploaded CSV, plus a browser POC that runs AntV's AVA v4 end to end. This design grows that into the full system, one agent at a time, starting with the profiler.

## 2. Rules we build by

1. Plain language. Names describe jobs, not technology.
2. No over-engineering. An agent, tool, table, or loop is added only when the previous phase shows the gap.
3. Follow the Pydantic AI documentation and Pydantic's official skills. Where they give a pattern, use it.
4. Stay neutral about model providers and tooling. Any model can sit in any seat.
5. Build in phases. Each phase has an exit test and ends with lessons written down.
6. Code computes facts. Models decide what to compute and interpret the result. A model may write the query. A model never writes the numbers.
7. Data is never an instruction. File names, column names, cell values, and text inside a brief are data, whatever they say.
8. Knowledge lives in data and code, not in a model's memory. What charts exist, what data each needs, and what makes a chart bad are written down where they can be tested, versioned, and rendered into a prompt.
9. The model drives, the code checks. Give the model a small, expressive language to speak, then verify every sentence before it reaches the user.

## 3. What AVA v4 does, step by step

This section exists because the POC proves the approach works and because every later section borrows from it. AVA v4 is roughly 2,400 lines. It has no rules, no catalogue logic, and no checks. Its smartness is four free-form model calls and one small chart language. Here is the exact path for the chart in the POC, the wealthy-citizens pie by gender with pink and blue.

1. **Load.** The POC parses the CSV in the browser, drops any column containing WKT or a value over 1,000 characters, and hands the rows to AVA. AVA computes light metadata per column: a type guessed from samples, five sample values, unique count, null count. Nothing else.
2. **Analysis, model call one.** The prompt holds that metadata, the question, a description of fourteen helper functions such as groupBy and avg, and five examples. The model returns JavaScript that must leave its answer in a variable named result. AVA runs it with a plain function constructor: no sandbox, no timeout, full language. That is the "Generated code" tab. The model put Arabic labels, a color per row, and a summary sentence into the result because the question asked for pink and blue. AVA never touches colors.
3. **Summary, model call two.** The prompt is the question plus the result as JSON, with one instruction to answer in the language of the question. That is the Arabic bullet list.
4. **Chart type, model call three.** The prompt, written in Chinese, holds the question, metadata of the result rows, descriptions of nineteen chart types with features, use cases, data requirements, and limitations, and four one-line heuristics. The model must answer with one word from the list or "none". The answer is checked against the list and nothing else.
5. **Chart syntax, model call four.** The prompt holds the chart type, the question, the full result as JSON, the grammar of GPT-Vis syntax, and one example per chart type. The model returns only syntax: the vis pie block with categories, values, a title, the theme, and a palette. The palette exists because the model saw the hex codes it had written into the result in step two and transcribed them. The POC then forces innerRadius and the dark theme for donut requests.
6. **Render.** AVA wraps the syntax in a fixed HTML page that loads GPT-Vis from a CDN. GPT-Vis parses the syntax into a small JSON object, type, data, title, theme, style, and its pie component maps that to a G2 chart: a stacked interval on a polar coordinate, colors from the palette in category order, percentage labels only when there are eight or fewer slices with overlap hiding, a legend, tooltips, and dark-theme tokens. Twenty-six such hand-written components exist. A separate package renders the same JSON to a PNG on a server with no browser.

What makes it feel smart: the model writes real code against the data, so any question that can be computed gets computed. The chart language is tiny, so the model rarely gets it wrong. The polish lives in the renderer's hand-written components, not in the model. Language following costs one prompt line.

What it does not do, and what your screenshot shows: nothing checks the numbers or the labels. The generated code appears to map the value F to the Arabic word for males and everything else to females, which is inverted if F means female in the data. The summary then repeats the inverted claim. Nothing checks the syntax against the chart's schema before render, so errors only appear in the browser. Chart choice is a single word with no reason and no alternatives. The generated code runs unsandboxed. Colors are whatever the model happened to write.

AntV knows this. Their skills repository ships an evaluation harness that renders generated charts in a headless browser, detects blank output, and asks a vision model to score four things: data completeness, chart type match, visual clarity, and aesthetics, weighted 0.35, 0.3, 0.25, 0.1. They use it offline to improve their prompt documents. We run the same idea at request time, on every chart, as the reviewer.

## 4. The team

One lead talks to the caller. Specialists do one job each and hand results back to the lead. The lead never loses control of the conversation. Rendering is plain code with no model at all.

| Agent | Job | Skill, meaning its written rulebook | Input | Output |
|---|---|---|---|---|
| **Vis lead** | Understand the ask, classify the request, run the workflow, ask questions, explain the result | How to read a vague ask, when to ask versus assume, how to explain a chart in plain words, answer in the caller's language | Request text, dataset reference, previous artifact reference, answers to earlier questions, the brief | An artifact plus a short explanation, or one clear question |
| **Profiler** | Measure the data and describe what it means | Column meaning, units, roles, measurement levels, geography, data-quality flags, how to use hints from a brief without trusting them | Dataset ID, optional brief | Dataset profile: measured facts, interpretation, warnings, conflicts with the brief |
| **Data analyst** | Turn the question into a query, run it, and describe the result | Writing correct SQL over the profiled columns, choosing grouping and measures, naming result columns for people, keeping labels faithful to the data | Profile, question, brief, previous query when revising | A result table, the query that produced it, a description of each result column, and a plain-language summary in the caller's language |
| **Chart designer** | Decide what to show and how, within the chart catalogue | Reading intent, choosing among candidates, assigning result columns to visual roles, titles, labels, annotations, color intent, repairing a failed check | Result table and its description, the question, the brief, ranked chart candidates, previous chart spec when revising | A chart spec that passed the check, or a question |
| **Reviewer** | Independent judge of the finished chart | A scored rubric: correct, relevant, honest, readable, accessible, simple | The rendered picture, the chart spec, the result table, the raw question, the list of known rendering compromises | A verdict with a score per criterion and a short list of concrete fixes |
| **Insight finder** (later phase) | Find what is interesting in the data before anyone asks | Which findings deserve an annotation or a sentence, which are noise | Profile, result table | Ranked findings, each with the evidence and a suggested annotation |

| Code step | Job | Input | Output |
|---|---|---|---|
| **Render** | Turn a spec plus data into files, one renderer per chart library | Chart spec, result table | HTML page, the library's own config, an image for the reviewer |

The data analyst is new in this revision. AVA showed that a model writing the query is what makes arbitrary questions answerable. The earlier draft only allowed declarative grouping inside the chart spec, which could not have produced "percentage of wealthy citizens by gender". The analyst writes SQL, code runs it on the existing DuckDB store on a read-only connection with a timeout and a row cap. That is AVA's analysis step with the safety AVA lacks: no JavaScript execution, and every number comes from the database.

## 5. Tools, initial catalogue

Every tool is listed here so the full picture exists now. Each is built in the phase that needs it. "Done by" says whether the tool's work is fixed code or a model call.

### Vis lead

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| run_workflow | Start or continue the fixed sequence of steps for one request | Code | Request ID | The artifact, or the question a step raised |
| ask_caller | Pause the request and send one question to the human or to the producing agent | Code | Request ID, the question, who should answer | Confirmation that the request is paused |
| find_dataset | Look up a dataset and its profile | Code | Dataset ID or name | Dataset summary and profile status |
| find_artifact | Look up an artifact and its versions | Code | Artifact ID | Artifact summary and lineage |
| suggest_questions | Propose questions worth asking about a dataset, as AVA's suggest does | Model, from the profile | Dataset ID | Three to five questions with a reason each |

### Profiler

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| profile_csv | Import the file, measure every column by code, interpret meaning with the model, save the profile. Exists today. | Code for facts, model for meaning | Dataset ID, optional brief | Dataset profile |
| review_profile | Check the interpretation against the measurements and the brief. Flag conflicts. Send the interpretation back for a redo when a check fails. | Code checks, then a model self-check | A profile | The same profile with warnings and conflicts filled in, or a redo request |

### Data analyst

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| run_query | Run one read-only SQL statement on the dataset with a timeout and a row cap. Reject writes, multiple statements, and references to other tables | Code | SQL | Result table, row count, column types, or the database error verbatim |
| check_result | Recompute a few sanity facts from the raw data by code: row totals, category sets, min and max, so the analyst can confirm labels and percentages are faithful | Code | The query, the result table | Matches and mismatches |

The query, the result description, and the summary are the analyst's output, not tools.

### Chart designer

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| recommend_charts | Match the result table's shape and the intent against the chart catalogue, apply the rules, return ranked candidates with the reason for each score | Code | Result description, intent | Ranked candidates with reasons, or "no chart fits, use a table or a single number" |
| check_spec | Check a draft spec against the chart's schema, the rules, and what the chosen renderer supports. Return violations, each with a suggested fix, and the list of compromises the renderer will make | Code | A draft chart spec, renderer name | Pass, or violations with fixes |

The chart spec itself is the designer's output, not a tool.

### Reviewer

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| inspect_artifact | Load the rendered image, the spec, the result table, the raw question, and the known rendering compromises together | Code | Artifact ID | Everything the reviewer needs to judge |
| check_numbers | Read values off the spec and compare them with the result table and with a fresh recomputation from the raw data | Code | Artifact ID, values to check | Matches and mismatches, including label-to-value pairing |

The verdict itself is the reviewer's output, not a tool.

### Insight finder, later phase

| Tool | What it does | Done by | Input | Output |
|---|---|---|---|---|
| find_patterns | Run fixed statistical tests: trend, change point, outlier, majority, low variance, correlation. Score and rank them | Code | Result table | Ranked findings with evidence |

## 6. How the analyst and the designer work

These two steps are where AVA's smartness lives, and where our checks are added. The model drives in both. The code verifies.

### 6.1 The analyst step

Input: the profile, the question, the brief. The model writes one SQL statement against the dataset's table, naming result columns for people. Code runs it read-only. The model then writes a description of each result column: what it measures, its unit, whether it is a category, a measure, a time, or a share. It confirms with check_result that labels and shares are faithful. Finally it writes a two-sentence summary in the caller's language. Output: the result table, the query, the column descriptions, the summary.

Why SQL and not the model's own arithmetic: rule 6. The database computes. The screenshot's inverted gender labels would have been caught here, because check_result compares the category set in the result with the category set in the raw data and reports the mapping the query used.

Revise requests reuse the previous query as the starting point. Requests that need columns the dataset lacks return a question instead of a query.

### 6.2 The chart catalogue

A list of chart types written as data, not code. Each entry says: the chart's name and aliases, what it is for using a fixed vocabulary such as comparison, trend, distribution, rank, proportion, composition, relation, spatial, and anomaly, what result shape it needs expressed as how many columns of which kind, which fields of the spec it accepts, and a rating: recommended, use with caution, not recommended. Pie is "use with caution" in the catalogue itself.

The same catalogue file does two jobs. It is rendered into the designer's prompt as descriptions, the way AVA v4 renders its nineteen chart definitions. And it drives the code checks in recommend_charts and check_spec, the way AVA v3 did. One source, two uses.

### 6.3 The chart spec

Our contract between the designer and every renderer. It is text in GPT-Vis syntax, the same indented key-value form AVA emits, because the POC proves models write it reliably, it streams line by line, and a renderer for it already exists in the browser and on a server. The syntax is the only form of the spec that is written, stored, shown, or exchanged. There is no JSON contract. The checker and each renderer parse the syntax internally with one shared parser, exactly as GPT-Vis parses its own syntax, and nothing outside them sees the parsed form. On top of GPT-Vis's vocabulary we add optional keys that GPT-Vis does not have, written in the same style, which any renderer may honor or degrade:

- Chart type and data, in GPT-Vis's shapes: category and value, time and value, x and y, group, series.
- Title, axis titles, theme, palette. As in GPT-Vis.
- Sort order and top-N with "Other".
- Number and date formats per axis and per label, as format strings.
- Axes and legend shown or hidden. Data labels on or off.
- Scale choices: log, zero baseline forced, independent second axis.
- Annotations: reference line, band, point callout, text note, in data coordinates with a label.
- Color as a rule: a palette by category order as GPT-Vis does, or emphasis on named categories with the rest muted. Brand colors from the brief override.
- Accessibility text describing the chart.
- A map branch when a geographic column exists.
- Interaction hints, kept out of the render-critical path.

Anything a model writes into the spec is validated against the chart's schema before it goes anywhere. That is the check AVA skips.

### 6.4 The designer step

1. Read the intent from the question, the brief, and the analyst's column descriptions.
2. Call recommend_charts. Choose among the top candidates. Rules cannot tell a grouped bar from a stacked bar; the model reads column names and decides.
3. Fill the spec: which result columns take which roles, title in the caller's language, axis titles with units, sort, labels, color intent including any colors the caller asked for by name.
4. Call check_spec. Repair once on violations. Hand over only a spec that passed.
5. Explain the choice in two sentences, including why a suggested chart type was overridden.

### 6.5 The rules

Small pure functions, each with an ID, a type, a human explanation, and a suggested fix. Hard rules filter: the result shape does not satisfy the chart, a column would be silently dropped. Soft rules score: pie and donut want two to six unequal slices, bars with more than twenty categories lose points, line and area want time or ordinal on the horizontal axis. Design rules fix: never truncate a bar's value axis, hide data labels when marks are too many. Scores are bounded and additive, and every candidate keeps its per-rule breakdown for the explanation and the evaluation set.

### 6.6 The renderers

One renderer per library, in code, tested with fixed specs and reference images. Each renderer declares what it supports. Before rendering, check_spec resolves every feature the spec uses to supported, degraded with a documented fallback, or rejected with a message the designer can act on. The degradation list travels with the artifact to the reviewer.

### 6.7 The narrative

The words that accompany a chart are written in the same spirit as the chart: a small text syntax the model writes, that code can check and a renderer can style. We adopt AntV's narrative syntax, T8: ordinary Markdown for structure, plus an annotation on every data point in the prose, in the form display text, entity type, and metadata. The entity types name what a number is: a metric name, a metric value, a change, a rate, a share, a rank, a trend description, a category value, a time period, an anomaly. The metadata carries the raw value behind the display text, the unit, and whether the change is good or bad.

Two rules make it more than styling. Every annotated value must carry its raw value, and code checks that the raw value exists in the result table or in a computed comparison between result rows. A sentence whose number cannot be found is a validation failure and goes back to the model once. This closes the gap in AVA v4, where the summary is free prose and any number in it is the model's own reading. Second, the narrative is written in the language of the raw question, detected once and passed to every agent.

The analyst writes the two-sentence summary this way. The lead writes the explanation this way. In a later phase the insight finder produces annotated sentences from fixed templates per finding type, the way AVA v3 did without a model, and the model only smooths the wording.

## 7. Rendering targets

The reviewer must see a picture, so "can this library draw an image on a server" is the deciding question.

| Library | Image on a server | License | Verdict |
|---|---|---|---|
| GPT-Vis on G2 | Yes, an official server package draws the parsed syntax to PNG with Node and a native canvas library | Open | **First renderer.** The base spec is its own format, so mapping cost is near zero, and the POC already renders it |
| Vega-Lite | Yes, one Python package, no browser, no JavaScript runtime | Open | **Second renderer.** Proves the spec is neutral and gives a Python-only image path |
| Plotly | Yes, needs a bundled headless Chrome | Open | Third, for 3D, sankey, candlestick, gauges |
| MapLibre | Yes, native package or headless browser | Open | Map renderer when a base map is needed |
| ApexCharts | Yes, official server-side rendering, recent | Commercial since mid-2025: free only under a revenue threshold, faceting paid | Optional, subject to license review |
| Mapbox | Static image service renders only styles published in their studio, billed per load | Proprietary | Not used. MapLibre is the open equivalent |

Adding a renderer means writing one mapper from the spec to that library's config plus a capability declaration. AntV's evaluation datasets of hundreds of chart cases can seed the mapper's tests.

Features that resist neutral expression, and how the spec handles them: annotations use different coordinate conventions in every library, so the spec carries data coordinates and each renderer converts. Per-mark colors are a list in one library, a scale in another, and a flag in a third, so the spec carries a color rule and the renderer produces the list. Number formats are declarative everywhere except ApexCharts, so that renderer, if built, pre-formats values in code.

## 8. Edge cases the designer must handle

Each of these is a rule, a design fix, a query pattern, or a profiler flag. None is left to the model's judgment alone.

**Categories**
- More than about twenty categories on a bar: sort and keep the top N with "Other", or switch to a table.
- Pie or donut with more than six slices, or slices too close in size: use a sorted bar instead.
- A second categorical column with high cardinality: heatmap, facets, or top N. Never dozens of colors.
- Long category labels: horizontal bars, wrapped or rotated labels, full text in the tooltip.
- A categorical column whose values are unique per row is an identifier, not a grouping.
- Coded values such as F and M are relabeled only from the profile's interpretation or the brief, and the relabeling is checked against the data.

**Time**
- Line and area charts need time or ordinal on the horizontal axis.
- Mixed granularity: regularize to one unit in the query. Missing periods show as gaps, never as zero.
- Time zones and fiscal calendars come from the brief. Absent that, state the assumption in the explanation.
- Fewer than three time points is not a trend. Use a bar.

**Values**
- Never truncate a bar's value axis. A line may start above zero only when the range is narrow, with a note.
- Negative values rule out pie, percent-stacked, and log scale.
- Log scale only for positive values spanning orders of magnitude, and always labeled.
- Dual axes only when units differ and the brief asks. Prefer two stacked panels.
- Units and number formats come from the profile and the brief.
- Percentages are computed in the query with the denominator stated in the column description, never passed as pre-rounded numbers to a pie.
- A single aggregated number is a stat card, not a chart. A table is always a valid fallback.

**Data shape**
- Wide data is reshaped to long in the query.
- Nulls: drop, gap, or explicit "unknown" group, chosen per chart and stated in the explanation.
- Large results are aggregated, binned, or sampled in the query. Raw rows never reach a model.
- Empty result: ask, do not draw an empty chart.

**Labels, annotations, color**
- Data labels only when marks are few enough to read.
- Annotations are for evidence: a target line, an average, a highlighted outlier, a period band.
- Categorical palettes cap at about ten colors and must be colorblind-safe. Sequential for ordered values. Diverging only around a meaningful midpoint.
- Emphasis color on one or a few marks with the rest muted, when the question is about those marks.
- Colors the caller names are honored by category, checked for contrast, and the pairing is verified by the reviewer.
- Hiding an axis is allowed for sparklines and stat cards. Never hide the value axis of a comparison.

**Maps**
- A map needs coordinates or region codes that match a known boundary set.
- Choropleths use sequential or diverging color with a legend.
- Points on a map cluster or sample above a size threshold.

**Layout and accessibility**
- Portrait canvases favor horizontal bars. Landscape favors columns.
- Every artifact carries a text description of what it shows.
- Contrast and font sizes meet the accessibility floor in every theme.

## 9. Inputs: the request and the brief

A request carries: its type, the caller's identity and a return address for questions, the question, a dataset reference or a fresh upload, an artifact reference when revising, a request reference when resuming or answering, and a brief.

The brief is the context that travels with the data. When another agent produces the file, it fills the brief. When a human uploads through the chat, the brief is mostly empty and the lead fills what it can by asking.

The brief holds: where the data came from and the query used to pull it, when it was pulled, the raw user question, the enriched question, the intent such as compare, trend, rank, distribution, or composition, a suggested chart type, column descriptions and units, code meanings such as F for female, known caveats such as filters, sampling, or row limits, brand colors or theme, and the identity of the producing agent.

Three rules govern the brief.

1. **The brief is context, never fact.** The profiler still measures everything. When a hint contradicts the numbers, the profile carries a warning instead of silently picking a side.
2. **A suggested chart type is a preference, not an order.** The designer may override it with a stated reason. The reviewer checks that the reason holds.
3. **Both questions are kept, and the reviewer judges against the raw one.**

## 10. Workflow

### Steps and checkpoints

Every request has an ID and moves through fixed steps in this order:

understand, profile, analyze, design, render, review, deliver.

The output of each step is saved under the request ID the moment the step completes. That saved output is the checkpoint. A dropped or stopped request resumes by skipping every step that already has a saved output. Every step must be safe to run twice.

Decision: the order of steps is fixed in code. Models make decisions only inside a step and in the conversation with the caller. This keeps checkpoints, tests, and the review loop predictable.

Profiling is skipped when a complete profile for the dataset already exists.

### Request types

Agents state the type explicitly. For humans in the chat, the lead infers it from the conversation and confirms when unsure.

| Type | Starts with | Must reference | Starts at | Produces |
|---|---|---|---|---|
| **New** | A question plus data | The dataset | Understand | A new artifact, version 1 |
| **Revise** | A change request | An existing artifact | Analyze when the data must change, otherwise design | A new version linked to its parent |
| **Resume** | Nothing new, just "continue" | A dropped or stopped request ID | The last saved checkpoint | Whatever the original request would have produced |
| **Clarification** | An answer, or a question | The request that is waiting | The step that asked | Continues the original request |

Resume carries no new information and exists only because something stopped. Clarification carries new information and exists because a step deliberately paused to ask.

### Clarification in both directions

Outbound: the vis agent asks a question and the request pauses at a checkpoint. The recipient is the human through the chat or the producing agent through the agent-to-agent channel, chosen by who can answer. When the answer arrives, the request resumes at the step that asked. At most two questions per request.

Inbound: another agent may ask the vis agent something with no chart involved. The vis agent answers from its own knowledge. No artifact is created.

Rules for the agent-to-agent channel: every request carries the caller's identity and a return address; every outbound question has a deadline, after which the request stays paused and the human is told; every exchange is logged under the request ID; only messages on the channel count as requests.

### The review loop

The reviewer sees the rendered picture, not only the spec. It also sees the list of rendering compromises so it judges the designer's choices, not the renderer's limits. When the verdict is not a pass, the fix goes back to the analyst when the data is wrong or to the designer when the chart is wrong, and the reviewer judges again. The loop is bounded. When the cap is reached, the best version is delivered with the reviewer's remaining notes shown to the caller.

The reviewer is independent: separate instructions, and a different model where possible, so it does not share the designer's blind spots. Quality is the priority. Time and cost are not the constraint.

## 11. Artifacts and lineage

The artifact is the unit of delivery and the unit of memory. It holds the query, the result table, the chart spec, the rendered files, the plain-language explanation, the reviewer's final verdict, the rule breakdown behind the chart choice, and its lineage: dataset, profile version, catalogue and rules version, renderer, request, parent artifact when revised, and the clarifications that shaped it.

Rule: every artifact is traceable and reproducible. Given its lineage, the same artifact can be rebuilt.

## 12. Storage

No new database. The project's existing local database and data folder hold everything.

Already present: uploaded files, the imported tables, dataset metadata, and saved profiles.

Added as phases need them: the chart catalogue and rules as versioned files, requests and their state, step outputs used as checkpoints, artifacts and their versions, reviewer verdicts kept as labeled examples, and the log of clarification messages. Rendered files live on disk next to the uploads.

Profiles are saved once per dataset and reused by every later request about that data. The interpretation is re-run only when the profile format changes or when a brief arrives that the profiler has not seen for that dataset.

## 13. Quality

- Every agent has a typed output and a validator. A failed validation asks the model for one corrected attempt. A failure the model cannot fix is reported as a failure, not retried.
- Every specialist's cost counts against the parent request, with a spending cap per request.
- Tracing is on from day one.
- Tests use fake models so logic is checked without network calls, and they run through the agent rather than around it.
- Catalogue, rules, spec check, and renderers are tested with no model at all: fixed inputs, expected candidates, expected violations, reference images.
- Each agent has an evaluation set of real inputs with expected outputs. Reviewer verdicts feed the designer's set automatically. Recorded real runs are kept and replayed.
- The evaluation harness follows AntV's shape: render every case, detect blank or broken output, score the picture, and feed failures back into the rulebooks.
- A profile is triggered automatically when an upload finishes.

## 14. Interfaces

One entry point, many callers. Web chat, terminal, and other agents send the same inputs and receive the same outputs. The installed SDK provides the web chat and the terminal entry points today. The agent-to-agent entry point is a separate Pydantic package and is confirmed in the technical stage before Phase 6 relies on it.

## 15. Effort and risk

Honest sizes for an experienced engineer, in working days, excluding tuning time on real data.

| Piece | Days | Main risk |
|---|---|---|
| Profiler upgrades: brief, review step, measurement levels, code meanings, geography, auto-profile, tracing, evals | 5 to 8 | Interpretation quality on messy real files |
| Data analyst: read-only query tool, result checks, column descriptions, summary, evals | 6 to 9 | SQL quality on ambiguous questions; the checks must catch label errors |
| Design foundation: spec on the GPT-Vis base with extensions, catalogue, rules, spec check, GPT-Vis server renderer with images | 8 to 12 | Node and native canvas in the deployment; extensions the base renderer cannot honor |
| Designer agent: intent, candidate choice, spec filling, repair, evaluation set | 8 to 12 plus ongoing tuning | Model quality on ambiguous asks |
| Reviewer: rubric, picture inspection, number and label checks, loop, verdict store, agreement measurement | 6 to 10 | Agreement with human judgment |
| Lead and conversation: request types, checkpoints, resume, clarification, agent channel, durability | 10 to 15 plus operations | The agent-to-agent package and running durable execution |
| Second renderer, Vega-Lite | 6 to 9 | Extensions mapping |
| Map renderer with base map | 12 to 18 | Legends, palettes, headless rendering |
| Insight finder | 6 to 10 | Findings versus noise |

Total for the first six pieces: roughly 45 to 65 days before a second renderer or maps. Using GPT-Vis's format as the base saved four to six days on the foundation compared with the previous revision, at the cost of a Node dependency for images.

## 16. Phases

Phases follow the workflow order, one agent at a time. The profiler goes first because it exists, it is the pilot for how every agent in this system is built, and every later step depends on its output.

### Phase 1: Profiler as the pilot agent

Goal: make the profiler the model for every agent that follows, and produce what the analyst and the designer will need.

In scope:

- Accept an optional brief. Use its hints for interpretation. Flag conflicts with the measurements as warnings.
- Add measurement levels per column: nominal, ordinal, interval, discrete, continuous, time, geographic. A column may carry several. Detect ordinal patterns, boolean vocabularies, coded values such as F and M with their likely meanings, and geography.
- Add review_profile. Code checks first, then a model self-check against the measurements and the brief. A failed check sends the interpretation back once.
- Start profiling automatically when an upload finishes.
- Make the profiler callable on its own: from the chat as today, from the terminal, and from another program that passes a brief.
- Turn tracing on.
- Tests run through the agent with a fake model. Build an evaluation set of ten to twenty real CSVs, including the POC's sample and files seeded with deliberate brief conflicts.
- Fix pilot findings that touch this agent: report terminal failures as failures rather than retries, widen the geometry column rule, check upload size before the body is parsed, and log semantic failures with their cause.

Out of scope: analyst, designer, renderer, reviewer, artifacts, request types, checkpoints.

Exit test: on the evaluation set, column roles, units, and measurement levels are right at least nine times in ten, seeded conflicts are flagged every time, no measured statistic ever comes from a model, and every test passes through the agent.

Lessons to record: where interpretation fails and why, how often a brief conflicts with the data, time and cost per profile, whether review_profile catches errors the existing output check missed.

### Phase 2: Data analyst

The read-only query tool on DuckDB, the result checks, column descriptions, the summary in the caller's language. The lead stays a thin chat front. The output is a table and a summary, no chart yet.

Exit test: on twenty real questions over the evaluation datasets, the result table is correct at least nine times in ten, and every seeded label inversion is caught by check_result.

Lessons to record: where SQL fails, how often the model needs the repair turn, which questions need clarification.

### Phase 3: Design foundation, no model

The spec on the GPT-Vis base with our extensions, the chart catalogue with about twenty entries, the rules, recommend_charts and check_spec as code, and the GPT-Vis server renderer producing HTML and an image. All tested with fixed inputs and reference images. A human can hand-write a spec and get a correct picture.

Exit test: for a fixed set of result shapes and intents, recommend_charts returns the expected top candidate at least nine times in ten. Every edge case in section 8 that is a rule or a fix has a test. The renderer draws every catalogue entry from a hand-written spec.

### Phase 4: Chart designer agent

The model on top of the foundation. Charts are judged by hand, and those judgments seed the reviewer's rubric and evaluation set.

Exit test: on at least twenty real questions, the first chart is judged correct by a human at least seven times in ten without revision, and every delivered spec passed check_spec.

### Phase 5: Reviewer and the review loop

Reviewer built as a full agent with a different model from the designer. Bounded loop. Verdicts saved as labeled examples. Vega-Lite added as the second renderer to prove the spec is neutral.

Exit test: reviewer verdicts agree with human judgment at least eight times in ten, and charts delivered after the loop score higher than Phase 4 first charts on the same set.

### Phase 6: The lead and the conversation

Four request types, checkpoints and resume, clarification in both directions, the agent-to-agent channel, durable execution, terminal interface, question suggestions.

Exit test: a request killed mid-run resumes from its last checkpoint. A revise produces a linked version. A clarification round-trips with both a human and an agent.

### Phase 7: Beyond one chart

Maps with a base map, the insight finder, multiple datasets, dashboards, other file types, additional renderers on demand.

## 17. Decisions made

- Fixed step order in code. Models decide inside steps only.
- The model writes the query. The database computes the numbers. A data analyst agent owns that step.
- One syntax for every chart and every map, and the syntax is the output. The model writes only that syntax. It is what gets stored, shown, and handed to renderers. No JSON contract exists. The checker and each renderer parse the syntax internally with one shared parser and translate it into their own library's format. No model ever writes ApexCharts, Vega-Lite, Plotly, or map configuration directly. A renderer that cannot honor a feature reports it before rendering.
- The syntax is GPT-Vis's syntax plus our extensions written in the same style. GPT-Vis on a server is the first renderer, Vega-Lite the second, Plotly third, MapLibre for maps. Mapbox not used. ApexCharts optional after license review.
- Data enters the spec by binding result columns to chart roles. Code inserts the rows. The model never retypes values.
- One chart catalogue file feeds both the designer's prompt and the code checks.
- Every model output is validated against a schema before it is used. Every chart is checked before render and judged after render.
- The reviewer is a full, independent agent, judges the rendered picture, checks numbers and label pairing, and sees the rendering compromises.
- Profiles belong to the dataset and are reused across requests.
- Existing database and data folder hold everything. No new database.
- The brief is context, never fact.
- Profiler first, then analyst, then the design foundation without a model, then the designer, then the reviewer, then the lead.

## 18. Open questions for the technical stage

- How the GPT-Vis server renderer is hosted next to the Python service: a small Node sidecar, or a command the Python code shells out to.
- Which model sits in the reviewer's seat, given it should differ from the designer's.
- Whether the agent-to-agent package is available for the installed SDK version.
- What running durable execution requires operationally.
- Font availability for server-side image rendering, including Arabic shaping.

## Appendix: how this maps to Pydantic AI

| Design idea | Pydantic mechanism |
|---|---|
| Specialist returns a result to the lead | Agent delegation: the lead calls the specialist inside a tool and passes its usage along |
| Fixed step order with models inside steps | Programmatic hand-off, or a graph when the state machine grows |
| Typed outputs with validation and one retry | Structured output types, output validators, ModelRetry |
| Failures the model cannot fix | ToolFailed, which does not consume the retry budget |
| The query the analyst writes | A structured output holding the SQL, validated by code before execution |
| Chart syntax the model must write | Text output with a parsing function, which Pydantic's skill prescribes for structured text that is not JSON. The parser is the shared syntax parser, and validators on the parsed form encode the hard rules and ask for one corrected attempt |
| Catalogue and rules used by the model | Rulebook instructions loaded on demand, plus recommend_charts and check_spec as tools the model must call |
| Checkpoints and resume | Durable execution capability already attached, or saved step outputs until it is activated |
| Web chat, terminal, other agents | The web and terminal entry points on the agent; the agent-to-agent package to be confirmed |
| Tests without network | TestModel and FunctionModel through agent override, with message capture |
| Evaluation sets | Pydantic's evals package with cases and datasets |
| Tracing | Logfire instrumentation, or any OpenTelemetry backend |
