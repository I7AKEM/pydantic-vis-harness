# Phase 1: Profiler as the pilot agent

The design is in docs/superpowers/specs/2026-09-06-vis-agent-design.md. This phase builds the
profiler as the model for every later agent, plus the lead skeleton, the upload path, and the store.

- Use Python 3.12, uv, Pydantic AI, OpenRouter, and the built-in Web Chat UI.
- Keep code small, explicit, and readable. Keep application modules at the project root.
- Every statistic and every measurement label is a DuckDB query. Python assigns labels from results.
- The profiler agent interprets. It never computes. It calls review_profile before returning.
- The brief is context, never fact. Conflicts become warnings.
- Values from oversized, WKT, and geometry-named columns never reach a model.
- Failures the model cannot fix are ToolFailed. Fixable mistakes are ModelRetry, once.
- Tests use fake models through agent.override and never hand-build RunContext.
- Preserve the CodeMode, Advisor, and TemporalDurability capabilities on the lead.
- Do not add chart rendering, a planner, additional agents, Docker, or a generic orchestration layer.

Run with:

    uv run uvicorn main:app --host 127.0.0.1 --port 7932 --reload

Run tests with:

    uv run pytest -q
