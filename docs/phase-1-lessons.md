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

## Dry run over the 500-file Dev CSV corpus (2026-09-06)

The deterministic stage ran over every CSV in the Insightor dev corpus with no model call, measuring the prompt the
profiler would send. Median prompt 2,566 characters, 99th percentile 6,960, maximum 19,721 for a 28-column file. Row
count never mattered: a 3.66 million row file produced a 2,366 character prompt in 4.5 s. No cell value longer than
120 characters reached a prompt; 32 columns holding values up to 96 KB were excluded entirely. Two changes followed:
`pytz` was added because DuckDB needs it to return timezone-aware timestamps (7 files failed without it), and columns
past the first 40 now send counts and types only, so a 100-column upload cannot triple the prompt. The 134 MB file
is over the 20 MB upload limit and never reaches the profiler.

## Corpus evaluation: fifty real files (2026-09-07)

`evals/profiler/corpus_cases` holds fifty CSVs from the Insightor corpus, chosen for spread over shapes, row counts,
edge cases, and Arabic content, each with a brief built from its sidecar's question, SQL, and chart type. Expected
roles: Sonnet 4.6 and GPT-5.4 mini agreed on 183 of 195 columns; the 12 disagreements and 6 agreed labels that broke
the place-name rule were decided by the rules in `decisions.json`. Run with
`uv run python -m evals.profiler.run --cases corpus_cases --mismatches`. Scores below are against the final
expectations; time is seconds per profile with six profiles in flight.

| Model | Role accuracy | Columns wrong | Time | Notes |
|---|---|---|---|---|
| google/gemma-4-31b-it:nitro (default) | 0.979 | 4 of 195 | 4.6 s | open weights, fastest host |
| qwen/qwen3.8-27b:nitro | 0.908 | 27 of 195 | 17.6 s | open weights, fastest host |
| mistralai/mistral-small-2603 | 0.808 | 35 of 195 | 12.4 s | open weights, Mistral's host |
| openai/gpt-5.4-mini | 0.900 | 14 of 195 | 7.3 s | closed; one of the two label sources |

Qwen's loss is mostly one file: it produced no usable profile for the 19-column traffic file, which counts as 19
wrong columns; on the other 49 files it was close to Gemma but three times slower.

What each model gets wrong, from the mismatch lists: Gemma flips ordered levels named in words (Poor to Rich) to
category and a 1 to 10 sequence to measure. GPT-5.4 mini and Mistral label place names as plain categories, which is
most of their loss, and both call coordinates stored as text just text. Every model's own place-name confusion is
avoidable: the deterministic place-name hint only recognises a few English words, so widening it to municipality,
port, district, and the Arabic equivalents would give every model the same evidence. Small models also vary between
runs on borderline columns; Gemma's two runs differed on three columns.

## Instruction optimization with DSPy (2026-09-07)

The profiler's instructions were written with Sonnet in mind and run on Gemma 4 31b. DSPy GEPA rewrote them for
Gemma using `evals/profiler/corpus_train`, 150 more corpus files labelled by majority vote of Sonnet 4.6, GPT-5.4 mini,
and Opus 5 plus the rules in that directory's `decisions.json`, split 110 train / 40 dev. The task model was Gemma with
reasoning off and temperature 0, the reflection model Sonnet 4.6. Two budgets ran; the light run scored 0.994 on dev
against 0.989 for medium, so its text was pasted into `PROFILER_INSTRUCTIONS` unchanged. Pydantic AI remains the
runtime; DSPy is an offline tool in the optional `optimize` dependency group, run with
`uv run python -m evals.profiler.optimize_instructions`.

Measured with the real runner, same code before and after, role accuracy and seconds per profile:

| Set | Before | After |
|---|---|---|
| Held-out 50, never seen by the optimizer | 0.968, 4.9 s | 0.992, 3.0 s |
| Hand-made 12 | 0.889, 4.6 s | 0.958, 3.4 s |
| Training 150 | 0.946, 5.8 s | 0.983, 3.2 s |

What the new text adds: integer years and period strings are ordinal, time is only a native date type, a set
geographic hint means geography while nationality words stay category, all-null columns are unknown. Remaining
misses: ordered levels written in words still flip to category on some files, a 1 to 10 sequence reads as measure,
and `registry_location` (traffic office names) follows the place-name hint to geography where the label says
category. Small models also vary by run: allow one column either way between runs.

Two other changes landed with this step: the profiler retries once when a model request stalls, since one stall used
to cost the whole 90 s timeout and a partial profile, and `evals/profiler/corpus_tools` holds the selection,
labelling, and merging scripts that built both corpus sets.
