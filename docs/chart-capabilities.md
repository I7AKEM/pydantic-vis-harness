# Chart capability lookup

`chart_capabilities` is a shared optional tool for the visualization lead and designer. It answers two
different questions without confusing them:

1. What the internal `vis` DSL accepts for every chart and for a selected chart type.
2. What the installed, pinned `@antv/gpt-vis-ssr` renderer can execute, including fixed mappings,
   degraded options, rejected options, and supported repairs for visible defects.

An empty `chart_type` returns the common configuration and a compact matrix of every exposed chart.
A chart type or alias returns roles, accepted column kinds, chart-specific configuration, its renderer
target, and fixed options. `problem` can be `label_overlap`, `legend_overlap`, `clipping`, `low_contrast`,
or `too_many_categories` to retrieve only relevant, executable repair advice.

The tool reads the declared and installed SSR versions, its embedded GPT-Vis dependency, the separate
browser reference version, and the installed package's `VisOptionMap`. The
catalogue and renderer capability registry remain the executable source of truth. Website documentation
may describe a newer browser package and must not silently expand this contract.
Native renderer types that are installed but not safely exposed by the internal DSL are reported separately;
their presence is not treated as permission for either agent to emit raw renderer configuration.

AntV does publish an official `chart-visualization` skill at
<https://github.com/antvis/chart-visualization-skills>. Its chart-selection and generation guidance is
useful advisory context, but it targets AntV more broadly and does not replace this project's pinned SSR
package, resolver, validator, or rendering tests.
