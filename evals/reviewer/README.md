<!-- evals/reviewer/README.md -->
# The reviewer's evaluation

1. Build the labelled set from the evaluation team's run (designer cases both judges agreed on):
   `uv run python -m evals.reviewer.build_labelled ~/Downloads/20260913-183937`
2. Confirm each verdict by eye: `uv run python -m evals.reviewer.review_page`, open `labelled/review.html`,
   choose pass or fail per chart, copy the JSON into `labelled/human.json` (keep everyone's verdicts; add, never overwrite).
3. Measure a seat: `uv run python -m evals.reviewer.run --model openrouter:openai/gpt-5.4` or `--model litellm:Qwen/Qwen3.8-27B`.
   The exit line is agreement of at least 0.8 on the confirmed set, for the chosen seat on the proxy and on OpenRouter.
4. Probe which proxy models read pictures: `uv run python -m evals.reviewer.probe_seats`.
5. Export runtime verdicts as future labelling candidates: `uv run python -m evals.reviewer.export_verdicts`.

The pictures and the exported verdicts stay out of git; `cases.json` and `human.json` are committed.
