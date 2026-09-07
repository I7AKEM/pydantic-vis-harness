Cases are written by hand in `cases.json`, with reference SQL; decisions go in `decisions.json`.
Each case has `name`, `csv`, `question`, `brief` (an object or null), `reference_sql`, and `expect` (`table` or `clarification`).
The `csv` path is relative to this directory; clarification cases use null reference SQL.
Reference SQL uses `dataset` only as the table name: the tooling replaces every occurrence with the real quoted name.
Run `uv run python -m evals.analyst.make_expected` to write `expected.json`, mapping table case names to `columns` and `rows` through guarded SQL.
