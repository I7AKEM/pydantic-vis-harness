# Designer evaluation set

The 31 cases use thirty saved analyst reports and one empty-result copy. No analyst or profiler runs during evaluation. `cases.json` holds expectations; `decisions.json` records the controller's intent, the recomputed Phase 3 rankings, allowed alternatives, and coverage limitations. There are 14 Arabic and 17 English cases, including the empty case.

Run from the repository root with `OPENROUTER_API_KEY` available:

```sh
uv run python -m evals.designer.agent.run
uv run python -m evals.designer.agent.run --render --repeat 2 --mismatches
uv run python -m evals.designer.agent.run --model openrouter:openai/gpt-5.4-mini --render
uv run python -m evals.designer.agent.run --judge openrouter:anthropic/claude-sonnet-4.6
```

`--model` defaults to `PYDANTIC_AI_DESIGNER_MODEL`, then `DEFAULT_DESIGNER_MODEL`. `--cases` accepts a cases JSON path; report paths resolve relative to that file. `--max-concurrency` defaults to 4 and `--repeat` to 1. `--judge MODEL` must use a different model from the designer. It receives the question and bounded result description, including column facts and a short preview, not just a report filename. Neither dataset construction nor `--judgments` creates a model.

The default automatic evaluators are `Delivered`, `Passed`, `ChartAccepted`, `LanguageRight`, `BindingRight`, and `Metrics` (requests, check calls, seconds). `Passed` rechecks the spec against the captured report rather than trusting the returned check. `--render` adds `Rendered`, requiring an existing PNG and a non-background share of at least 0.02. Expected clarifications score 1 on the inapplicable design/render checks; `Passed` also scores 1 whenever no design was delivered. Always read these scores together with `Delivered`. `--mismatches` prints each run with a failing chart, language, or binding score and its spec.

`ChartAccepted` is deliberately permissive: it includes the controller's lists, all candidates within three points of the top, and the documented human alternatives. Some of those candidates are weak choices. `BindingRight` constrains shared roles only, so tables and chart families with different roles remain possible. Human review must assess whether the requested measure, groups, units, and emphasis were actually shown. No case invents an emphasis request that was absent from its question. The evaluator's emphasis behavior is tested separately.

Rendering uses the existing Node 22/GPTVis setup (`vis doctor`). Artifacts go under `renders/<model slug>/<case>/`: `chart.png`, renderer HTML/config, `spec.txt`, and `explanation.txt`. Additional repetitions have their own `repeat-2/`, `repeat-3/`, etc. folders, assigned in design-completion order; the review page connects each evaluation run to its actual artifacts. A subsequent invocation replaces the same model's artifacts. Save judgments before rerunning. Renderer failures score zero and appear on the page without aborting other cases.

## Human review

After `--render`, serve the pages locally:

```sh
uv run python -m http.server 7942 --bind 127.0.0.1 --directory evals/designer/agent/renders
```

Open `http://127.0.0.1:7942/`, select the model folder, and open its `index.html`. Enter your name (`controller` for the controller's first pass). Review the image, question, spec, explanation, compromises, and scores. Check any **failed** rubric criteria, choose pass or fail, and enter a note. A correct chart passes all six criteria. The empty case has a clarification and no image; assess whether that was the right response.

Click **Copy judgments JSON**. Paste the copied object into the `judgments` property of `judgments.json`, keeping the `rubric` property. The textarea remains available if clipboard access fails. Each verdict includes the reviewer, UTC date, model, and exact spec, so there is no separate `judged/` directory. Repeated runs have distinct case keys such as `deaths_by_gender [1/2]`; preserve those keys. Save the controller and owner's verdict sets separately when comparing their reviews, rather than overwriting one without retaining it.

```sh
uv run python -m evals.designer.agent.run --judgments
```

This prints judged count, correct count, correct share, and failed-criterion counts. A pass with any failed criterion counts as incorrect. It also rechecks the saved judged specs and prints their passing share, excluding clarifications and unknown case names. With no judgments, the judged count and correct share are zero; the spec-check share is null. This is not an exit-test pass.

The exit test is the human correct-first-time share together with clean delivered specs (`Passed` must be 1.0). The design specifies no numerical threshold for the human share; report it without inventing one. Review each original delivered result, including any recorded check calls, and report repeated runs separately when studying variability. The automatic scores and optional model judge do not replace the owner's verdict.

With `--judge` and existing judgments, the runner prints agreement only for matching case/run names, designer model, and exact spec text. A regenerated or stale spec is not a judgment of the same artifact; it is excluded. `compared: 0` and `agreement: null` mean no comparable judgments, not agreement. The judge assertion must equal the human verdict; a pass with failed criteria is treated as a failure. The Phase 5 target of eight-in-ten agreement is a measurement for the reviewer, not this designer's exit test.

Costs are not exposed by the current `DesignReport` contract. This runner reports only the requested metrics; the controller records provider costs and live-model results separately. Every confirmed failed criterion should become an eval case plus a rulebook line, Phase 3 check/rule, or delivery check in a later implementation round.

## Offline verification

```sh
UV_CACHE_DIR=/tmp/pydantic-vis-harness-uv-cache UV_OFFLINE=true UV_NO_SYNC=true uv run pytest -q
UV_CACHE_DIR=/tmp/pydantic-vis-harness-uv-cache UV_OFFLINE=true UV_NO_SYNC=true uv run python -m evals.designer.run
```

The deterministic designer runner and its 37 cases are unchanged. Tests exercise dataset loading, evaluator correctness, clarification short-circuiting, repeated render bookkeeping with a fake renderer, judgment export markup, CLI paths, and judge agreement without real model requests. Live designer/judge runs and human verdicts are controller steps.
