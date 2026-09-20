# Explicit label/legend switches retain working package defaults

Local-only fix verification, 2026-09-17. This is not a new model trial and does
not change the frozen case-bank or the original 20-case experiment scores.

## Change

The renderer adapter now treats the existing DSL `labels on` override as an
enable fallback: if the pinned package already supplies labels, their placement,
font size, offsets, and collision transforms are retained. If it supplies no
labels, the resolver's generic value label still enables them. `labels off`
continues to disable labels, including child marks.

The same proven toggle problem affected `legend on`: it replaced the pie
package's bottom-centered layout with a boolean and then deleted that boolean.
An existing legend object is now retained; `on` still enables a default-off
legend and `off` still disables it. No raw AntV options or new DSL settings were
introduced, and `node_modules` was not edited.

## Retained-case replay

`../replay_enabled_fix.py` reads the exact saved original donut spec and
`AnalysisReport` from
`../../results-parallel20-glm-production-v3-assets/corpus-vizcsv-6eff7ae46ebb4edf/`.
Both original switches remain `on`; neither the spec nor source rows are edited.

Run from the repository root:

```sh
PYTHONPATH=. .venv/bin/python evals/lead/labels-on-probe/replay_enabled_fix.py
```

The script refuses to overwrite this output directory. Its assertions confirm:

- GPT-Vis inputs, requested overrides, number formats, display mappings, data,
  and every resulting G2 property except labels/legend are unchanged.
- Both source rows are drawn, with zero dropped/folded rows.
- Pie labels keep outside placement, radius 0.85, and `overlapHide`.
- The legend keeps bottom position and centered layout.
- The original checkpoint, PNG, HTML, and config files keep their SHA-256 hashes.

The new real renderer output is `chart.png` (2400 × 1350), with SHA-256
`cfdc371e5265f694a9b28f27289385fe4af8831dd5f78408bdb2793387867c53`.
Render-only time was 0.173 seconds, not model/end-to-end latency.
The original and new PNGs were opened and visually inspected: the original
white inside labels are clipped; the new outside labels fully show
`مواطن: 373,877` and `وافد: 375,161`, matching the source and legend.

## Regression tests

Before the adapter fix, nine of the initial eleven default-preservation tests
failed (seven label defaults and both pie/donut legend layouts). After the fix:

```text
.venv/bin/python -m pytest -q tests/designer/test_resolve.py tests/render/test_gptvis.py
418 passed in 40.06s
```

Tests cover pie/donut, bar/column, grouped/stacked marks, histogram defaults,
numeric formatting, explicit off, and generic labels/legend enabling where the
package default is off. This does not certify every arbitrary chart layout; it
guards the concrete abstraction bug without adding an automatic repair loop.
