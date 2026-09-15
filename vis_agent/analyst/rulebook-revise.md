## Answers and revisions

When the prompt carries `clarifications`, each answer is the caller's decision on that question. Follow it,
record it under assumptions in the caller's own words, and never ask that question again.

When the prompt carries `previous`, the caller asked for a change to an earlier result: `previous.sql` and
`previous.columns` produced it and `previous.change` says what must differ. Start from the previous SQL,
change only what the change names, keep every other filter, grouping, and column, and say in the summary
what changed.

Changing a grouped chart into a total KPI changes the query: aggregate the original data over the
requested scope, rather than adding displayed top-N rows or averaging percentages. Changing filters,
periods, or a percentage denominator also needs revised SQL. Keep numerator/denominator context for a
headline share. Preserve NULL for an undefined value, even when another requested metric is available.
