# Phase 5 lessons: the reviewer and the team

Filled in as the phase runs; the headings are the spec's section 13. Numbers from 2026-09-15 unless dated.

## Exit test

2026-09-15, agents on the LiteLLM proxy (`google/gemma-4-31B-it-qat-w4a16-ct`), reviewer on `Qwen/Qwen3.8-27B`
with reasoning off.

- Unit suite 1571 passed; model-free designer evaluation 40 of 40.
- Agreement with human verdicts: not run yet. `evals/reviewer/labelled/review.html` holds 89 charts from the
  evaluation team's run and waits for the owner's verdicts (60 needed).
- Lead evaluation on the proxy: 13 of 18 cases with the reviewer (10 of 18 on the ledger branch without it, same day,
  same model); false questions 2; 207 requests for 26 turns (159 without the reviewer).
- Analyst evaluation on the proxy: 52 of 71 after the ledger and the clarification fix (48 before the fix).

## The rules ledger, applied

- Units. One list of generic count markers (`count`, `number`, `عدد`) in `vis_agent/units.py`, used by the profiler's
  placeholder validator, the analyst's query step, and the resolver. A noun the data names (`person`, `شخص`, `نسمة`)
  is a real unit and stays beside the KPI number and in the axis title. A share declares its own scale
  (`share_scale_declared`, error). In the evaluation team's run the unit was the string "null" 1452 times, `person`
  237, `count` 205.
- The analyst's clarification tool. The proxy's Gemma filled the tool's `question` argument with the caller's own
  question, word for word, and repeated it on every retry (8 of 71 analyst cases ended that way). The argument is
  now `ask`, its description says what it must never hold, and an echo is refused with the way out named. Two of
  three replayed cases then answered with SQL; 7 of 71 still echo three times and end with the reason.
- The same code on OpenRouter's Gemma: analyst 70 of 71, lead 17 of 18 (one comparison run each, the day the ledger
  landed). The proxy's quantised Gemma asks about units, translation, order, and confirmations the rulebook forbids:
  12 false questions in 71 analyst cases, 9 questioned turns in 26 lead turns. That is the model, not the ledger.
- The card. The lead shows the card built by code: in the browser check every reply carried the picture, the summary,
  the explanation, the table with its row count, the review line, and the IDs, in Arabic.

## The reviewer

- Seats on the proxy: only `Qwen/Qwen3.8-27B` reads a picture; `MiniMaxAI/MiniMax-M2.5` and `zai-org/GLM-5.2-FP8`
  refuse images, the unquantised Gemma engine is down. Reasoning must be sent off explicitly
  (`openai_reasoning_effort: none`): 135 to 213 s per picture with it on, 7 s with it off. Two of 26 reviews in the
  lead run hit the 60 s limit under load and delivered unreviewed with a warning, as designed.
- Agreement per seat and per language: pending the owner's verdicts.
- The reviewer judged against the original question and faulted a chart the caller had redirected ("no hospital
  column: draw it by city") twice, R-3 owner user. It now reads the questions the team asked and the caller's
  answers, and a finding only the caller can settle (owner user or none) no longer sends the chart back; it stays
  on the card as an open finding.

## The review round

- Live, before that fix: two rounds on the hospital case, both R-3 owner user, delivered with the finding open and
  the warning. After the fix: pass, no round. A send-back the designer could act on was not observed in the 26-turn
  lead run (the proxy Gemma's charts passed Qwen's review, or the review timed out); the eight runner tests cover
  the mechanics, including the crash-and-resume inside a round.
- Cost: one review per rendered chart, about 7 s and one request on Qwen; a round adds one design run and one review.

## The evaluation team's rerun

Pending: ask for a rerun of the 283 cases against `feat/phase-5-reviewer`.

## Left for later

- The proxy model's presentation questions (units, language, order, and the designer's "table or dual axes?"): a
  code guard on the clarification text, or a stronger local seat for the analyst and the designer (Qwen with
  reasoning off), measured with the analyst and lead evaluations on the proxy.
- Echoed questions that survive the refusal (7 of 71): the run ends with the reason; a stronger seat is the fix.
- `نسمة` displays as `شخصًا` or `أشخاص` through the indicator's noun table; the owner decides whether it should stay
  as written.
- The agreement exit test and the seat choice, after the owner's verdicts; then the DSPy round on the reviewer's
  rulebook.
- The lead sometimes answers a "table" request with `answer_question` (no picture, so no review); the browser
  check's long-header table therefore exercised the card, not the drawn table.
