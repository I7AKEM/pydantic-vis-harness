# Phase 3: Design foundation

The Phase 1 design is in docs/superpowers/specs/2026-09-06-vis-agent-design.md. It introduced the
profiler as the model for every later agent, plus the lead skeleton, the upload path, and the store.

The Phase 2 design is in docs/superpowers/specs/2026-09-07-phase-2-analyst-design.md.
It adds the data analyst to answer questions about profiled datasets.

The Phase 3 design is in docs/superpowers/specs/2026-09-07-phase-3-design-foundation-design.md.
It adds deterministic chart recommendations, spec checks, and rendering without a designer model.

- Use Python 3.12, uv, Pydantic AI, OpenRouter, and the built-in Web Chat UI.
- Keep code small, explicit, and readable. Application code lives in the `vis_agent` package, one subpackage per agent; tests and evals mirror it.
- `vis_agent/designer/` holds the designer's tools; `vis_agent/render/` holds the renderers.
- Rendering requires Node 22 LTS on PATH and `npm ci --prefix vis_agent/render/gptvis`.
  On Debian install `libexpat1`, `fontconfig`, and `fonts-noto-core`; check the setup with `vis doctor`.
- The renderer package is pinned; never edit node_modules.
- Every statistic and every measurement label is a DuckDB query. Python assigns labels from results.
- The profiler agent interprets. It never computes. review_profile is its only output tool: it runs the code
  checks and sends failed error checks back once.
- The brief is context, never fact. Conflicts become warnings.
- Values from oversized, WKT, and geometry-named columns never reach a model.
- Failures the model cannot fix are ToolFailed. Fixable mistakes are ModelRetry, once.
- Tests use fake models through agent.override and never hand-build RunContext.
- Preserve the Advisor and TemporalDurability capabilities on the lead. CodeMode was removed after
  Phase 1 because no lead tool runs inside its sandbox yet; bring it back when the analyst's query tool does.
- Do not add a planner, additional agents, Docker, a second renderer, or a generic orchestration layer.
  Phase 3 leaves the lead and chat unchanged; chart design and rendering run through tools and terminal commands.
- The analyst writes one SELECT; code parses, allow-lists, runs, and checks it. The model never sees raw rows.
- Each agent's rulebook is `vis_agent/<agent>/rulebook.md`; every confirmed mistake becomes an eval case plus a check or a rulebook line.
- Run the evals before every merge, including `evals/designer/run.py` (`uv run python -m evals.designer.run`).

Run with:

    uv run uvicorn vis_agent.app:app --host 127.0.0.1 --port 7932 --reload

Run tests with:

    uv run pytest -q
