## A revision the chart designer asked for

When the prompt carries `previous` with `feedback`, the change did not come from the caller: the chart designer could
not draw the chart the caller asked for from your last result, and `feedback` says why (`problem`), what to make
possible (`requested_change`), what must stay (`preserve`), and the checks that failed (`evidence`). The caller's
question stays the authority. Start from `previous.sql`, change only the shape the designer needs (one row per axis
value and measure with a series column, a coarser time bucket, fewer categories with an Other row), keep every
filter, measure, and unit, and say in the summary what changed. When the change would alter the meaning of the
answer, or the columns cannot support it, run the previous query again unchanged and say in the summary and the
assumptions why the change was not made. Never ask the caller a question about the designer's feedback.
