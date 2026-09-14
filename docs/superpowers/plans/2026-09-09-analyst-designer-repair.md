# Analyst–designer feedback and repair plan

Status: proposed. This document describes the implementation; it does not change runtime behavior.

## The issue

The analyst can return a correct answer in a table that the designer cannot use to draw the requested chart. The designer can recognize the mismatch, but currently has no way to ask the analyst for a revised result. Its choices are to change the specification, deliver, or ask the user a question.

The validation feedback makes recovery harder. Some errors omit the actual mismatch, and some suggest an alternative that is also rejected. When attempts run out, both agents can turn an internal failure into a user clarification. This makes a clear, answerable request appear to need more information from the user.

This is a gap in feedback and available actions. It is not evidence that the user must choose a different chart, that the units should be changed, or that the renderer crashed.

### Evidence from the reported request

User request: **ارسم التغير الشهري لعدد المصابين والوفيات في جدة**

Trace: [`01a084f7dd5dc4f1c26bd40feb2cd7f6`](https://logfire-us.pydantic.dev/i7akem/vis-harness?traceId=01a084f7dd5dc4f1c26bd40feb2cd7f6&spanId=e6cd4641408a7853&since=2026-09-09T06%3A30%3A35.886460Z&until=2026-09-09T07%3A30%3A35.886460Z). Request: `rq_f5c12d15eb2a4bddbfd2783cba9e90d1`.

All 22 spans were inspected through Logfire MCP. The analyst successfully returned 12 monthly rows with a time column and two measure columns, both using the unit `شخص`.

| Action | Observed result |
|---|---|
| Recommend charts for `trend`, then `compare` | Both calls reject `grouped_column` and `multi_line` under H1. Single-measure candidates leave deaths unbound. |
| Check `dual_axes` | H10 rejects equal units and says “Use a grouped column.” |
| Check `grouped_column` | C2 rejects the month’s `time` kind for `category`, and rejects the numeric injuries measure as `group`. |
| Check `multi_line` | C2 reports the missing `group` binding. |
| Deliver the original `dual_axes` specification | H10 fails again. The designer returns a clarification and the request becomes `waiting`, without an artifact. |

H10’s grouped-column suggestion is fixed text, not a verified recommendation. C10 wraps a hard-rule failure; it is not a separate diagnosis. The error IDs are useful for tracing, but neither agent should need to decode them to understand a failure.

The designer is not entirely blind to chart requirements: its instructions already contain the catalogue, including roles and allowed column kinds. The missing information is a precise explanation of the current mismatch and a useful path to request upstream work.

### Relevant code

| Location | Current responsibility or limitation |
|---|---|
| `vis_agent/designer/rules.py`, `h1_shape`, `h10_units` | Generic shape failure and unconditional grouped-column advice. |
| `vis_agent/designer/recommend.py`, `default_binding`, `recommend_charts` | Missing bindings become generic H1 rejections. |
| `vis_agent/designer/check.py`, `check_spec` | Already produces some useful role/column/type explanations. |
| `vis_agent/designer/agent.py`, `instructions`, `create_designer` | Supplies the catalogue; exposes design and clarification outputs only. |
| `vis_agent/designer/agent.py`, `deliver_design` | Exhausted checks become a user clarification. |
| `vis_agent/analyst/agent.py`, `deliver_analysis` | Exhausted queries can also become a user clarification. |
| `vis_agent/analyst/rulebook-revise.md` | Treats a previous-analysis change as a caller instruction, not specialist feedback. |
| `vis_agent/requests/runner.py`, `design` | Runs the fallback only when both design and clarification are absent; has no analysis repair branch. |
| `vis_agent/requests/models.py`, `Request.next_step` | Resumes from the first missing saved step; repair must keep saved results consistent. |

## Intended behavior

Give the designer a general way to explain why the result cannot support the original request and request a change from the analyst. The analyst chooses how to revise its query using its existing tools. The designer then checks the revised result.

The model decides whether a problem requires a specification correction, revised analysis, or information from the user. Code validates outputs, enforces limits, and saves the exchange.

The implementation must not contain a branch for this dataset, Arabic column names, or a particular chart/reshape combination. The reported request becomes an evaluation case. It does not become the repair algorithm.

### Keep the architecture small

- Keep the current agents, renderer, SQL guard, chart grammar, and catalogue.
- Use one typed revision request and the existing runner. No message bus, peer-to-peer protocol, planner, or workflow engine.
- Start with one analysis repair exchange per request, enforced across fallback attempts and resumes.
- Keep the normal step order. Add one explicit exception: before rendering, design may request a revised analysis and then run again.
- Keep chart and SQL checks. A repair cannot change units, drop a requested measure, change filters, or relabel a time column merely to bypass a check.
- Treat a specialist’s feedback as a proposed internal repair, subordinate to the original request and the user’s answers.

This exception must be documented in `AGENTS.md` and the Phase 6 design during implementation.

## Communication contract

### 1. Self-contained validation feedback

Retain rule IDs for tests and telemetry. Make each model-visible failure explain:

- The attempted chart or binding.
- The relevant expected requirement.
- The actual columns, kinds, units, or measured limits causing the mismatch.

Derive this information from the existing catalogue, bindings, and result facts. Reuse one small formatting helper where recommendation and checking need the same explanation. Do not duplicate the catalogue in a new rule dictionary or add a rule-lookup tool.

For example, a missing-group error should identify that a categorical series column is required and that the available result contains a time column and two numeric measures. This is a description of the mismatch, not an instruction to apply a particular SQL transformation.

Remove unconditional alternative-chart advice. A suggested alternative must be checked for compatibility, or its unmet prerequisites must be stated explicitly. Compatibility alone does not establish that an alternative satisfies the whole user request.

### 2. Designer requests revised analysis

Add an `AnalysisRevision` Pydantic model alongside the analyst’s existing contracts. Give it three short, descriptive fields:

| Field | Written by the designer |
|---|---|
| `problem` | Why the current result cannot support the requested visualization. |
| `requested_change` | What the analyst should make possible, leaving the SQL implementation to the analyst. |
| `preserve` | Aspects of the task that must survive the change, such as measures, filters, time grain, and units. |

Expose it as a separate designer output, for example `request_analysis_revision`, alongside `deliver_design` and `ask_clarification`. It is an internal handoff, not a failed tool call or a user question.

Code attaches the actual diagnostic messages and relevant catalogue requirements from that run. The model should not reconstruct those facts from memory. A recommendation rejection is sufficient evidence; do not force the designer to spend all its check calls before requesting repair.

### 3. Analyst receives complete context and replies

Build a bounded repair prompt containing:

- Original user request and already answered clarifications.
- Existing dataset profile and permitted query context.
- Previous SQL and result-column metadata.
- Designer’s revision request, identified as internal feedback.
- Code-supplied diagnostic evidence and relevant chart requirements.

Reuse the previous-analysis plumbing, but distinguish internal feedback from user revisions. Load repair guidance only on repair runs, following the existing conditional revision/localization pattern.

The analyst chooses the query change, executes it through the existing guard and result checks, and uses its existing analysis summary and assumptions to explain what changed and any limitations. It may explain that the proposed change is unsupported or would change the meaning of the answer. It must not comply by silently changing the user’s question.

The original question remains authoritative even if the designer’s `preserve` list is incomplete. No extra raw-data access or full cross-agent conversation dump is required.

### 4. Designer receives the reply

Pass the revised analysis, the repair request, and the analyst’s explanation to the next design run. The designer must know what changed and why, so it does not repeat the original assumption.

Rebuild recommendations and validation context from the revised report. Do not reuse a passing check or recommendation computed from an older result.

## Recovery and stopping behavior

| Situation | Response |
|---|---|
| The specification can be corrected using the current result | Designer corrects it within the existing check/delivery budgets. |
| The result needs changing to answer the original chart request | Designer emits `AnalysisRevision`; runner invokes the analyst once and retries design. |
| A tool/output argument mistake is fixable by the current model | Use the existing bounded `ModelRetry` behavior. |
| An internal attempt budget is exhausted | Return through the technical failure path, with concrete diagnostics; do not manufacture a user clarification. |
| Genuine information or a decision is missing | Ask one specific question the user can answer. |
| Designer still fails | Retain the existing fallback, at most once for the request’s design work and within the overall budget. |
| Repair is requested again, including by the fallback | Enforce the spent repair budget in code. Do not start another analyst run. |

Keep unsupported operations and model-correctable errors distinct. In Pydantic AI, `ToolFailed` is handled as a failed result for function tools; it is not a special recovery result for output functions. Use the application’s explicit outcome/failure handling for exhausted output attempts.

A fallback model does not replace the repair mechanism: it also needs compatible inputs or the ability to request a revision.

## Persistence and consistency

Use the existing request store, with a small optional repair record on the request. Save the feedback, previous analysis, progress, revised report or failure, and whether the repair/fallback allowances were spent. Defaults must allow old requests to load unchanged.

Required behavior:

- Save the repair decision before invoking the analyst.
- Share model usage accounting across the original runs, repair, and fallback. Resume must not create a fresh allowance.
- Save the revised report and update the active analysis checkpoint together before design continues. Keep the previous report in the repair record for diagnosis.
- On resume, reuse a completed repaired analysis. An interrupted attempt must not create an unbounded restart path.
- Render and deliver from the same active analysis used to validate the final design. Invalidate any downstream saved output tied to the replaced analysis.
- Preserve already delivered parent artifacts; revisions create a new artifact version as they do today.
- Trace the feedback, analyst reply, outcome, and budget use under the request so Logfire shows the full exchange.

Do not claim exactly-once external model execution across a process crash. Persisted progress and attempt limits should make interruption behavior explicit and bounded.

## Implementation tasks

### Task 1: Improve diagnostic messages

- [ ] Update `designer/rules.py`, `recommend.py`, and `check.py` to report concrete expected-versus-actual mismatches.
- [ ] Keep existing rule IDs and reuse catalogue facts.
- [ ] Remove or qualify contradictory alternative-chart suggestions.
- [ ] Add focused tests for complete explanations and advice whose prerequisites are unmet.

### Task 2: Add the internal revision outcome

- [ ] Add the small shared `AnalysisRevision` contract in `analyst/models.py`.
- [ ] Extend `DesignReport` and designer outputs to distinguish repair from design and clarification.
- [ ] Update the designer rulebook: explain when to repair its own spec, request analysis, or ask the user.
- [ ] Pass repair feedback through analyst prompt construction without presenting it as a user instruction.
- [ ] Reuse the analyst’s existing checked query and delivery paths; explain the revision in its reply.
- [ ] Give the subsequent designer run the request and reply, with refreshed result facts.

### Task 3: Add one bounded repair to the runner

- [ ] Extend request models/storage for the optional repair record and persisted allowances.
- [ ] Handle the new outcome in `requests/runner.py` before rendering.
- [ ] Reuse existing analyst and designer entry points with shared usage accounting.
- [ ] Update the active saved analysis consistently and preserve its predecessor in the repair record.
- [ ] Enforce one analysis repair and one designer fallback across retries/resumes; do not recursively call the runner or create a general routing loop.
- [ ] Keep explicit user clarification and internal failure separate in the returned request outcome.

### Task 4: Correct exhausted-attempt handling

- [ ] Remove automatic technical-error-to-clarification behavior from both agent delivery paths.
- [ ] Preserve actionable failure details through reports, fallback, and the final outcome.
- [ ] Update tests that currently require a clarification after exhausted queries/checks.
- [ ] Ensure ordinary missing-information questions still pause and resume correctly.

### Task 5: Test the protocol and evaluate reasoning

Use `FunctionModel`/`TestModel` through `agent.override` for deterministic tests. Test the actual agent loop, not hand-built `RunContext` objects.

- [ ] An agent-requested repair reaches the analyst with the original question, previous SQL, metadata, and actual diagnostics.
- [ ] The designer receives the analyst’s revision explanation and uses the revised report for checks.
- [ ] Spec-only errors do not require analysis repair; successful ordinary requests add no calls.
- [ ] A model that repeatedly requests repair stops within a fixed bound, including during fallback and after resume.
- [ ] Crash/resume after a completed repair reuses the saved report; chart/table/artifact lineage stay consistent.
- [ ] Unsupported repair and technical exhaustion do not produce a generic user question.
- [ ] Genuine ambiguity still asks a useful question and preserves the answer on resume.

Add live end-to-end cases through the existing request/lead evaluation path. Designer-only cases with frozen analyst reports cannot demonstrate this interaction by themselves.

Include the reported Arabic request plus independently written English and Arabic cases for missing series, unsuitable aggregation, different units, excessive categories, a fixable spec mistake, and genuinely unavailable information. Include cases where the correct action is to decline the proposed transformation or ask for a decision. Keep some cases held out from prompt tuning.

Judge whether the agent preserves requested measures, filters, units, time grain, ordering, and meaning—not just whether `check_spec.ok` is true. Track repair choice, completion rate, false clarification rate, model requests, latency, and cost. Deterministic protocol tests prove routing; live cases measure the model’s ability to use it.

Compare baseline and proposed behavior on the same cases, models, and day. Require better recovery without reducing ordinary-task correctness or hiding dropped measures. Do not adopt a change solely because the reported Jeddah example passes.

### Task 6: Required validation and documentation

- [ ] Run `uv run pytest -q`.
- [ ] Run `uv run python -m evals.designer.run`.
- [ ] Run `uv run python -m evals.designer.agent.run`.
- [ ] Run the designer scale train/dev/heldout checks required by `AGENTS.md`; render the heldout set.
- [ ] Run `uv run python -m evals.lead.run` and the new end-to-end repair cases.
- [ ] In the browser, verify one recovered chart request, one normal request, and one real clarification. Check that internal diagnostics do not masquerade as user questions.
- [ ] Update `AGENTS.md`, the Phase 6 design, and relevant eval documentation to describe the bounded repair exception and outcome semantics.

No model or rulebook optimizer changes are part of this plan.

## Feasibility already checked

The installed versions are Pydantic `2.13.5`, Pydantic AI Slim `2.38.0`, and Pydantic AI Harness `0.28.1`.

An in-memory check confirmed that the existing SQL guard accepts a CTE with `UNION ALL` over the permitted table, and that a resulting time/series/value result can receive a valid multi-line specification. No new renderer or unrestricted SQL access is needed for that repair route. This was a hand-written feasibility check, not evidence that the model can autonomously choose and complete the repair.

## Pydantic guidance informing the plan

- [Official Building Pydantic AI Agents skill](https://github.com/pydantic/skills/blob/main/skills/building-pydantic-ai-agents/SKILL.md): typed outputs, focused context, and tests using model overrides.
- [Orchestration and Integrations](https://github.com/pydantic/skills/blob/main/skills/building-pydantic-ai-agents/references/ORCHESTRATION-AND-INTEGRATIONS.md): use tool delegation when the caller keeps control, or output functions/programmatic handoff when control moves elsewhere.
- [Multi-agent applications](https://pydantic.dev/docs/ai/guides/multi-agent-applications/): ordinary application code can coordinate agents and share usage accounting.
- [Tools Advanced](https://github.com/pydantic/skills/blob/main/skills/building-pydantic-ai-agents/references/TOOLS-ADVANCED.md): distinguish retryable model mistakes, completed failed tool results, and application exceptions.

The request-specific persistence and one-repair limit are design choices for this repository. Pydantic provides the mechanisms; it does not guarantee semantic correctness or prescribe this exact protocol.
