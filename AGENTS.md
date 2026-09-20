# Lead-directed visualization team

The current design is `docs/lead-directed-team.md`. Earlier phase designs under
`docs/superpowers/` describe the historical fixed-runner architecture.

## Product contract

- The upstream data agent supplies an authoritative CSV. The brief supplies visualization intent,
  column meanings, units, and preferences. The visualization team presents that data; it does not
  repeat upstream research, invent rows, check for missing data, or reaggregate prepared measures.
- Only the visualization lead controls the flow. It chooses profiling, analysis, design, rendering,
  review, repair, fallback, and publication through tools. Each tool returns control to the lead.
  Do not add a fixed step order, automatic specialist handoffs, or automatic review/repair loops.
- Optimize for correct charts and latency. Routine prepared CSVs need no profiler or analyst model call.
  The designer can deliver a spec in one response. After rendering, one scoped visual-inspector call checks
  only visible defects; it does not reopen analysis. Reasonable presentation decisions are the lead's
  responsibility, not questions to the user.
- Code handles data access, executable schema/binding checks, read-only SQL safety, rendering,
  persistence, and framework resource limits. Chart aesthetics and specialist selection belong to agents.
  Historical chart policy checks may remain in offline evals; they do not gate runtime design.
- Failures return diagnostics to the lead. They never become questions about missing data.

## Implementation

- Python 3.12, uv, Pydantic AI, OpenRouter or LiteLLM, and the built-in Web Chat UI.
- `vis_agent/lead.py`: the lead and its delegation tools.
- `vis_agent/providers.py`: one lead/team per provider. OpenRouter first when configured; default lead
  is the text-only `openrouter:z-ai/glm-5.3` with low thinking effort. Profiling and analysis use the same
  GLM model; chart design uses `openrouter:deepseek/deepseek-v4-pro`; the scoped visual inspector uses
  `openrouter:google/gemma-4-31b-it` with thinking disabled.
  Rendered image bytes never enter the lead context. Environment overrides persist.
- `vis_agent/analyst/source.py`: read the original CSV for direct charting without model calls.
- `vis_agent/requests/service.py`: request persistence, publication, and API/CLI entry point to the same lead.
- `vis_agent/requests/runner.py`: compatibility imports only; no flow control.
- `vis_agent/requests/models.py` and `store.py`: saved tool results and linked artifact versions.
- `vis_agent/designer/`, `analyst/`, `profiler/`, `reviewer/`: existing domain specialists.
- `vis_agent/render/`: the pinned GPT-Vis renderer. Node 22 LTS on PATH and
  `npm ci --prefix vis_agent/render/gptvis`; never edit node_modules. On Debian install
  `libexpat1`, `fontconfig`, and `fonts-noto-core`. Check with `uv run vis doctor`.
- Keep code small and explicit. No workflow engine, external A2A package, additional planner, Docker,
  second renderer, or generic orchestration layer.
- Preserve optional Advisor and TemporalDurability capabilities on the lead. Ordinary web calls do
  not run a Temporal worker. CodeMode is deferred until a tool actually needs its sandbox.

## Fidelity and recovery

- CSV values are immutable. SQL is the only computation path when the lead explicitly asks for a
  calculation. Labels, Hijri time strings, and leading-zero identifiers survive direct charting.
- Upstream `code_meanings` define codes per column. Approved `display_labels` supply exact localized
  wording; preserve it in saved designs. Translate only established meanings and keep ambiguous codes.
  Presentation mappings never change source cells or grouping identities. See `docs/data-agent-handoff.md`.
- Geometry, WKT, and oversized column values never enter model context.
- Never silently sample or aggregate the direct table. Resource bounds report technical limits.
- A changed table or design invalidates stale renders/reviews before external work. Publishing an
  already published request is idempotent. Resume returns saved work for the lead to choose from.
- Use async Pydantic AI delegation with shared `ctx.usage` and parent usage limits. Budgets belong
  to the framework. Test a model that ignores stop instructions and verify it terminates.
- Use fake models through `agent.override`; never construct `RunContext` by hand.

## Verification

```bash
uv run pytest -q
uv run python -m evals.designer.run
uv run python -m evals.designer.agent.run
uv run python -m evals.lead.run
```

Real-model evals need credentials. Prepared-CSV lead cases measure source fidelity, delivered artifacts,
model requests, and latency. Keep historical analyst/policy corpora separate from that objective.
Before merging reviewer changes, run `uv run python -m evals.reviewer.run` with the labelled set;
target at least 0.8 agreement. Confirmed failures become representative eval cases.

Run locally:

```bash
uv run uvicorn vis_agent.app:app --host 127.0.0.1 --port 7932 --reload
```
