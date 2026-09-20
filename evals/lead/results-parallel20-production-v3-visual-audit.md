# Independent visual audit: production-v3 paired twenty

This is a local visual audit of the frozen first 20 renderable data-agent handoffs
for each designer arm, not the later supplementary thirty. Images are inspected
directly against persisted full source rows, required columns, and saved designs;
reviewer verdicts are not treated as visual ground truth. No raw score is changed.
The user brief asks for supplied-data presentations, not answers to the original
upstream research questions. A table is a valid presentation for categorical data.

Status: complete — all 40 case outcomes accounted for and all 41 retained PNG
paths inspected (21 GLM; 20 Claude, including first/final repairs). Claude's
`97280400c00748a7` timed out without a PNG; therefore 39 of 40 cases have image
evidence. `Clear` means no material visible defect found in the inspected PNG;
it is not an overall pass or a proof of perfect accuracy. `Fallback` means the
published artifact has no PNG, even when a discarded render remains in the audit.
RTL category or legend order alone is not an error. An intentionally scrollable
viewport with access to all rows is not data corruption; static PNG visibility
and accessible HTML/source-table completeness are separate dimensions.

| Dimension | GLM designer | Claude designer |
| --- | ---: | ---: |
| Frozen raw strict result, unchanged | 12/20 | 12/20 |
| Cases with directly inspected render evidence | 20/20 | 19/20 |
| Rendered cases with no material visible defect identified | 18/20 | 19/19 |
| Cases with a confirmed visible defect | 2/20 | 0/19 rendered |
| Cases without any PNG | 0/20 | 1/20 |

This narrower manual dimension does **not** replace the strict end-to-end score:
review failures, missing final image links, fallbacks, timeouts, and latency still
count there. It also does not certify every overlapping scatter point. One
Claude render uses English title/axes following the lead's English rephrasing;
that localization caveat is listed below rather than called data corruption.
One GLM final reply invents code meanings even though its image retains the codes.

| Case suffix | Supplied presentation | GLM designer: first/final visual evidence | Claude designer: first/final visual evidence |
| --- | --- | --- | --- |
| `46dad75ae7fa7b62` | Percentage 0 with support 2 and 370,783 | Clear; all three values readable | Clear; all three values readable |
| `6eff7ae46ebb4edf` | Two-category population donut | Defect: inside labels clipped at ring; published source-table fallback | First and final clear; false legend accusation prompted needless repair; final reply omits image link |
| `70ea08202f57d58f` | Prepared percentage 100 | Clear | Clear |
| `97280400c00748a7` | Supplied male count 0 only | Clear; no invented ratio | No PNG or artifact; 120-second timeout |
| `3b62e4047e2cb455` | Prepared percentage 26.11 | Clear | Clear |
| `2177430e3e44a9a3` | Region / F-M / percentage | Clear chart, all 16 correct values; unsupported F/M decoding in final prose | Clear; all 16 values and F/M retained |
| `ba0187c944a3f829` | All 17 region / city pairs | Clear PNG, all 17 rows and correct headers; false header accusation; complete source-table fallback | Clear PNG with all 17 rows; false RTL-order objection; complete source-table fallback |
| `e07c573241abdb02` | Population count 0, WKT excluded | Clear | Clear |
| `9e75e9ae40758227` | Age group / person type / population | Clear; all ten values, matching colors and RTL age order | Clear values and mapping; English title/axes despite Arabic handoff (localization caveat, not data loss) |
| `85830f71807a6905` | Single city name | Clear one-cell table, no invented measure | Clear one-cell table |
| `39471b0e4a5d3fc5` | Two prepared averages 3.76 | Clear; both means and correct units | Clear; both means and correct units; 114.9 seconds, over SLA |
| `f6687502449585a5` | District counts and percentages | Clear table; all ten rows and three required columns | Clear table; all ten rows and three required columns |
| `45980b90faceca07` | Two independent percentages with support | Clear two cards; all six values readable, independent denominators | Clear two cards; all six values readable and matched |
| `2571f37808cda8e2` | Gender-code percentages | Clear; F/M preserved, 50.44%/49.56% correctly rounded | Clear; F/M preserved, 50.44%/49.56% correctly rounded |
| `c76808cc7a78dac8` | Population and employed counts; rate retained in source | Defect: short-bar value/unit labels collide with city names; saved chart but no final reply | Clear; all ten population/employed pairs and colors correct, outside labels readable; false rejection; source-table fallback; 73.3 seconds |
| `ae315d3da67a2d11` | 1,000 coordinate points, not routes | Clear axes/legend, exact 1,000-entry render binding; overlapping point count not visually provable | Clear axes/legend, exact 1,000-entry binding; same overlap caveat; 81.9 seconds |
| `2bc0cfa90c65f142` | Five wealthy-count city rows | Both PNGs clear and byte-identical; 6,5,4,4,4 in RTL order; false review rejection; no artifact or final reply | Clear five bars and exact categories/counts; 61.2 seconds |
| `61793ff199102633` | Two prepared rates per 100 | Clear 13.19/7.17 and per-100 units; long rotated ticks readable; no final reply | Clear 13.19/7.17, correct groups and per-100 units |
| `3dda20f66cddb9da` | Population count 671 | Clear | Clear |
| `8b3fd04765e40d3a` | Preregistered supplied total count 0 | Clear; no inferred port/transport facts | Clear; no inferred port/transport facts |

## Confirmed evidence

- GLM donut: [first PNG](results-parallel20-glm-production-v3-assets/corpus-vizcsv-6eff7ae46ebb4edf/renders/cc842f40687c/chart.png) has white category labels and leading count digits cut by the ring boundary. The saved source has مواطن=373,877 and وافد=375,161; both values remain intact in the fallback table. This is a real glyph-visibility defect, not a scroll-viewport issue.
- Claude donut: [first PNG](results-parallel20-claude-production-v3-assets/corpus-vizcsv-6eff7ae46ebb4edf/renders/b6db1a053695/chart.png) and [final PNG](results-parallel20-claude-production-v3-assets/corpus-vizcsv-6eff7ae46ebb4edf/renders/d3c235336432/chart.png) both correctly match labels, counts, colors, and legend. First render: blue=وافد 375,161; teal=مواطن 373,877. Final reverses colors consistently. The second `error` finding retracts itself in prose. This does not excuse the missing final image link or turn the raw review gate into a pass.
- GLM region/city: [PNG](results-parallel20-glm-production-v3-assets/corpus-vizcsv-ba0187c944a3f829/renders/9430e883b1ca/chart.png) has all 17 rows, including جدة، مكة المكرمة، نجران, under the correct region/city headers. The reviewer alleges a swap that is not visible. The published fallback retains all 17 source rows; no source data was lost.
- GLM region/gender: [PNG](results-parallel20-glm-production-v3-assets/corpus-vizcsv-2177430e3e44a9a3/renders/c2d4f050dc65/chart.png) retains F/M correctly. However, [saved final response](results-parallel20-glm-production-v3-assets/corpus-vizcsv-2177430e3e44a9a3/case.json) calls F female and M male despite the explicit no-codebook handoff. This is an unsupported nonnumeric prose claim, outside the numeric-only answer gate and separate from image quality.
- GLM city counts: [PNG](results-parallel20-glm-production-v3-assets/corpus-vizcsv-c76808cc7a78dac8/renders/b9d79cb051df/chart.png) preserves the source counts but the population value/unit labels extend out of the very short blue bars and collide with the city labels. This is an actual text-overlap issue. The render is saved, but the run has no final response; therefore source fidelity cannot be inferred from a successful-delivery gate.
- Claude city counts: [PNG](results-parallel20-claude-production-v3-assets/corpus-vizcsv-c76808cc7a78dac8/renders/9d06d6c367f8/chart.png) has readable outside labels with correct counts and legend: blue population=701 and teal employed=10,356 for نجران, and the other nine city pairs also match. The reviewer alleges these colors/values are swapped, contrary to the PNG. The published result is nevertheless a source-table fallback, with no image link.
- GLM five-city ranking: [first PNG](results-parallel20-glm-production-v3-assets/corpus-vizcsv-2bc0cfa90c65f142/renders/84faa7d9d93f/chart.png) and [final PNG](results-parallel20-glm-production-v3-assets/corpus-vizcsv-2bc0cfa90c65f142/renders/4f368873e010/chart.png) are byte-identical (`e3c79e9eae34b2d0eea3f9e7507e6099b8419d2044666d186b597ca5da1eeb04`). Both correctly show مكة المكرمة=6، الدرعية=5، جازان=4، جدة=4، الباحة=4 from right to left. Rejection for ascending order confuses RTL with incorrect data/order.
- GLM coordinate scatter: [PNG](results-parallel20-glm-production-v3-assets/corpus-vizcsv-ae315d3da67a2d11/renders/ccbe35bca85a/chart.png) has correct longitude/latitude axes and a readable app legend. All 1,000 config entries match the full persisted source rows exactly for x=longitude, y=latitude, group=app_name. Dense overlapping points cannot be counted independently in the raster, so this is not a claim that 1,000 distinct dots are visually identifiable.
- Claude coordinate scatter: [PNG](results-parallel20-claude-production-v3-assets/corpus-vizcsv-ae315d3da67a2d11/renders/6d75b6e643fc/chart.png) also has correct axes, degree units, readable app legend, and exact 1,000-entry x/y/group binding. It has the same raster-overlap uncertainty, not evidence of lost source rows.
