# Indicator evaluation

`discovery.json` contains all 35 one-row analyst results from run `20260913-183937`. The manifest records the original question, explicit primary/context/support expectations, classification, and file hashes. `baseline.json` retains historical request statuses, designs, replies, and timings. That history is a discovery baseline; it is **not** a matched same-day model comparison.

`cases.json` contains 24 independently authored cases: 12 dev and 12 heldout. All variations of each semantic family stay in the same split. The original heldout set is now explicitly marked used for tuning after failures on age breakdown and missing-year coverage. Its original golds and evidence remain unchanged. `confirmation.json` and its hashed manifest contain 12 new, frozen confirmation families; no discovered cases are relabeled as fresh confirmation. Do not relabel a model failure to make it pass. If a heldout failure informs a change, mark that set as used for development and create a fresh confirmation set.

Gold classifications:

- `required`: the requested headline measurement must be an indicator.
- `allowed`: an entity-aware indicator or a complete table is acceptable.
- `forbidden`: preserve the requested breakdown, trend, text/table format, or excess metrics.
- `incomplete`: the supplied result lacks requested detail. This is an analyst/pipeline problem; an indicator cannot repair it.
- `unavailable`: render the NULL metric as unavailable, without inventing zero or a cause.

`PresentationFit` and `MetricFidelity` use explicit golds, never recommendations or source `chosen_chart` labels. `Rendered` checks actual canvas text and measured bounds, primary/support values, scope and unit/state preservation. The metric text comparison permits explicit rounding and compact suffixes, but never an implicit percentage rescaling or loss of a nonzero value. A PNG or colored background cannot establish correctness. `paired_scores` checks primary consistency across permutations and changes of question.

Legacy suites retain `ChartAccepted` as a diagnostic for rules agreement. Their rendering smoke score does not make claims about independent metric correctness. Historical human judgment rubrics remain unchanged; focused model judging adds indicator-specific criteria.

Run with the existing runner:

```bash
uv run python -m evals.designer.agent.run --cases evals/designer/agent/indicator/discovery.json --render --out outputs/indicator/discovery.json
uv run python -m evals.designer.agent.run --cases evals/designer/agent/indicator/cases.json --split dev --repeat 3 --render --out outputs/indicator/dev.json
uv run python -m evals.designer.agent.run --cases evals/designer/agent/indicator/cases.json --split heldout --repeat 3 --render --out outputs/indicator/heldout.json
uv run python -m evals.designer.agent.run --cases evals/designer/agent/indicator/confirmation.json --repeat 3 --render --out outputs/indicator/confirmation.json
uv run python -m evals.designer.agent.run --cases evals/designer/agent/indicator/regressions.json --render --out outputs/indicator/user-regressions.json
uv run python -m evals.analyst.run --cases indicator --mismatches --out outputs/indicator/analyst.json
uv run python -m evals.lead.run --cases evals/lead/indicator/cases.json --out outputs/indicator/lead-1.json
```

Repeat the lead run three times with separate output names. The 14 conversations include actual clarification/resume, no-pending resume behavior, multi-card delivery, explicit no-chart/table requests, and style/filter/denominator/grouped-to-total revisions. Offline request tests exercise renderer failure, fallback, budget and interruption paths; the live corpus does not inject fake failures into runtime tools.

Lead scoring records actual request outcomes separately from evaluator completion; checks bound metric values and units, final image delivery, scale-sensitive numerical claims, and saved analysis reuse. Count dimensions may normalize when the lead gold leaves the unit unspecified. Explicit meaningful units remain required, and currency and percentage units stay strict. Rendered fidelity preserves raw source metadata and checks actual separate number/unit canvas runs and their adjacency. The actual citizen-count regression follows the updated user preference: a label inside the card above the value and a visible localized person unit. Complete message histories, tool-call sequences, returned metadata, usage and portable render assets remain reviewable. Wording quality beyond numeric fidelity still needs human or model judgment against this saved evidence; it is not inferred from an image link.

The eight SQL cases use guarded reference queries to distinguish totals, weighted rates, supporting counts, NULL denominators and percentage change. Their strict-scale option disables the legacy fraction-to-percent leniency.

Use matched models and prompts when comparing before/after runs, and retain both outputs. `--out` saves corpus hash, dependency versions, git state, prompts, repeats, all design outputs and inputs, and portable render assets. Provider-reported turn usage is saved for the lead; unavailable monetary cost remains null. Review the added scalar designer latency and cost rather than assuming no overhead.

`evals/lead/indicator/regressions.json` separately covers the actual citizen-count dataset and an English instruction to make the existing card Arabic, preserving the analysis. It is a known user regression, not part of fresh confirmation.
