# Phase 7: the program caller and the query result

Status: design, 2026-09-15. Baseline commit 8f5fd20. Companion: the analyst–designer repair plan
(`docs/superpowers/plans/2026-09-09-analyst-designer-repair.md`), whose Task 4 (exhausted attempts are
technical failures, never manufactured questions) should land before or with this phase.

## 1. The problem

The vis agent was built as a data analyst serving a person in a chat: every specialist reasons from the
question, the column facts, and the brief as hints, and can pause the request to ask "the caller" one
question. Phase 6 added the agent channel and a two-question cap on top of that design without telling the
specialists anything new. So when another program (Insightor's data agent) sends a finished query result
with a brief, the vis agent behaves like a data agent talking to a human: it re-opens definitions the
producer already closed, asks the program to choose a presentation, asks it to confirm what the brief's SQL
states, and the cap turns that into a failed request.

Evidence, 2026-09-15, as the data agent over the agent channel:

| Run | Result |
|---|---|
| 8 hand-built briefs, OpenRouter Gemma | charts in 6 to 15 s; caveats never on the picture; the enriched question ignored unless repeated as the request text; a program-facing answer with a leaked "thought" token; `not_reviewed` everywhere |
| 40 seeded corpus cases with briefs, proxy Gemma qat | 17 charts, 23 failed at the cap; 27 asked; 12 asked a presentation choice, 10 echoed the question into the ask tool after an answer, 10 re-asked verbatim, 4 asked the caller to confirm the brief, 8 had a real gap, 4 caught a data-quality problem |

Two smaller defects came out of the same runs: DuckDB typed a gender column of only "F" as BOOLEAN, and units
and code labels came out in English on Arabic charts because nothing states their language.

## 2. Where the gap lives

| Behaviour | Seam |
|---|---|
| presentation questions, confirmations of the brief | `AnalystPrompt` and `DesignerPrompt` carry no caller; the rulebooks say "ask the caller" and the model reads a person; nothing tells the analyst that `brief.query` defines the table |
| echo and verbatim repeat | the output union lets the model end a run by "asking"; `ask_clarification` checks only for an empty string; the revise rules say "never ask again" and nothing enforces it |
| failure at the cap | `_pause` has one branch at `MAX_QUESTIONS`: `failed` |
| "F" is BOOLEAN | `read_csv` auto types include BOOLEAN |
| English units, raw F and M | `ColumnSemantics.unit` has no language rule; code meanings are optional |
| caveats not on the picture, lineage without the query | no designer rule uses caveats or the subtitle; `Lineage` holds a fingerprint only |
| "thought" leak, prose for programs | the lead sets no `thinking`; `/agents/ask` returns text only |

## 3. What Pydantic AI prescribes

Per-run context is dependency injection plus dynamic instructions (`@agent.instructions` reading
`RunContext.deps`), the mechanism the revise and Hijri blocks already use. A wrong output is corrected with
`ModelRetry` from the output function or an output validator, counted against `retries={"output": N}`. A
finished-and-failed tool call is `ToolFailed`, which the model sees and adapts to. Programmatic hand-off is
"application code deciding which agent runs next", which the runner is. Asking an external party and
resuming is a deferred tool (`CallDeferred`, `DeferredToolRequests`, `DeferredToolResults`, resume with
`message_history`); the vis agent restarts the analyst instead, which is where the echo comes from. A2A is
the separate `fasta2a` project.

## 4. Decisions

1. The specialists are told who is asking. `Caller.role` maps the channel's `agent` kind to `program` and
   the chat and terminal to `person`. Both prompts carry `caller`; a per-run instruction block for programs
   says: decide presentation yourself and record it under assumptions, never ask to confirm the brief, ask
   only when the columns cannot answer. A person's runs are byte-identical to today.
2. The specialists are told what the file is. When the brief carries `query`, a per-run block tells the
   analyst that the table is that query's finished result, the SQL defines every column, the WHERE and
   LIMIT clauses are its scope, and nothing in it is re-derived or confirmed. The profiler reads column
   meanings and code meanings from the query. The designer's titles follow the analyst's meanings and
   assumptions, not the question's wording.
3. The ask tools are guarded in code. A question equal to the caller's question, or to one already answered,
   is sent back with `ModelRetry` naming the two legitimate reasons. A model that keeps echoing ends within
   the output retries; the request then fails as a technical failure, it does not wait.
4. The repair plan's Task 4 is adopted, not repeated: spent budgets are failures, not questions.
5. CSV import never infers BOOLEAN. Single-letter codes stay text; yes/no text is still labelled by the
   measurements' boolean vocabulary. The profile version rises so cached profiles rebuild.
6. Units and code meanings follow the caller's language, and a unit the brief declares is kept: a profiler
   rule, and an analyst check that fails when a measure taken from a column with a declared unit drops it.
7. The subtitle carries the definition or scope when it narrows the question; the lineage carries the
   brief's source, query, pull time, and producer.
8. The lead runs with thinking off; the ask route returns the requests it made beside the prose.
9. A program-caller evaluation set built from the corpus briefs that carry a query scores "answered without
   a question", on OpenRouter and on the proxy.

Not changed: the two-question cap, which is right once the questions are legitimate; and "the brief is
context, never fact", which now reads "use it, do not verify it".

## 5. Later

Turning `ask_clarification` into a deferred tool so an answer resumes the same run (the documented shape)
is the durable fix for the loop if the guard and the program rules leave it above the exit line. The
designer's missing-detail case becomes a hand-back to the analyst through the repair plan. A2A through
`fasta2a` wraps the runner once its statuses are exposed as task states. Caption rendering beyond the
subtitle is renderer work.

## 6. Exit test

On the program set (`evals/analyst/program`), on the proxy model: at least 90% of cases answered without a
question, no echo and no verbatim repeat in any run, no new failed error checks against the seed set, and
the ordinary analyst and lead evaluations unchanged. Recorded in `docs/phase-7-lessons.md`.
