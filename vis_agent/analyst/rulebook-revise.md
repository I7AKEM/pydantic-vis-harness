## Answers and revisions

When the prompt carries `clarifications`, each answer is the caller's decision on that question. Follow it,
record it under assumptions in the caller's own words, and never ask that question again.

When the prompt carries `previous`, the caller asked for a change to an earlier result: `previous.sql` and
`previous.columns` produced it and `previous.change` says what must differ. Start from the previous SQL,
change only what the change names, keep every other filter, grouping, and column, and say in the summary
what changed.
