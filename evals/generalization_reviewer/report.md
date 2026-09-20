# Frozen synthetic reviewer probe — 2026-09-17

## Result

Both frozen runtimes accepted all six clean images and identified the actual defect in all five eligible
defective images. The candidate did not improve verdict or defect-identification agreement on this small
probe, and it added three evidence-contract retries. This is **not** a human-gold accuracy estimate or a
substitute for the production labelled reviewer set.

| Measure | Baseline | Candidate |
| --- | ---: | ---: |
| Eligible cases completed | 11/11 | 11/11 |
| Clean images passed | 6/6 | 6/6 |
| Defective images rejected | 5/5 | 5/5 |
| Rejections identifying the constructed defect, agent-adjudicated | 5/5 | 5/5 |
| Uncertain / failed / timed out | 0 / 0 / 0 | 0 / 0 / 0 |
| Model requests | 11 | 14 |
| Output-contract retries | 0 | 3 |
| Median case time | 2.009 s | 6.581 s |
| Whole-arm elapsed time | 27.045 s | 127.407 s |
| Input tokens across completed responses | 20,167 | 27,478 |
| Output tokens across completed responses | 672 | 1,479 |
| Provider-reported response cost | $0.00149567 | $0.00271348 |

Same model: `openrouter:google/gemma-4-31b-it:nitro`, with runtime defaults of thinking disabled and
temperature zero in both arms. Reviewer calls use each runtime's unchanged normal `review_chart` path.
No failed trial was rerun; framework retries are retained in the reports and included in timing/usage.

## What the retry traces establish

- **Bar pairing:** the candidate's first summary correctly identified the swapped values, but both
  evidence fields contained the same apostrophe. The validator requested a correction; the second
  response supplied the correct 26-versus-9 comparison. Total: 29.711 s, two requests.
- **Grouped legend:** the first response accurately described both series swaps but omitted `column`
  from its cell references. After a validator retry, it supplied whole-source references. Total:
  18.833 s, two requests.
- **Indicator value:** the first summary correctly said 880 instead of 88, but evidence fields both
  said `8` and the reference lacked row/column. The second response supplied correct evidence. Total:
  21.773 s, two requests.

These are demonstrated output-contract compliance costs, not failures to notice the true visual defect.
The validators prevented accepting inconsistent evidence, but final visual detection was already
correct in the simpler baseline. This probe therefore does not justify claiming intelligence gains from
the richer evidence schema.

Some candidate clean calls were also slow without retry: line 18.966 s with 41 output tokens and
indicator 17.651 s with one request. The two reviewer arms ran while two GLM/Gemma transfer arms were
active. Different cache hits, provider scheduling, network and inference timing were not isolated.
Thus the observed total latency difference cannot be attributed entirely to schema complexity, even
though its three extra requests are directly evidenced. One trial per image/runtime is not a stable
provider-tail estimate.

## Construction and pre-model audit

All content is newly authored synthetic measurement data. The pinned renderer generated each PNG;
no pixel editing, browser/UI automation, old user CSVs, or hidden transfer-bank cases were used.
Six clean/defect pairs were attempted. Every one of the 12 PNGs was viewed before model calls.

Five defect variants were visibly verified: swapped bar value/category pairing, psi-versus-kPa axis
title, swapped grouped-series legend, missing full table row, and an 880-versus-88 headline value.
The scatter defect was excluded before either arm ran: the renderer swapped and correctly relabelled
its axes, so it was not an unambiguous misleading chart. Its image, original construction claim, and
the audit explaining that claim's failure remain in the fixture directory. The faithful scatter is
retained as a sixth clean case. Frozen denominator: six clean plus five defective, not twelve.

Labels are synthetic construction plus agent visual inspection, not independently established human
gold. Final findings from both arms were read against those inspected images and constructions;
all five true defects were identified, rather than merely rejected for an unrelated complaint. The
fixtures are small, English, clear and fully covered by the reference. They do not test Arabic/RTL,
high cardinality, partial references, genuinely ambiguous images, or full-team orchestration.

## Provenance

- Manifest SHA256: `d7ebce54bdd9c468368f9ebf17c0b0ecd6c8bda3d25c77c31ea9b8a00f8a959c`.
- Pre-model visual-audit SHA256: `32d859d4cc44d9cbda5064bcd92dabd8c33f1cdddd34ffe5b14539eef00f4f72`.
- Baseline runtime root: `/private/tmp/vis-generalization-baseline.3SEChZ`.
- Candidate runtime root: `/Users/muhammad/Documents/NACI/pydantic-vis-harness`.
- Root-provided frozen runtime fingerprints: baseline
  `573f65b5b612013ffd94558a396ba375d7891df3be68da410328136b354a6218`; candidate
  `7ff116ba5c5a222c69f3e7d9806f1356d5e1658524b4de10aa7edebe9150929d`.
- Baseline report SHA256: `adba98128b4651d2f94ded5c31d13779b8b61076280f3cb28ccb318dbe3143ee`.
- Candidate report SHA256: `8b02b860bc09f12102828a2409b745aafc168b8a8bb18dcfba4a59869244d0c0`.

The runner reverified all source/image hashes after the calls. Result JSONs retain per-case input and
image hashes, runtime reviewer-file hashes, provider response IDs, usage, tool arguments, retry messages,
timestamps and complete final reviews. There are no credential values in these reports.

Files: `fixtures/manifest.json`, `fixtures/audit.json`, `results/baseline-gemma11.json`,
`results/candidate-gemma11.json`, and `adjudication.json`.
