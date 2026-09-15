# Indicator cards: implementation, tests, and evaluation

Status: implementation and validation runs complete; broader response-control and legacy-analysis
limitations remain. See `docs/indicator-validation-2026-09-15.md` for the evidence and release boundaries.

Based on the review of `20260913-183937` and the code at `2bcc745`. The report identifies its runtime as `53c179b`; the intervening changes do not implement indicator support.

## 1. Outcome and design decisions

When a user asks for a total, count, average, rate, or an explicit KPI, the existing designer can deliver an `indicator` artifact. It can contain one prominent metric or several independent metric cards, with the labels and supporting values needed to interpret them.

**The question determines the presentation. One result row establishes eligibility, not intent.** A one-row breakdown, an entity lookup, and a one-row statistical summary can need different presentations.

Decisions for the first implementation:

- Add `indicator` to our catalogue and render it inside the existing GPT-Vis adapter, using its installed Node canvas dependency. The pinned `@antv/gpt-vis-ssr@0.3.8` registry has no indicator type. Ant Design's React `Statistic` is not part of this renderer. No package upgrade or second renderer is needed.
- Use the normal designer, check, render, and artifact path. Remove the runner's single-number design bypass. Do not add an automatic card path ahead of the designer.
- Support **one to six cards in one artifact**, each with an explicit primary column, context columns, and supporting numeric columns. Six is an initial layout limit; larger summaries use a table with an explanation. Never silently truncate to six.
- Require exactly one complete result row for an indicator. SQL selects, filters, aggregates, and computes comparisons. The renderer never selects the first/latest row, sums rows, or calculates a percentage or delta.
- Keep numbers-only and explicit table requests on `answer_question`. “Total” or “single row” alone does not mean numbers-only.
- Preserve the existing agents, tools, budgets, artifact model, and saved step order. One composite indicator still has one spec, PNG, HTML page, and artifact version.
- Do not include gauges, targets, progress rings, sparklines, or automatic red/green trend judgments in this release. An already computed change can be a metric; its direction is not automatically good or bad.

### Evidence to preserve as regressions

The report contains 35 one-row results: 16 with one numeric column, 12 with a numeric column plus a label, and seven with multiple numeric columns. These are a discovery set, not 35 confirmed KPI requests.

| Case | Required distinction |
| --- | --- |
| `analyst--visitors_2024_total` | A total of 1,458 is eligible for an indicator. |
| `analyst--discounted_percentage` | Emphasize the 48% share; retain the count of 480 as support. |
| `analyst--unpaid_share_overall` | Emphasize the unpaid share; retain numerator and denominator counts. |
| `analyst--top_store_by_orders` | Preserve the winning store's identity. A large order count alone does not answer “which store.” |
| `vizcsv-5a978d632cfd754c` | A NULL percentage from a zero denominator means unavailable, not zero. |
| `vizcsv-ae79cdc7d8e77066` | Preserve the nonzero share of approximately 0.000539399%; retain supporting counts. |
| `vizcsv-c2315009d8035563` | Arrivals and departures can be separate cards when the question asks for those two totals. |
| `vizcsv-8001e09f5f45bb3f` | A total plus age buckets must retain the requested breakdown. A single total card is incomplete. |
| `vizcsv-f91723bce2abb15b` | An explicit request for count, mean, deviation, and z-score cannot silently lose fields. |
| `vizcsv-6c8cc1666963d616` | A single period-wide value cannot satisfy a request for one result per year. |

The relevant current gaps are `requests/runner.py::single_number`, the table preference in `designer/rulebook.md` and rule S13, the missing chart type, and evals that can count artifact existence or rules agreement as success without proving that the requested metric was shown.

## 2. Typed card contract

Add `IndicatorCard` to `vis_agent/designer/models.py`:

| Field | Type | Meaning |
| --- | --- | --- |
| `value` | `str` | Exact result column holding the primary metric. |
| `context` | `list[str]`, default empty | Exact columns identifying the entity, location, period, or other scope. |
| `support` | `list[str]`, default empty | Exact columns holding supporting numeric results. |
| `format` | `str \| None` | Existing number-format grammar, applied only to this card's primary metric. |

Add `Spec.cards: list[IndicatorCard]`, default empty. For `indicator`, require one to six cards and an empty ordinary `bind`. Other chart types reject `cards`. Keep old specs loadable with unchanged defaults.

Extend the existing line grammar with card records; do not introduce a YAML parser. A record starts with `- value`; each following four-space line is `context`, `support`, or `format`. Repeated context/support lines append columns. Duplicate value/format declarations and unknown fields are errors with source line numbers.

```text
vis indicator
title Unpaid violations
description Share of violations that remain unpaid
cards
  - value unpaid_share
    support total_unpaid
    support total_all
```

```text
vis indicator
title Passenger totals
description Arrival and departure totals for the reported period
cards
  - value arrivals
    context period
  - value departures
    context period
```

Labels come from the bound columns' metadata and context cells. Literal metric values, formulas, denominators, and manually entered deltas are not accepted in card specifications. Card order is explicit; source column order never determines the primary metric.

### Deterministic validation

- Require `result.row_count == len(result.rows) == 1`, matching result/metadata columns, unique column names, and matching cell counts. A bounded preview of a larger result is not a scalar.
- Primary/support columns must be `measure` or `share`, holding finite numeric values or NULL. Reject booleans, numeric-looking strings, identifiers, and nonfinite values. NULL is allowed explicitly; it must not pass merely because an all-null column appears numeric to the shape helper.
- Context accepts category, ordinal, time, geography, and identifier columns. Preserve their text, including Hijri periods and Arabic digits.
- Every result column must appear as a primary, context, or support binding somewhere in the indicator. This conservative first version avoids hiding scope or auxiliary results. A table remains available when full coverage makes cards unsuitable.
- Reject duplicate primary cards, duplicate columns within a context/support list, and overlap of value/context/support within a card. Shared context across cards and a metric supporting another card are allowed.
- Reject axes, sort, row limits, folding/Other, percent stacking, legends, and other inapplicable settings. Explicitly enumerate indicator capabilities instead of inheriting all grammar keys as supported.
- Allow title, subtitle, description, language, theme, dimensions, direction, digits, background, and a single accent color. Per-card formatting cannot silently change a column's unit. Reject top-level `format` on indicators because cards may have different units.
- These checks establish structural fidelity. They cannot prove that SQL answered every part of the question; that requires semantic evals and analyst correctness.

## 3. Selection, percentages, and missing values

### Selection rules

Add `summary` to the shared `Intent` literal. It means reporting one or several headline measurements. The designer already reads the question and chooses intent; no additional intent agent or routing stage is needed.

| User request / result | Intended behavior |
| --- | --- |
| “What is the total?” with one valid aggregate | `draw` followed by an indicator. |
| “Just the number,” “no chart,” or “table only” | `answer_question`, with the requested answer/table. |
| Explicit KPI with one primary metric plus counts | Indicator with counts as support. |
| Several independent totals in one row | Several cards, preserving each metric's own unit. |
| “Which store is highest?” | Identity must remain prominent; a table/entity answer is acceptable. An indicator must include the entity context. |
| “Total by city,” a time trend, distribution, or age breakdown | Preserve groups or periods; do not collapse to a single KPI. |
| Explicit KPI over multiple raw rows | Analyst computes the requested aggregate in SQL first. No implicit renderer aggregation. |
| One-row result missing requested years or categories | Disclose the missing coverage; do not present it as a complete answer. |
| Ambiguous KPI definition or a missing target needed by the question | Ask only for information actually needed to answer. No presentation-preference question for an otherwise clear total. |

Give the catalogue entry empty flat roles/fields and document its nested `cards` contract explicitly. Update the catalogue invariant that currently treats only tables as having empty roles. Keep this as a small indicator-specific branch.

Add an optional `cards` field to `Candidate`. Recommendation can propose a fully bound card when there is only one numeric metric, with all label columns as context. With several metrics, return indicator eligibility and an explanation that the designer must choose primary/support bindings from the question; leave the proposed cards empty. Do not choose the first numeric column. Keep table and compatible comparison candidates available.

Replace S13's unconditional one-number table preference with a summary-aware indicator preference. Shape alone must not override a trend, comparison, explicit table request, or the raw question in favor of a brief's suggested chart.

### Percentage semantics

Keep new percentage results in the analyst's existing 0–100 convention, computed in SQL and labeled `%`. Display formatting adds a suffix; it never guesses a scale from the value or multiplies by 100.

Use `kind="measure", unit="%"` for percentage change, including negative changes and changes above 100. A part-of-whole share is `kind="share"`. Update percent-format validation so a correctly labeled percentage change does not produce a false “not a share” warning.

Add a backward-compatible `ResultColumn.partition_by: list[str] | None = None`, applicable only to shares:

- `None`: no claim that returned shares form a complete partition; scalar shares, partial selections, and independent row rates use this.
- `[]`: the returned column is a complete partition across the whole result.
- A list such as `["year"]`: shares form a complete partition within those result columns.

Implementation finding: the live small model supplied `[]` on ordinary measure columns and repeated it
after validation feedback. Normalize that inapplicable empty annotation to `None`, like placeholder unit
metadata; reject nonempty partition groups on non-shares. The meaning of `[]` on an actual share stays strict.

Validate referenced grouping columns and completeness of the materialized result. Run `shares_add_up` only for a declared complete partition, using DuckDB aggregation over the declared groups. New `%` partitions must total 100; a legacy fraction partition can total 1 only when its metadata explicitly identifies fractions. An unknown scale produces a metadata warning rather than a guessed target. Do not guess the denominator group from the first category column. Keep legacy reports loadable; absence of this metadata does not establish completeness. Existing pie/donut/treemap suitability checks still apply.

Legacy fraction-valued results remain unscaled. Unitless `0.34` does not become `34%`, and `0.34%` remains `0.34%`. If the percentage basis is missing, preserve/disclose that gap; do not invent a denominator. A new request needing a percentage must obtain it from the analyst's SQL.

### Value and display states

| Input | Display / outcome |
| --- | --- |
| `0` | A real zero, with its unit. |
| `NULL` in a valid one-row result | Localized “Unavailable”; keep scope and supporting values. Do not invent the cause. |
| Mixed valid and NULL metrics | Render each card's own state; do not discard the whole row. |
| No result rows | No indicator. Preserve the existing empty-query handling and its explicit outcome. |
| Query/model/renderer failure | Existing failure or disclosed table fallback, never an “Unavailable” success card. |
| Small nonzero number | Increase default precision or use scientific notation so it is visibly nonzero. |
| Explicit rounding or compact formatting | Preserve the unrounded value in secondary text when rounding would conceal it, including a nonzero becoming zero. |
| Integer beyond JavaScript's safe integer range | Preserve the Python integer exactly in code-generated display text; do not pass it through JavaScript `Number`. |

Format indicator values once in Python from the saved result and send display strings to the canvas/HTML page. The same strings power both surfaces. This is presentation formatting, not new statistics. Existing `Decimal -> float` conversion in `analyst/query.py::cell` is a separate upstream precision limitation; this release guarantees fidelity to `QueryResult`, not recovery of decimal precision already lost there.

## 4. Implementation sequence

Each task includes its focused tests. Enable routing only after the contract, checks, and renderer work.

### Task 1 — Freeze evidence and independent expected outcomes

Files: new `evals/designer/agent/indicator/` fixtures and manifest; existing eval loaders/scorers and their tests.

- Classify all 35 discovery results: required indicator, allowed indicator, inappropriate indicator, incomplete answer, or unavailable value. Record rationale and exact expected primary/context/support columns. Preserve original questions and provenance; do not replace all expectations with `indicator`.
- Reuse the existing discounted/unpaid fixtures where possible. Store only the bounded inputs needed to reproduce the cases, with source run/case IDs and a manifest hash.
- Add independent expectations before changing recommendation rules. Use explicit chart sets; never derive indicator gold labels from `reference_charts` or the corpus's `chosen_chart` metadata.
- Keep baseline fixture inputs compatible with the old report schema. Add new optional metadata only in the candidate inputs, recording that difference; otherwise an old loader failure would be mistaken for an agent failure. Archive baseline outputs before introducing the new chart contract.
- Add scorer tests proving that a wrong metric, missing scope, NULL-as-zero, wrong percent scale, extra unwanted card, missing requested card, and an inappropriate indicator all fail even when the PNG exists and `check_spec` passes.

Done when the fixtures reproduce the current limitations and the evaluators can distinguish them.

### Task 2 — Add the spec, catalogue, and checks

Files: `vis_agent/models.py`; `vis_agent/designer/{models,syntax,catalogue,recommend,rules,check,agent}.py`; `catalogue.json`.

- Implement `summary`, `IndicatorCard`, card parsing/canonical serialization, candidate support, and the indicator entry.
- Add a focused indicator validation helper and dispatch to it after shared syntax/title checks. Do not feed nested bindings through flat-role H1/H2 checks or generic sort/axis transforms.
- Supply accurate generated grammar and catalogue descriptions to the designer. Ensure all card-bound columns are accounted for by coverage checks.
- Catch nested validation failures as ordinary `SpecCheck` violations so the existing bounded repair mechanism can handle them.
- Update the deterministic `one_number` fixture to declare summary intent, add separate explicit-table and non-summary cases, and preserve full catalogue coverage. Check intent literals and catalogue assumptions in eval loaders, corpus tooling, and optimizer tests without changing existing split membership.

Tests: extend `tests/designer/test_{syntax,catalogue,check,rules,recommend}.py` and `tests/test_models.py`.

Cover old spec round trips; one/two/six/seven cards; missing and duplicate fields; Unicode/space/punctuation column names; literal values/formulas rejected as nonexistent columns; per-card formats; card-only keys rejected on other charts; declared/actual row-count mismatches; zero/NULL/nonfinite/string/bool cells; multiple context columns; and multi-metric column permutations.

### Task 3 — Correct share checks and propagate metadata

Files: `vis_agent/analyst/models.py`, `checks.py`, and `rulebook.md`; designer result-facts construction, percent checks, and rulebook; analyst/designer fixtures.

- Add and document `partition_by`; propagate it through saved reports and designer facts. Validate column references and legal combinations.
- Run partition totals as DuckDB queries. Skip whole-partition claims on truncated results, with an explanatory warning.
- Update analyst examples for a scalar share, per-group rates, a complete partition, and signed percentage change. Keep SQL responsible for all numerator, denominator, and change calculations.
- Update existing whole-share fixtures to explicitly declare a complete partition. Do not simply remove their warning assertions.

Tests: `tests/analyst/test_{models,checks,agent}.py`, `tests/designer/test_agent.py`, and percent-related check tests. Verify bad complete partitions still warn, valid grouped partitions pass, scalar/partial/per-row shares do not trigger false totals warnings, and old reports without the field still load.

### Task 4 — Resolve and render indicators

Files: `vis_agent/designer/resolve.py`; a small number-text helper if needed; `vis_agent/render/gptvis.py`; `vis_agent/render/gptvis/render.mjs`; optional local `indicator.mjs` drawing helper.

- Add an indicator resolve branch before null dropping, sorting, folding, and axis transforms. Produce a typed resolved card payload with column identity, label, context, unit, value state, primary display text, and supporting display text.
- Keep raw result values in the report. Send exact numeric text across the Python/Node boundary for indicator drawing; never reparse it as a JS number.
- Draw through the existing Node entry point using `createCanvas`; keep the GPT-Vis path for other chart types. Do not edit `node_modules` or add another renderer registry entry.
- Use a readable one-card layout and a bounded grid for two to six cards. Measure text; wrap context/labels and adapt height within existing dimension limits. Never clip or ellipsize a metric value. Report a render failure if the requested dimensions cannot contain it legibly.
- Preserve Arabic shaping, RTL placement, digit preference, Hijri text, themes, and contrast. Do not infer favorable/unfavorable colors from the sign.
- Produce the usual PNG, config JSON, and standalone HTML. Treat indicators explicitly as static; omit G2 initialization and provide escaped, accessible metric/context text alongside the image.
- Keep render metrics compatible and add actual text/bounds evidence for card checks. Metrics must represent drawn text, not merely echo input payloads.

Tests: `tests/designer/test_resolve.py`, `tests/render/test_gptvis.py`, `tests/render/test_conformance.py`, and focused formatting cases. Verify exact bindings, units, no SQL recomputation, no dropped NULL rows, integers above `2**53`, tiny positive/negative values, rounding, percent changes, Arabic/English, long labels, HTML escaping, bounded layout, and absence of G2 startup in indicator pages. Inspect representative PNGs in addition to text assertions.

### Task 5 — Integrate designer, lead, persistence, and revisions

Files: `vis_agent/designer/rulebook.md`, `rulebook-revise.md`; `vis_agent/requests/runner.py`; `vis_agent/lead.py`; analyst revise guidance where required.

- Replace the “table when one number” instruction with the selection rules above. Explain primary versus supporting metrics and the six-card limit.
- Remove `single_number` and its early return. Run the designer normally, including its existing fallback and saved output.
- Clarify lead wording: “total/how many” uses `draw`; explicit numbers-only uses `answer_question`; explicit indicator requests remain drawable even when their result is a single number.
- A color/language/layout change or table-to-card conversion over a suitable existing scalar result reuses analysis. Changing filters, periods, denominator, or converting grouped rows into a total requires reanalysis. Reuse existing `revise(redo_analysis=...)`.
- Preserve completed historical scalar artifacts and persisted skipped steps. A new revision can create an indicator version; opening/resuming old completed work must not rerun it or mutate its history.
- Preserve the request/response artifact fields, table delivery, warnings, IDs, and bounded tool use.

Tests: replace `test_a_single_number_skips_the_designer` in `tests/requests/test_runner.py`; extend request/API/store, designer fake-model, and lead tests. Cover ordinary scalar delivery, multiple cards, designer retry/fallback, render failure with disclosed table fallback, exhausted budgets, interrupted/resumed design/render, old saved skip, version lineage, and style versus data revisions. Use agent overrides, not manually constructed `RunContext` objects.

### Task 6 — Strengthen end-to-end evaluation and review delivery

Files: `evals/designer/run.py`; `evals/designer/agent/run.py`; `evals/lead/run.py`; new indicator lead/analyst cases; corresponding eval tests.

- Add typed optional indicator expectations to existing case loading, scoring, and review output. Keep old case schemas valid.
- Add `--cases` to the lead runner so a focused indicator conversation set can use the existing execution path. Keep the existing default and `--corpus` behavior.
- Save full relevant tool-call sequences, request states, artifact specs/results, and portable render assets before temporary directories disappear. Distinguish evaluator completion from request success.
- Score the final answer as well as the final artifact: the user must receive the correct image/table and an honest explanation. Check explicit image/artifact references deterministically; judge wording against the saved result.
- Retain table, clarification, unavailable-value indicator, fallback, and failure as separate observed outcomes. An explicit KPI request ending in a fallback table is not a successful KPI delivery.
- Save the same-day baseline/candidate comparison, model IDs, prompts, corpus hashes, dependency versions, git revision/dirty state, repeat counts, and per-stage timing. Record token usage/cost when provided; mark unavailable values as unavailable.

## 5. Test and eval coverage matrix

| Family | Deterministic tests | Model/e2e evaluation |
| --- | --- | --- |
| Scalar total/count/average/min/max | Bound value, metadata, formatting | Correct intent and primary column; explicit KPI delivered. |
| One-row label plus value | Full context coverage, no alias collapse | “Which entity” retains identity; total retains scope. |
| Multiple measurements | One/two/six/seven cards; mixed units | Independent cards versus one primary with supporting counts. |
| Shares and changes | Scale preservation, partition checks, negatives, >100 change | Right percentage metric and denominator context. |
| Missing/invalid data | Zero, NULL, empty rows, partial results, invalid numeric cells | Honest unavailable/clarification/failure; no invented zero. |
| Precision | Tiny values, large integers, compact/explicit rounding | Readable value matches SQL result; no accidental 100x scaling. |
| Inappropriate cards | Multiple rows and invalid card bindings rejected | Trends, breakdowns, top-N, distributions, missing requested years. |
| Localization and layout | Arabic/English, RTL, digits, Hijri, escaped text, long text | Human-readable image and useful labels in the requested language. |
| Conversation | Persistence, resume, budgets, fallback, versioning | Style reuse, data reanalysis, no-chart override, final image delivery. |
| Compatibility | Existing specs, reports, renders, API outputs | Ordinary lead/designer/analyst suites do not regress. |

### Independent eval sets

1. **Discovery regression:** classify and retain all 35 one-row report cases. Use them for development; never describe them as held out.
2. **New designer cases:** at least 24 cases across the matrix, with 12 dev and 12 heldout cases on distinct source/semantic families. Keep permutations, translations, and paraphrases of one case in the same split. Existing discovered cases and their variants remain in discovery/train.
3. **Paired cases:** include total versus by-city; scalar versus trend; same schema asking for a count versus a percentage; column permutations; one extra denominator column; explicit no-chart versus explicit KPI; and missing versus available time detail. Score the relationship between paired outputs, not just each chart type.
4. **Lead conversations:** at least 12 focused conversations covering direct totals, explicit indicators, numbers-only, multi-KPI, and the revision/failure paths above. Run three times independently to expose unstable routing.
5. **Analyst cases:** SQL gold for scalar totals, weighted rates, percentages, zero denominators, and grouped-to-total revisions. Ratio of sums versus average of rates must be explicit; cards cannot repair the wrong statistic.

Freeze heldout expectations before tuning. If heldout failures lead to changes, mark that set as used for development and create a fresh confirmation set. Do not use an optimizer's rules-agreement score as evidence of semantic correctness.

### Scores to report separately

- **Presentation fit:** required, allowed, or forbidden indicator; no-chart instructions obeyed.
- **Metric fidelity:** exact primary columns/card count, required supporting/context columns, units, value states, and coverage of requested parts.
- **Rendered fidelity:** actual drawn text and readable bounds agree with the expected result; image exists. A colored background or border alone cannot pass.
- **Pipeline delivery:** actual request outcome, user-visible artifact/table, successful resume/revision, and truthful fallback explanation.
- **Efficiency:** designer requests/check calls, SQL calls on revisions, fallback rate, token usage, end-to-end p50/p95 latency, and cost where available.

Keep `ChartAccepted` with `reference_charts` as a diagnostic for legacy cases. For the focused indicator set, missing gold expectations are a loader error. LLM visual judges supplement deterministic checks; discrepancies such as a judge claiming 34.07% became 3407% require inspection of the image and render text.

## 6. Validation commands and acceptance gates

These commands are for implementation. Fixture paths below are planned additions. Capture a baseline before runtime edits and preserve its output separately from the candidate run.

```bash
# Offline regression tests, including new contract/scorer/request tests.
uv run pytest -q

# Deterministic recommendation evaluation.
uv run python -m evals.designer.run

# Focused designer development and heldout rendering.
uv run python -m evals.designer.agent.run --cases evals/designer/agent/indicator/cases.json --split dev --repeat 3 --render
uv run python -m evals.designer.agent.run --cases evals/designer/agent/indicator/cases.json --split heldout --repeat 3 --render

# Focused SQL and lead checks; --cases on the lead runner is added in Task 6.
uv run python -m evals.analyst.run --cases indicator --mismatches
uv run python -m evals.lead.run --cases evals/lead/indicator/cases.json --out outputs/indicator/lead-1.json

# Existing premerge suites.
uv run python -m evals.analyst.run
uv run python -m evals.designer.agent.run
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split train
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split dev
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split heldout --render
uv run python -m evals.lead.run
uv run python -m evals.lead.run --corpus --out outputs/indicator/lead-corpus.json
```

Repeat the focused lead command with `lead-2.json` and `lead-3.json`. Model runs need configured providers/credentials; rendering needs the existing Node setup. Judge the heldout scale forty as required by the project, and visually inspect all focused heldout indicator renders. Do not change model IDs between baseline and candidate and attribute that difference to this feature.

Release gates:

- All deterministic tests and required checks pass. Existing spec/report compatibility is verified.
- Every required-indicator case has an image, the right primary metric(s), required scope/support, correct units/value states, and delivery in the final response in all three focused runs.
- Zero critical fidelity failures: wrong numbers or percent scale, NULL-as-zero, dropped requested metrics, invented comparisons, inappropriate scalar collapse, clipped metric values, or extra SQL during style-only revisions.
- At least 95% presentation-fit success on the broader focused set, reported as both case counts and percentages. Inspect every failure. Structural validity alone is insufficient.
- No new confirmed semantic regressions on the existing suites. Investigate model variability with matched repeats instead of lowering expectations or relabeling failures.
- Record the added designer cost/latency for formerly skipped scalars. The runtime keeps its existing budgets; the observed latency/cost is part of review, with no claim of “no overhead.”
- Browser smoke check in the built-in chat: English total; Arabic percentage; multi-card mixed units; unavailable value; numbers-only; color revision; filter revision. Verify image, standalone page, table, and artifact version.

## 7. Boundaries and dependencies

This plan covers the identified indicator failure modes and adds tests that can reveal more. It does not claim to cover every possible visualization request.

The existing [analyst–designer repair plan](2026-09-09-analyst-designer-repair.md) addresses a separate gap: a designer cannot currently request a corrected SQL result from the analyst. Do not quietly implement a new repair loop as part of indicator rendering. If suitable data exists but the analysis returns the wrong granularity, record an end-to-end failure; a user clarification is not a passing substitute. If source data genuinely lacks the requested detail, an honest clarification/disclosure can be the expected outcome.

Other explicit boundaries are empty-query policy, exact decimal preservation before `QueryResult`, and technical failures currently disguised as clarification. Keep these visible in the eval results. Where they prevent a required acceptance case from passing, the release is blocked on the relevant fix rather than claiming that a KPI renderer solved it.

Implementation is complete when the contract, renderer, normal request path, revision behavior, and independent evals satisfy the gates above. A green spec check or a screenshot by itself is not completion.

## 8. Implementation review adjustments

The user's visual review superseded the initial single-card layout: keep the metric label directly
above its value inside a compact Statistic-style card; omit a matching outer title instead of hiding
the useful inner label. Keep meaningful units visible in a smaller adjacent text run, localizing known
count nouns without changing source metadata. For the verified citizen-count result, the display is
`إجمالي عدد المواطنين` above `18 شخصًا`, with the dataset scope below it. Generic count markers can
remain absent when the label identifies the count; currency, percentage, physical, compound, and
meaningful count units remain visible. NULL also retains its unit. This changes presentation only.
The supplied arrow examples do not establish a comparison in a plain total: this release still does
not invent arrows, targets, or favorable/unfavorable colors.

If a single-card description repeats the visible metric label exactly after Unicode/whitespace
normalization, omit that redundant footnote as well. Preserve the description in metadata and accessible
image text; retain a visible footnote when it adds scope or explanation.

Live validation also caught a computed percentage with a missing unit. New `run_query` results require
an explicit `%` or `fraction` unit on shares; missing or unknown scales return an error check for the
existing bounded repair. This check does not rewrite old saved reports or infer a scale from the value.

An explicit output-language instruction can differ from the script used to write it. Common requests
such as `Make this card Arabic` now set the requested presentation language while preserving the saved
analysis on style-only revisions; the request regression covers both English- and Arabic-worded changes.

Review found that language-only revisions could translate titles but not card labels: reused analysis keeps its original column meanings. Add an indicator-only `Spec.column_labels: dict[str, str]`, default empty, for presentation translations of existing, bound columns. The line grammar uses `columnLabels` with records such as `  - ["visitor_count", "إجمالي الزوار"]`. JSON string pairs preserve exact column names containing spaces, quotes, or Unicode. These labels cannot change units, values, context cells, SQL, or bindings; the designer must preserve the original meaning without adding numbers or claims. This is a deliberate extension of the original metadata-only label contract so a language revision can reuse analysis.

Historical scalar artifacts also have no saved design. `PreviousDesign.spec` therefore accepts null while retaining the latest `previous.change`; the designer can create the requested card without losing a color or language instruction or inventing a previous spec. Completed historical steps remain unchanged.

Contrast checks use both the actual card surface and the outer background. Arabic numeric runs, including signs and scientific exponents, need direction isolation separately from Arabic unit labels; logical text logs alone do not establish correct visual order.

An explicitly scaled part-of-whole share must also lie within its range: 0–100 for `%` or 0–1 for `fraction`, allowing floating-point noise of `1e-9` times the upper bound. This applies to primary and supporting card values, independently of partition totals. Percentage changes remain `measure` values with unit `%` and can be negative or above 100. Unknown scales remain unchanged, and NULL stays unavailable.

The first live three-repeat heldout run (`outputs/indicator/heldout.json`) exposed failures on `heldout_age_breakdown` and `heldout_missing_years`: the designer selected scalar cards for a requested wide breakdown and for absent yearly detail. Their evidence was used to strengthen the designer's coverage and intent precedence instructions. This heldout set is therefore now used for development; subsequent results on it are regression results, not independent confirmation. Its expectations remain unchanged. A fresh confirmation set must be frozen before claiming heldout acceptance.

Broad analyst and lead regression runs exposed nonempty `partition_by` lists on ordinary measure and grouping columns, exhausting model retries. Non-share columns now discard this inapplicable annotation as null, including copied grouping names or placeholder lists; this does not change their SQL, kind, values, units, or aggregation. This deliberately replaces the planned rejection of non-share partition metadata to keep an optional share annotation from breaking ordinary questions. Actual shares retain strict partition validation, including distinct/nonempty names, grouping references, self-reference rejection, declared completeness, scale, and value bounds.

The subsequent focused regression showed that the designer could correctly select composition intent and still deliver multiple indicator cards for a requested breakdown. Spec checking now receives the designer's existing selected intent and rejects indicators for compare, trend, composition, or distribution, including at delivery and rendering. The existing repair budget can select a table or suitable chart. This adds no keyword-based intent inference: summary, share, scalar rank, and unspecified historical intents remain supported, and semantic evals still assess whether the chosen intent matches the question.
