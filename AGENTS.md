# Phase 6: The lead and the conversation

The Phase 1 design is in docs/superpowers/specs/2026-09-06-vis-agent-design.md. It introduced the
profiler as the model for every later agent, plus the lead skeleton, the upload path, and the store.

The Phase 2 design is in docs/superpowers/specs/2026-09-07-phase-2-analyst-design.md.
It adds the data analyst to answer questions about profiled datasets.

The Phase 3 design is in docs/superpowers/specs/2026-09-07-phase-3-design-foundation-design.md.
It adds deterministic chart recommendations, spec checks, and rendering without a designer model.

The Phase 4 design is in docs/superpowers/specs/2026-09-07-phase-4-chart-designer-design.md.
It adds the chart designer agent, checked delivery, rendering, and the lead's chart tool.

The Phase 4b design is in docs/superpowers/specs/2026-09-07-phase-4b-evaluation-at-scale-design.md.
It adds the two-hundred-case scale set, the Hijri and Arabic seeded cases, the DSPy optimizer, and the
lessons in docs/phase-4b-lessons.md.

The Phase 6 design is in docs/superpowers/specs/2026-09-08-phase-6-lead-and-conversation-design.md.
It adds chart-first conversation, saved requests and artifact versions, clarification and resume,
terminal commands, the agent channel, and the lead evaluation in `evals/lead/`.

Requests package file map:

- `vis_agent/requests/models.py`: request records, step names, callers, exchanges, and artifacts.
- `vis_agent/requests/store.py`: requests and artifact versions in the datasets database.
- `vis_agent/requests/runner.py`: the fixed step order, saved outputs, answers, and resume.
- `vis_agent/requests/api.py`: the seven JSON routes and return-address callback.

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
- Hijri dates stay text end to end: the profiler labels them `hijri` (and Arabic-Indic numbers
  `arabic_digits`), the analyst buckets them as text with substr or a CASE over month names and never reads
  them as Gregorian dates, and resolving never shortens or reorders non-Gregorian time text. Gregorian time
  is drawn in order. The analyst's Hijri and digit rules live in `vis_agent/analyst/rulebook-localized.md`
  and reach the model per run only when a column carries one of those levels: in the always-on rulebook
  they cost three of 69 ordinary questions.
- Values from oversized, WKT, and geometry-named columns never reach a model.
- Failures the model cannot fix are ToolFailed. Fixable mistakes are ModelRetry, once.
- Tests use fake models through agent.override and never hand-build RunContext.
- Preserve the Advisor and TemporalDurability capabilities on the lead. CodeMode was removed after
  Phase 1 because no lead tool runs inside its sandbox yet; bring it back when the analyst's query tool does.
- The request runner is code with a fixed step order and a saved output per step:
  understand, profile, analyze, design, render, review, deliver. Resume reuses completed steps.
- No workflow engine, no external A2A package, no new agents. Do not add a planner, Docker,
  a second renderer, or a generic orchestration layer.
- The analyst's and designer's revise rules live in `vis_agent/analyst/rulebook-revise.md` and
  `vis_agent/designer/rulebook-revise.md` and reach the model per run only.
- `make_chart` is gone; `draw` returns the table with the chart. Use `answer_question` for numbers only.
- Run `uv run python -m evals.lead.run` before a merge that touches the lead.
- The analyst writes one SELECT; code parses, allow-lists, runs, and checks it. The model never sees raw rows.
- Each agent's rulebook is `vis_agent/<agent>/rulebook.md`; every confirmed mistake becomes an eval case plus a check or a rulebook line.
- Run the evals before every merge, including `evals/designer/run.py` (`uv run python -m evals.designer.run`).
  Also run `uv run python -m evals.designer.agent.run` (needs `OPENROUTER_API_KEY`).
  Run the scale set with `uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json`
  and `--split train`, `--split dev`, or `--split heldout`; judge the held-out forty with `--render`.
  Use `uv run python -m evals.designer.agent.optimize_instructions check` before optimizing with
  `uv run python -m evals.designer.agent.optimize_instructions run light OUT_DIR --split train`
  (`medium` is also supported; both modes need `OPENROUTER_API_KEY` and the `optimize` dependency group).
  The optimizer uses train and dev only. Adopt its rulebook changes only if the real runner's automatic
  scores improve on dev and heldout without lowering the judged sample; otherwise keep the seed rulebook.

Run with:

    uv run uvicorn vis_agent.app:app --host 127.0.0.1 --port 7932 --reload

Run tests with:

    uv run pytest -q
