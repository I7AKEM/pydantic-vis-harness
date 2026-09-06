# Phase 1 lessons

The spec's exit test: roles, units, and measurement levels right at least nine times in ten,
seeded conflicts flagged every time, no measured statistic from a model, every test through the agent.

## Evaluation results

Run with `uv run python -m evals.profiler.run` on 2026-09-06 against the twelve committed cases.

| Date | Model | Role accuracy | Unit accuracy | Expected checks flagged | Time per profile |
|---|---|---|---|---|---|
| 2026-09-06 | openrouter:anthropic/claude-sonnet-4.6 | 0.958 average (10 cases at 1.00, sales and stores at 0.75) | 1.00 | 12 of 12 | 18 s average, 14 s to 27 s |
| 2026-09-06 | openrouter:openai/gpt-5.4-mini, reasoning off | 0.979 average | 1.00 | 12 of 12 | 5.3 s average |
| 2026-09-06 | openrouter:google/gemma-4-31b-it:nitro, reasoning off (new default, chosen for speed) | 0.889 average (conflict_units 0.50, arabic 0.67, sales and stores 0.75) | 1.00 | 12 of 12 | 3.1 s average |

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
- CodeMode was removed from the lead after Phase 1: both lead tools were excluded from its sandbox, so `run_code` was a scratchpad costing a model turn. Reintroduce it when the analyst's query tool runs inside the sandbox.

## Profiler model benchmark

Run on 2026-09-06 with a scratch driver over the twelve cases, six at a time, reasoning switched off where the endpoint
allowed it. Time is seconds per profile. Requests counts model calls for all twelve profiles; the minimum is 24, so
anything above it is retries or send-backs. Round two routed open-weight models to the highest-throughput host with
OpenRouter's `:nitro` suffix.

Result: `openai/gpt-5.4-mini` is three times faster than Sonnet 4.6, seven times cheaper, and the only model with every
role right. Among open weights, Gemma 4 31b was the fastest of all models at 2.2 s but missed more roles; it was chosen
as the default for speed, with GPT-5.4 mini as the accurate alternative; Mistral Small, Qwen 3.8 27b, and GLM 5.3 Flash reached 0.917 to 0.958 but were slower or retried often.
The gpt-oss models could not produce the structured profile reliably at low reasoning effort. Hosting mattered more
than weights: the same DeepSeek and GLM models swung from unusable to usable depending on the host.

| Model | Mean s | Max s | Role | Units | Checks | Requests | Notes |
|---|---|---|---|---|---|---|---|
| anthropic/claude-sonnet-4.6 | 16.5 | 26.4 | 0.958 | 1.00 | 12 of 12 | 25 |  |
| anthropic/claude-haiku-4.5 | 7.1 | 8.6 | 0.958 | 1.00 | 12 of 12 | 25 |  |
| google/gemini-3.8-flash | 10.8 | 21.6 | 0.868 | 1.00 | 12 of 12 | 27 | reasoning could not be switched off |
| google/gemini-3.5-flash-lite | 5.0 | 7.2 | 0.958 | 1.00 | 12 of 12 | 31 | reasoning could not be switched off |
| openai/gpt-5.4-mini | 5.5 | 7.0 | 1.000 | 1.00 | 12 of 12 | 24 |  |
| openai/gpt-5.4-nano | 8.4 | 12.6 | 0.806 | 1.00 | 12 of 12 | 31 |  |
| deepseek/deepseek-v4-flash | 21.3 | 37.9 | 0.875 | 1.00 | 12 of 12 | 29 |  |
| qwen/qwen3.8-flash | 22.6 | 40.6 | 0.479 | 1.00 | 6 of 12 | 20 | 6 of 12 profiles failed |
| z-ai/glm-5.3-flash | 60.6 | 90.2 | 0.604 | 0.92 | 8 of 12 | 17 | reasoning could not be switched off; 4 of 12 profiles failed |
| mistralai/mistral-small-2603 | 5.5 | 9.2 | 0.917 | 1.00 | 12 of 12 | 30 |  |
| google/gemma-4-31b-it:nitro | 2.2 | 4.5 | 0.889 | 1.00 | 12 of 12 | 26 | open weights, throughput-routed host |
| meta-llama/llama-4-maverick:nitro | 12.3 | 19.4 | 0.896 | 1.00 | 12 of 12 | 21 | open weights, throughput-routed host |
| qwen/qwen3.8-27b:nitro | 8.0 | 10.9 | 0.917 | 1.00 | 12 of 12 | 30 | open weights, throughput-routed host |
| deepseek/deepseek-v4-flash:nitro | 46.3 | 90.2 | 0.583 | 0.92 | 7 of 12 | 35 | open weights, throughput-routed host; 5 of 12 profiles failed |
| minimax/minimax-m3:nitro | 9.9 | 16.6 | 0.479 | 1.00 | 6 of 12 | 42 | open weights, throughput-routed host; 6 of 12 profiles failed |
| openai/gpt-oss-120b:nitro | 1.8 | 2.8 | 0.417 | 0.92 | 5 of 12 | 31 | open weights, throughput-routed host; lowest reasoning effort (off refused); 7 of 12 profiles failed |
| openai/gpt-oss-20b:nitro | 5.5 | 8.2 | 0.100 | 0.90 | 1 of 10 | 52 | open weights, throughput-routed host; lowest reasoning effort (off refused); 9 of 10 profiles failed; 2 runs raised |
| z-ai/glm-5.3-flash:nitro | 10.8 | 37.0 | 0.958 | 1.00 | 12 of 12 | 44 | open weights, throughput-routed host; lowest reasoning effort (off refused) |
