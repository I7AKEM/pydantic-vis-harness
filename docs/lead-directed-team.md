# Lead-directed visualization

## Decision

The lead is the domain expert and team manager. A CSV from the data agent is a finished factual result;
the brief tells the visualization team what to communicate. Running another analysis by default adds
latency and can change the meaning of a prepared total or percentage.

`draw` creates a request and reads that CSV without a model. The lead calls the designer with concrete
guidance, receives its spec, explicitly calls rendering, and decides whether to publish, request review, or repair. Optional
analysis is a separate lead tool for a requested transformation. The fixed understand/profile/analyze/
design/render/review/deliver dispatcher and its automatic repair loops have been removed.

## Ownership

- The lead owns chart intent, delegation, repairs, fallback selection, and completion.
- The designer owns visual representation and can deliver in one response.
- The scoped visual inspector receives the image after every successful render and returns only visible-defect
  findings to the lead. The lead never receives image bytes.
- The analyst computes only a task explicitly delegated by the lead.
- Code owns source reads, executable schemas, read-only SQL safety, persistence, rendering, and budgets.

The lead retains Pydantic AI's optional Advisor and TemporalDurability capabilities. Delegation uses
ordinary async tools with typed arguments, shared run usage, and framework limits. This keeps the team
visible in the existing Web Chat UI without an additional planner or orchestration library.

## Persistence and recovery

Requests save completed tool outputs. The old `steps` JSON field is retained for database compatibility,
but does not impose an order. The source table is stored under `analyze` to preserve artifact readers;
its `model` is null and its SELECT returns unchanged source columns. A changed design or table removes
stale render/review state before another external call. Publication reuses an existing artifact for the
request. API and terminal execution simply run the same lead against the saved request.

Existing artifacts remain readable and revisable. Old unfinished requests can be inspected by the lead;
no missing legacy checkpoint schedules work. In-process API runs reject a duplicate active request;
this is not a cross-process job queue or exactly-once execution service.

## Streaming lifetime

The chat response owns the lead's event stream. It explicitly closes both the protocol encoder and
the underlying event iterator when sending completes, fails, or is cancelled. This unwinds the
Pydantic AI run and provider stream before the HTTP handler returns. Without that cleanup, a browser
disconnect at a yielded chunk can leave background agent tasks and telemetry spans open until garbage
collection. Tests exercise connection loss, send failure, task cancellation, and normal completion.

Historical spans from a worker that already exited can still appear ongoing if its final span record
was never exported. That display does not mean the exited process is still doing work.

## Latency and quality

Avoid semantic profiling, another analysis, and mandatory chart ranking/check tool turns. A single scoped
visual inspection follows a successful render. The default OpenRouter lead is GLM 5.3 with low reasoning effort;
GLM 5.3 handles profiling and analysis, tested DeepSeek V4 Pro handles chart design, and Gemma 4 31B IT handles image inspection
with thinking disabled.
Model changes must be measured on complete requests, not inferred from token speed.

Acceptance checks cover preservation of prepared totals/percentages, Arabic/Hijri labels, lead-selected
review, lead-selected repair, source immutability, stale-preview invalidation, idempotent publish, saved
request recovery, and framework limits. Report live elapsed time and model requests alongside chart
fidelity. Historical chart-policy evaluations remain offline diagnostics, not runtime gates.

## Source meanings and display labels

The [data agent handoff](data-agent-handoff.md) carries source code definitions and optional approved
labels per language. The lead, designer, and reviewer receive the same definitions. A shared presentation
instruction requires consistent, source-grounded wording and preserves ambiguous codes when their meaning
is unknown. The designer supplies missing display mappings in its existing call; provided approved wording
is retained in the saved spec. Labels are applied only when drawing or displaying the card, so grouping
keys and source measurements remain unchanged across all chart types and later artifact reads.

## References

- [Pydantic AI: agent delegation](https://ai.pydantic.dev/multi-agent-applications/)
- [OpenRouter: GLM 5.3](https://openrouter.ai/z-ai/glm-5.3)
- [GLM 5.3 open weights](https://huggingface.co/zai-org/GLM-5.3)
