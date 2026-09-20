# Static table completeness regression

Source case: `corpus-vizcsv-ba0187c944a3f829`, saved in
`results-parallel20-glm-concise-v2-assets`. This is a local renderer replay,
not a new model evaluation or a retroactive pass for the original case.

The source contains 17 region/city rows. Both original rendered attempts used
800 × 450 logical pixels. Their PNGs contained 13 complete rows and a partial
fourteenth row, followed by a nonfunctional vertical scrollbar; Jeddah, Mecca,
and Najran were absent. The renderer's `drawn_rows=17` counted supplied rows,
not the cells actually visible in the static image.

The pinned packages are GPT-Vis SSR 0.3.8, S2 SSR 0.1.1, and S2 2.6.0. S2 uses
30-pixel header and data rows, a 2-pixel header split line, and a 6-pixel
scrollbar reservation. Its `autoFit` option crops blank space; it never expands
the viewport to include offscreen rows. Measured panel geometry:

| Requested height | Data viewport height | Full data height | Complete |
| --- | --- | --- | --- |
| 450 | 412 | 510 | No |
| 547 | 509 | 510 | No, last row loses one pixel |
| 548 | 510 | 510 | Yes |

The resolver now sizes default-height tables to at least `38 + 30 × rows`.
Explicit heights too small to fit every row produce an actionable diagnostic.
The full-image resource ceiling is 2400 logical pixels (78 default-size rows);
larger tables fail explicitly without sampling or claiming a complete PNG.

The exact saved source/spec was replayed locally, with canvas painted-text
tracing and visual inspection:

- `before/chart.png`: 1598 × 888 pixels; the final three city names were not painted.
- `height547/chart.png`: exploratory near-boundary image; text fits, but the last row is one pixel short.
- `after/chart.png`: 1598 × 1084 pixels; all 17 rows are visible, including the final three, without a scrollbar.

The HTML export already included an additional complete DOM table. It is not
an interactive S2 table (`interactive=false`); its complete text did not make
the embedded PNG complete. Headers and their data were correctly paired in
the original PNG: the reviewer reports of swapped headers were separate false
positives.

Verification: 398 resolver/renderer tests and 47 display-label/conformance/render
tests passed. Added tests check final-row painted text, actual PNG height,
source immutability, explicit undersizing, boundary sizing, and resource limits.

Frozen application hash after this fix:
`096451ded74efcdae3058d3a635924fbc66b41c4796c978706078037f91755a6`.
