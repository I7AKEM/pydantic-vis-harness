# `labels on` replaces working pie-label defaults

Local-only diagnostic, not another real-model trial or a retroactive case pass.
No runtime source code was changed. Both actual images were opened and inspected.

Source: `results-parallel20-glm-production-v3-assets/corpus-vizcsv-6eff7ae46ebb4edf/`.
Original render: `renders/cc842f40687c/chart.png`.
The original valid spec uses `innerRadius 0.6`, `labels on`, and `legend on`.
Its white inside labels are visibly clipped at the inner/outer ring boundaries.

Replay: parse the exact saved design and change only `Spec.labels` from `"on"`
to `None` (omit the option), then call the same `gptvis.render` with the saved
`AnalysisReport`, original columns, source rows, and `trace=True`.
Output: `labels-omitted/chart.png`, 2400×1350, both source rows retained.

Assertions confirmed the original and replay configurations have identical
`gptvis` input, dimensions, data, display mappings, number formatting, and every
override except `labels`. The removed override is `[{"text":"value"}]`.

The original merged G2 labels lose the pinned package's `position: outside`,
`radius: 0.85`, `fontSize: 12`, and `overlapHide` transform. Omitting only
`labels on` restores those defaults and visibly shows both complete category
names and correct values outside the ring: وافد375,161 and مواطن373,877.
The original top legend remains unchanged, isolating labels from legend layout.

Cause: `designer/resolve.py` replaces the labels array with a generic value
label for explicit on; `render/gptvis/render.mjs` deep-merges that replacement
over package options. Explicitly enabling already-visible labels is therefore
not equivalent to preserving their default placement/collision behavior.

This is a concrete abstraction/API-semantics issue contributing to the observed
model difference. Claude's initial output omitted the option and kept the
working outside-label default. It does not prove that all GLM designs or all
chart types fail, nor that the library lacks outside-label capability.
Runtime repair is intentionally deferred until the controlled comparison ends.
