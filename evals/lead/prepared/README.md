# Prepared CSV evaluation

These small CSVs contain invented test values, created for this evaluation. Their briefs describe
completed outputs from an upstream data agent. Six cases cover a regional comparison, a monthly trend,
a KPI, an explicit visual review, an Arabic population trend with Hijri month labels, and the axis-title
regression for a vertical column chart.

Run the application's configured lead and specialists:

```sh
uv run python -m evals.lead.run --cases evals/lead/prepared/cases.json --out /tmp/prepared-results.json
```

Each case checks publication, exact source columns and values, chart choice, chart bindings, and the
lead's explicit design → render → publish decisions. Profiling, analyst calls, and questions fail these
prepared-data cases. The latency target is 60 seconds per case; measured times and request counts are
saved with the evidence. Rendered images are copied next to the results for visual inspection.

Passing this small set is a smoke check. It does not establish correctness on every dataset or replace
looking at the rendered charts.
