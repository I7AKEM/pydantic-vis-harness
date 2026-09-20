# Aborted GLM production-instructions attempt

This was an attempted 20-case `renderable` run with concurrency 1, GLM5.3 lead,
GLM5.3 designer and fallback, and Gemma4 31B Nitro image review. Production lead
instructions and application runtime were unchanged. User-approved reference rows
and chart images were sent to the configured OpenRouter models.

The evaluation runner crashed while scoring case 7: an honest no-chart fallback
artifact has `spec=null`, but `visible_columns()` called `parse(None)`. This caused
`AttributeError: 'NoneType' object has no attribute 'splitlines'`. Before the
incremental-checkpoint fix, that exception prevented final JSON persistence.

Do not count this as a completed 20-case experiment or silently combine it with a
later run. First-six completion logs were:

| Case ID suffix | Delivered artifact | Requests | Seconds |
| --- | --- | --- | --- |
| `46dad75ae7fa7b62` | Yes | 8 | 27.44 |
| `6eff7ae46ebb4edf` | Yes | 13 | 24.13 |
| `70ea08202f57d58f` | Yes | 8 | 8.87 |
| `97280400c00748a7` | Yes | 8 | 8.94 |
| `3b62e4047e2cb455` | Yes | 8 | 9.57 |
| `2177430e3e44a9a3` | No, framework request limit | 18 | 46.79 |

Delivery here is not strict fidelity/review/latency success. Case 7 completed its
agent interaction but its result was lost at scoring; no request/time figure is
claimed. Assets for the six completed records remain in the adjacent
`results-parallel20-glm-production-assets` directory.

## Independently inspected images

- The first percentage indicator (`bb97c9426885`) visibly preserves 0%, 2 and
  370,783 as requested, with readable supporting labels.
- Both region/gender PNGs (`88bd4b829d04`, `b74bfea4afda`) visibly contain eight
  grouped regions, F/M legends, readable labels and the expected paired values.
  The missing raw review result means the precise cause of its extra requests
  cannot be established from these images alone.
- Donut `de1c2aa11229` has severely clipped white value labels on a hairline ring.
  Its repair `0458f801e10a` hides those labels but keeps the malformed thin ring.
  This is backed by retained configuration, not merely a subjective inspection:
  input `innerRadius` is 60.0 and then 65.0, whereas generated G2 coordinates have
  `innerRadius=1` and `outerRadius=0.95`. The catalogue's valid example is 0.6.
  Unconstrained numeric configuration reached the renderer; this is a concrete
  designer/API-validation failure to address in a separate frozen-code experiment.
