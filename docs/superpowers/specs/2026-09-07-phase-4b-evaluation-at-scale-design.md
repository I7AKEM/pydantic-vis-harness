# Phase 4b: Evaluation at scale

Two hundred real questions from the dev corpus, a measured baseline for Hijri and Arabic edge cases, and DSPy
used to catch the designer's errors and rewrite its rulebook where the measurements allow. It follows the Phase 4
design (docs/superpowers/specs/2026-09-07-phase-4-chart-designer-design.md, section 13) and the Phase 1 pattern
for instruction optimization (docs/phase-1-lessons.md).

## 1. Purpose

Phase 4 met its exit test on thirty-one questions judged by one person. That set is small, three quarters of it
is English, and it holds no Hijri dates. The owner's rulings for this phase, given on 2026-09-07:

- Hijri is measured first, as a baseline, and fixed afterwards in a round scoped by what breaks.
- The chart Insightor chose for a question is not a label. It is kept as metadata only.
- DSPy is for avoiding errors and for optimizing the designer's instructions, if the measurements show it pays.

Exit test:

1. The 200-case set runs end to end with every automatic score recorded, and the held-out forty are judged by a
   person with the Phase 4 rubric; the designer scores at least seven in ten on them.
2. The Hijri and Arabic edge cases have a baseline table: for every seeded case, which stage broke and how.
3. The optimized rulebook is adopted only when it beats the seed rulebook on the dev split and on the held-out
   split on the automatic scores, and does not lower the judged sample; otherwise the seed stays and the lessons
   say why.

## 2. Scope

In:

- Selecting two hundred datasets and questions from the dev corpus, by coverage, with the reason per case.
- Seeding Hijri and Arabic edge cases from real corpus files, labelled as seeded.
- Capturing the analyst's reports once and committing them as the fixed inputs, as Phase 4 did.
- Splits: train, dev, held-out, disjoint by dataset.
- The runner extended for splits and for the reference chart list of section 6.
- The DSPy optimizer for the designer's rulebook, in the Phase 1 pattern.
- The Hijri baseline measurement and one bounded fix round.
- Lessons.

Out: map charts (Phase 7), the reviewer (Phase 5), changes to the designer's tools or to the spec language,
Insightor's charts as labels.

## 3. The corpus

`/Users/muhammad/Documents/NACI/Insightor/insightor_POC/exports/visualization_csv_corpus_dev_2026-09-01_500/`:
five hundred query-result CSVs with a metadata sidecar each. 496 datasets carry a real producing question (826 of
834 questions are Arabic), the orchestrator's intent where it was persisted (single_value 93, comparison 55,
ranking 18, composition 18, table 7, map 3, distribution 1), the requested chart type, and the chart Insightor
chose. 67 files have temporal columns, all Gregorian; 54 have Arabic categorical columns; none holds a Hijri date,
a Hijri month name, or Arabic-Indic digits. The profiler's corpus sets came from the same export family, so the
selection excludes any dataset already in `evals/profiler/corpus_cases` or `corpus_train`.

## 4. Selecting two hundred

`evals/designer/agent/corpus_tools/select.py` reads `manifest.jsonl` and picks, deterministically:

- Only datasets with a question, a parsed CSV under the upload limit, and no geometry-only content; map datasets
  are excluded.
- Coverage first: every orchestrator task, every result shape (one number, one column, category by measure,
  time by measure, category by group by measure, wide), row-count buckets, Arabic categories, temporal columns,
  nulls and negatives and long text, then the rest by a fixed seed.
- One question per dataset: the first occurrence's question. The Insightor chart, the requested type, and the
  orchestrator task go into `decisions.json` as metadata.
- Language: the corpus is almost entirely Arabic; the set keeps at least twenty English questions by including
  the analyst's English cases already captured in Phase 4.

Output: `evals/designer/agent/scale/cases.json` and `decisions.json`, with every case's selection features.

## 5. Seeded edge cases

Twenty to thirty cases derived from real corpus files by `corpus_tools/seed.py`, deterministic, saved under
`evals/designer/agent/scale/seeded/` with the transformation recorded in `decisions.json`:

- Hijri dates in three written forms, converted from Gregorian columns with the Umm al-Qura calendar
  (`hijridate`, the maintained successor of `hijri-converter`, added to the optional `optimize` group): `1447-03-12`, `١٤٤٧/٠٣/١٢`, and
  `12 ربيع الأول 1447`. Questions ask for monthly and yearly Hijri buckets.
- Arabic-Indic digits in a measure column and in category labels.
- Categories with diacritics, tatweel, mixed direction (`مدينة الرياض (Riyadh)`), and labels over forty
  characters.
- A Hijri year column beside a Gregorian date column.

These cases are in the set but flagged `seeded: true`; the exit test's seven in ten is computed with and without
them.

## 6. The reference chart without Insightor's label

The automatic `ChartAccepted` needs an acceptable list per case. Without a human label per case, the list is the
Phase 3 rules' judgment: every candidate within one point of the top and not negative, for the intent the
designer declared in its design, plus the orientation and pie or donut swaps. This measures agreement with the
rules, not correctness; correctness is the judged held-out forty. `IntentPlausible`, a soft score, compares the
designer's intent with the orchestrator task when one was persisted (single_value to share or one number,
comparison to compare, ranking to rank, composition to composition, distribution to distribution).

## 7. Splits and the runner

`splits.json` assigns every case to train (120), dev (40), or held-out (40), disjoint by dataset, seeded and
Arabic cases spread evenly. The runner gains `--split`, reads the scale set through `--cases`, and keeps
`--render`, `--judge`, and `--judgments` as they are. The held-out split is never used by the optimizer.

## 8. DSPy in the Phase 1 pattern

`evals/designer/agent/optimize_instructions.py`, mirroring `evals/profiler/optimize_instructions.py`:

- A `dspy.Signature` whose input is the designer's prompt JSON as `build_prompt` writes it and whose outputs are
  the spec text and the explanation. The instructions are the rulebook plus the generated grammar and catalogue,
  exactly what the agent reads.
- The metric runs `check_spec` on the spec and turns violations into feedback text, then scores `Passed`,
  `ChartAccepted`, `LanguageRight`, and `BindingRight` as the runner does. The feedback is what GEPA reflects on.
- Task model Gemma with reasoning off at temperature zero; reflection model Sonnet 4.6; light budget first.
- The single-shot program cannot call the tools the runtime agent calls, so it sees `recommend_charts` only
  through the metric. The optimized text is pasted into `rulebook.md` and measured with the real runner, tools
  and all, on dev and held-out before it is kept.

## 9. The Hijri baseline and the fix round

The seeded cases run through profile, analyse, design, and render. For each, the report records the first stage
that broke: the profiler read the Hijri column as text or ordinal; the analyst could not bucket it and asked, or
bucketed wrongly; the designer had no time role and drew categories; the picture ordered the months wrongly. The
table goes into the lessons. Then one fix round, scoped by the table, in the order the pipeline runs: a
measurement level for Hijri patterns in the profiler (a DuckDB query over the values), a rulebook line for the
analyst on bucketing Hijri strings, and in resolving the ordering of Hijri labels. Anything beyond that waits.

## 10. Tests

- Selection is deterministic from a manifest fixture and honours every exclusion.
- Seeding converts known dates correctly (2024-03-11 is 1445-09-01) and writes the three forms.
- Every case's report validates; splits are disjoint by dataset; the reference list builds without a model.
- The optimizer's metric scores hand-built predictions without a model.
- The Hijri fix round adds its own tests per stage.

## 11. Files

- Create: `evals/designer/agent/corpus_tools/{select.py, seed.py, capture.py}`,
  `evals/designer/agent/scale/{cases.json, decisions.json, splits.json, judgments.json, README.md, reports/, seeded/}`,
  `evals/designer/agent/optimize_instructions.py`, `tests/designer/test_scale.py`, `docs/phase-4b-lessons.md`.
- Modify: `evals/designer/agent/run.py` (`--split`, `IntentPlausible`, the reference list), `pyproject.toml`
  (`hijri-converter` in the optimize group), `README.md`, `AGENTS.md`.

## 12. Decisions taken before the plan

1. Insightor's chart is metadata, never a label.
2. The reference list is the rules' judgment for the designer's own intent; correctness is judged by a person on
   the held-out forty.
3. Hijri is seeded from real files, since the corpus has none, and measured before anything is fixed.
4. DSPy stays offline; Pydantic AI stays the runtime; the optimized text is kept only if the real runner agrees.
5. The Phase 4 thirty-one-case set stays as the smoke set that runs before every merge.

## 13. Effort

Four to six days: one for selection and seeding, one for capture and the cases, one for the runner and the
judging, one for the optimizer, one or two for the Hijri baseline and fix round, half a day for the lessons.
