# Designer evaluation at scale

This set follows [Phase 4b, sections 4–7](../../../../docs/superpowers/specs/2026-09-07-phase-4b-evaluation-at-scale-design.md).
Selection and capture produce the data files; the runner consumes saved analyst reports and does not query or
modify the source corpus. This task adds runner support and documentation. The 200-case artifacts are supplied
by the other Phase 4b tasks and are not included in this worktree yet.

## How the set is built

The selection pipeline deterministically chooses real questions and datasets from the 500-file dev corpus,
excluding the profiler's existing train/evaluation datasets, files over the upload limit, and map or
geometry-only cases. Coverage includes orchestrator tasks, result shapes, row-count buckets, Arabic labels,
time columns, nulls, negatives, and long text. The first producing question is used per dataset; previously
captured Phase 4 cases provide at least twenty English questions.

Twenty to thirty labelled transformations of real files cover Hijri dates, Arabic-Indic digits, and Arabic
label edge cases. `decisions.json` records provenance and transformations. `splits.json` records train (120),
dev (40), and heldout (40), disjoint by dataset, with seeded and Arabic cases spread across them. Selection
and capture own these counts and the disjointness guarantee; the runner filters the top-level `split` field
in `cases.json`, which must agree with `splits.json`.

Every case points to a saved `AnalysisReport` relative to `cases.json` and keeps the Phase 4 fields:
`name`, `report`, `brief`, `expect`, `charts`, `language`, `bind`, `emphasis`, and `why`. Scale cases add
`split`, `seeded`, and `metadata.task` (or a top-level `task`). Nested metadata is preserved; top-level split,
seeded, and task fields take precedence. Provenance stays in evaluation metadata, outside the designer's
input. Insightor's chosen chart and the requested type are metadata, never acceptable-chart labels.

## What the automatic scores mean

Use `charts: null` to calculate `ChartAccepted` from the saved report and the intent declared by the
designer. The reference includes every `recommend_charts` candidate within one point of the top score and
with a nonnegative score. It also includes eligible orientation swaps (`bar`/`column`,
`grouped_bar`/`grouped_column`, `stacked_bar`/`stacked_column`) and `pie`/`donut` swaps. Swaps must still be
nonnegative candidates, so rejected charts never re-enter the reference. An empty result has no reference
charts. The returned order follows the recommendation ranking.

An explicit chart list, including an empty list, keeps Phase 4 acceptance behavior. Expected clarifications
still pass `ChartAccepted`. The reference measures agreement with the rules; it is not a human correctness
label. For example, the `gender_share()` fixture includes pie, donut, column, bar, **treemap**, and table
because all six meet the threshold.

Scale datasets add `IntentPlausible` as a soft score. The five task mappings are:

| Metadata task | Designer intent |
| --- | --- |
| single_value | share |
| comparison | compare |
| ranking | rank |
| composition | composition |
| distribution | distribution |

Matching scores 1; mismatching or missing designs score 0 when a mapped task exists. Missing or unmapped
tasks (including `table`) score a neutral 1. `single_value` uses `share` because the existing intent language
has no “one number” value. The mapping is temporarily private in `run.py` until Task 1's selector is merged.
Datasets with a null chart list or split metadata receive this evaluator. The original unsplit 31-case
smoke set retains exactly its six evaluators. `Passed`, `LanguageRight`, `BindingRight`, and `Metrics`
retain their existing meanings.

## Run the splits

From the repository root, with the existing environment and a configured designer provider:

```sh
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split train
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split dev
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split heldout
```

Omit `--split` to run the complete file. Use `--model`, `--repeat`, and `--max-concurrency` as in Phase 4.
`--mismatches` prints chart, language, binding, and intent disagreements. The report prints the selected
case count and seeded/unseeded counts; these count selected cases once, independent of `--repeat`.
The optimizer uses train and dev only; heldout is reserved for the final evaluation.

Model runs require provider access. Offline validation with the preinstalled environment is:

```sh
UV_CACHE_DIR=/tmp/pydantic-vis-harness-uv-cache UV_OFFLINE=true UV_NO_SYNC=true uv run pytest -q
UV_CACHE_DIR=/tmp/pydantic-vis-harness-uv-cache UV_OFFLINE=true UV_NO_SYNC=true uv run python -m evals.designer.run
```

## Render and judge

Add `--render` to save specs, explanations, images, and an HTML review page. Outputs live next to the chosen
cases file under `renders/<model>/<split>/` (the split directory is omitted for a full-set run). Each repeated
evaluation retains its own render and scores. The page groups train, dev, heldout, then unsplit cases, and
marks seeded cases. `Rendered` retains the existing PNG check and non-background pixel floor; tables only
require the PNG. The renderer environment must already be set up as described in the repository README.

Open the printed review-page path, enter your name, mark failed rubric criteria, choose pass/fail, and add
notes. Copy the judgments JSON and place it under the `judgments` key in `scale/judgments.json`, preserving
the existing `rubric` alongside it. Exported entries include split, seeded status, model, and exact spec.
Repeated case names remain distinct. A passing verdict with any failed criterion is not counted correct.

Read saved judgments without constructing a model:

```sh
uv run python -m evals.designer.agent.run --cases evals/designer/agent/scale/cases.json --split heldout --judgments
```

The summary's top-level `judged`, `correct`, and `share` include seeded cases. The nested `seeded` and
`unseeded` objects give the corresponding counts and shares; `unseeded.share` is the result without seeded
cases. Empty denominators report 0, with `judged: 0` making the absence of evidence explicit. Only pass/fail
entries are counted, and each repeat is a separate judgment, as in Phase 4. Missing seeded flags default to
false. The CLI fills provenance from the selected cases, overriding stale judgment flags, and filters repeat
names by their base case when `--split` is given. Saved specs are checked for the same selected split.
Legacy judgments with no seeded provenance retain their original summary shape.

Add `--judge MODEL` to an evaluation for an optional LLM judge; it must differ from the designer model.
Agreement with saved human judgments still requires matching case name, model, and exact spec. A person's
judgments on the heldout forty, with and without seeded cases, determine correctness and the seven-in-ten
exit test; neither `ChartAccepted` nor the LLM judge substitutes for that review.
