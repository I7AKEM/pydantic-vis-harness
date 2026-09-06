# Phase 1 lessons

The spec's exit test: roles, units, and measurement levels right at least nine times in ten,
seeded conflicts flagged every time, no measured statistic from a model, every test through the agent.

## Evaluation results

Run with `uv run python -m evals.profiler.run` on 2026-09-06 against the twelve committed cases.

| Date | Model | Role accuracy | Unit accuracy | Expected checks flagged | Time per profile |
|---|---|---|---|---|---|
| 2026-09-06 | openrouter:anthropic/claude-sonnet-4.6 | 0.958 average (10 cases at 1.00, sales and stores at 0.75) | 1.00 | 12 of 12 | 18 s average, 14 s to 27 s |

Measurement levels are asserted deterministically by `tests/test_eval_cases.py` and pass without a model.
Cost per profile was not measured by the runner; add token accounting to the report before the next phase.

## Where interpretation fails and why

- Two cases lost one column each out of four. In `sales`, the column `region` is expected to be a
  category, but the profiler labels place-name columns as geographic evidence, so the model has a
  reason to answer geography. The label rule and the expectation disagree; decide which is right and
  align one of them before the next run.
- In `stores`, one of four columns disagreed with the expectation. The runner reports only scores,
  so the column is not recorded. Extend the runner to print per-column mismatches.
- Every other case was fully correct, including Arabic headers and values, coded values with a brief,
  WKT boundaries, and wide data.

## How often a brief conflicts with the data

- Both seeded conflicts were flagged in every run: a unit given for a text column, and a code meaning
  for a code absent from the data. No false conflicts were raised on the ten clean cases.

## Whether review_profile catches errors the output check missed

- Not yet measurable from this run: the runner does not record how many interpretations were sent back.
  Add the send-back count to the report. The validator and the tool run the same checks, so the tool's
  value is in letting the model fix a draft before the validator forces a retry.

## What the plan got wrong, and what to carry forward

- DuckDB types a yes/no column as BOOLEAN at import; the plan assumed it stayed text.
- Starlette's multipart parser raises KeyError, not MultiPartException, when the content type is missing.
- pydantic-evals requires a dataset name.
- One output retry budget was shared by the structural retry and the check send-back; two are needed.
- A numeric column merely named like geometry must carry no statistics at all, not just no values.
- Background profiling and the chat's first question profiled every upload twice; concurrent runs now share one task.
- Near-unique text columns were labeled ordinal and coded; both labels now require repeated values.
- Codex runs cannot use uv or write under .git; the controller installs dependencies and commits.

## What to change before the analyst phase

- Record per-column mismatches, send-back counts, and token usage in the evaluation report.
- Resolve the place-name versus category expectation for columns such as `region`.
- Shield the shared profiling task from a joining caller's cancellation, and credit a joining caller's usage.
- Lift model-declared brief conflicts into the profile's warnings.
