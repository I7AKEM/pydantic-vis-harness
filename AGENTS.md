# Phase 2: Data analyst

The Phase 1 design is in docs/superpowers/specs/2026-09-06-vis-agent-design.md. It introduced the
profiler as the model for every later agent, plus the lead skeleton, the upload path, and the store.

The Phase 2 design is in docs/superpowers/specs/2026-09-07-phase-2-analyst-design.md.
It adds the data analyst to answer questions about profiled datasets.

- Use Python 3.12, uv, Pydantic AI, OpenRouter, and the built-in Web Chat UI.
- Keep code small, explicit, and readable. Application code lives in the `vis_agent` package, one subpackage per agent (`vis_agent/profiler/` today); tests and evals mirror it.
- Every statistic and every measurement label is a DuckDB query. Python assigns labels from results.
- The profiler agent interprets. It never computes. review_profile is its only output tool: it runs the code
  checks and sends failed error checks back once.
- The brief is context, never fact. Conflicts become warnings.
- Values from oversized, WKT, and geometry-named columns never reach a model.
- Failures the model cannot fix are ToolFailed. Fixable mistakes are ModelRetry, once.
- Tests use fake models through agent.override and never hand-build RunContext.
- Preserve the Advisor and TemporalDurability capabilities on the lead. CodeMode was removed after
  Phase 1 because no lead tool runs inside its sandbox yet; bring it back when the analyst's query tool does.
- Do not add chart rendering, a planner, additional agents, Docker, or a generic orchestration layer.
- The analyst writes one SELECT; code parses, allow-lists, runs, and checks it. The model never sees raw rows.
- Each agent's rulebook is `vis_agent/<agent>/rulebook.md`; every confirmed mistake becomes an eval case plus a check or a rulebook line.
- Run the evals before every merge.

Run with:

    uv run uvicorn vis_agent.app:app --host 127.0.0.1 --port 7932 --reload

Run tests with:

    uv run pytest -q
