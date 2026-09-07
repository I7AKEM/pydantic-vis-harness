# Spike: rendering GPT-Vis charts on a server

Date: 2026-09-07. Status: done. Output: a recommendation for the Phase 3 design, not code to keep.

The main design (section 7 and section 18) picked GPT-Vis on G2 as the first renderer and left three questions
open: how to host the Node renderer next to the Python service, whether Arabic text comes out right in a
server-rendered image, and whether the official server package draws our catalogue. This spike answers them.

Everything built for it is throwaway and lives outside git in `.superpowers/spike/gpt-vis-ssr/` on the machine
that ran it: the brief given to the implementer, the specs, the rendered images, the scripts, the implementer's
`REPORT.md` with every command and error text, and `syntax.md` on the text syntax. Codex implemented from the
brief; the images were judged by eye by the controller.

## Answer

Yes on all three. `@antv/gpt-vis-ssr` 0.3.8 draws every one of its 24 chart types to PNG from Node with no
browser. Arabic is shaped and ordered correctly on macOS out of the box and on Debian once a font with Arabic
glyphs is installed. A render costs about a third of a second from a fresh process and under a tenth of a
second in a warm one, which makes the simplest hosting, one Node process per render, good enough.

## What was measured

Machine: macOS on Apple silicon, Node 25, npm 11. Package: `@antv/gpt-vis-ssr` 0.3.8, which brings `canvas`
3.2.3 (cairo 1.18, pango 1.57) as a prebuilt binary. Install: 621 packages, about one minute, 541 MB on Linux.

31 specs covered all 24 types, with Arabic titles, labels, legends and groups on twelve of them, plus three
edge cases: eight labels of 25 to 40 Arabic characters, Hijri years in Arabic-Indic digits, and a title mixing
English, Arabic, a dash and parentheses.

| Measure | Result |
|---|---|
| Types that render to PNG | 24 of 24, 31 of 31 cases |
| Image for a 600 by 400 request | 1800 by 1200 pixels, 3x density is fixed in the package |
| Fresh process, column chart | 305 ms total, of which 89 ms is the render call |
| Warm process over HTTP, column, bar, pie, scatter, treemap | about 80 ms per chart |
| Warm process over HTTP, line, area, dual axes, funnel, waterfall, violin | about 420 ms per chart |
| Warm process memory after 93 renders | 134 MiB at start, 330 MiB after the first round, flat after that |
| Debian container, column chart | 100 to 130 ms render call, 300 ms process |

## Arabic text

Judged by eye on the rendered images:

- Letters connect, words run right to left, and numbers inside Arabic sentences stay in place: "عدد المخالفات
  حسب المدينة 2025" and "المخالفات خلال عام 1446هـ الموافق 2025" both read correctly.
- A title mixing scripts, "Sales by region — المبيعات حسب المنطقة (Q1 2025)", keeps every part in order.
- Arabic-Indic digit categories ("١٤٤٤", "١٤٤٥", "١٤٤٦") render with the right glyphs.
- Legends, grouped and stacked columns, donut labels ("أنثى: 38.4"), treemap cells and word clouds are all right.

What is not right, and is the same for English:

- Titles are left-aligned and categories run left to right. The package has no right-to-left mode. The
  category order follows the data order, so an Arabic chart can be fed its rows in reverse to put the first
  category on the right. Title alignment can only be set on treemap and word cloud today.
- Long category labels are rotated 90 degrees and the plot shrinks to less than half the height. There is no
  wrapping or truncation option. Twelve monthly labels also rotate at a 600 pixel width.
- The funnel writes a hard-coded Chinese label ("转化率", conversion rate) on every step. No other chart has
  user-visible Chinese text.

## Fonts

| Environment | Without any change | What was needed |
|---|---|---|
| macOS | Arabic in Geeza Pro, Latin in Helvetica, chosen by the system | Nothing |
| Debian slim container | Every glyph a box, including digits, because the image has no fonts | `apt-get install fontconfig fonts-noto-core`; Arabic then renders in Noto Sans Arabic with no code change |

An explicit font family works only through a custom theme object added to the package's theme map at run
time, because the light theme in `@antv/g2-ssr` ignores font overrides; the dark-based theme honours them.
`registerFont` accepts TTF, TTC and WOFF files, and rejects WOFF2 with "Could not parse font file". None of
this is needed when the font is installed system-wide.

## Package facts the design must know

- The plain import fails in Node because the spreadsheet dependency imports a CSS file. One line fixes it: a
  no-op require hook for `.css` before loading the package. No file in the package is patched.
- On Debian slim the prebuilt canvas binary needs `libexpat1`; nothing else was missing.
- Unknown option keys are dropped silently. Each chart reads a fixed set: title, axis titles, width, height,
  theme (default, academy, dark), `style.palette`, `style.backgroundColor`, `stack` and `group` on column and
  bar, `innerRadius` on pie, `binNumber` on histogram, and little else. The full per-chart table is in the
  implementer's report. There is no sort, top-N, number or date format, annotation, reference line, log scale,
  legend position or label alignment. Our extension keys from design section 6.3 would all be dropped.
- The dark theme is not supported by the graph charts; organization chart throws under it.
- Maps (district, pin, path, heat) are browser-only in GPT-Vis and are not in the server package.
- Each chart is 70 to 220 lines of G2 configuration on top of `@antv/g2-ssr`, so taking direct control of a
  chart later means copying one file, not writing a renderer.

## The text syntax

The parser for the indented syntax the POC used ("vis pie", "data", "- category ...") lives in
`@antv/gpt-vis` 1.0.1 at `dist/esm/syntax/parser.js`: one hand-written file of 559 lines that imports nothing
and runs in Node without a DOM. Its rules, verified by parsing samples: "key value", "key: value" and
"key=value" all work; section names `data`, `categories`, `series`, `children`, `nodes`, `edges` start lists
and `style` starts an object; list items are dash lines whose first pair opens an object; values become
numbers or booleans when they look like them, and quotes keep them as text; unknown keys pass through. Traps:
a scalar list item with a space or colon ("- North America") silently becomes an object; "data:" with a colon
is a scalar, not a section; there is no escaping, no comments, and malformed lines are skipped without error.

## Recommendation for the Phase 3 design

1. **Host by spawning a Node script per render.** JSON in on stdin, PNG out on stdout, a timeout, no port,
   no long-lived process to babysit. A third of a second per chart is small next to the model calls around it.
   Keep the warm-server numbers above as the fallback if a later phase needs more than a few charts a second.
2. **Write our own parser in Python** for the syntax, following the 1.0.1 rules but strict: a malformed line
   is an error the designer gets back, not a silent skip. Keep a conformance test that parses the same specs
   with the 1.0.1 parser in Node and compares the JSON, so the browser and the server agree on every spec.
3. **Treat the package as a fixed vocabulary.** Declare its accepted keys per chart as the renderer's
   capability table. The check step marks every extension key as degraded with a note the reviewer sees. Sort
   and top-N are applied to the data before render, so they are honoured without renderer support.
4. **Catalogue consequences.** Leave out the funnel until its Chinese label is fixed, the maps because the
   server package lacks them, and the spreadsheet because it is a table. Do not offer the dark theme on graph
   charts. Default time series to a wider canvas so month labels stay horizontal. Add the rule: long category
   labels prefer a horizontal bar.
5. **Deployment.** Node 22 LTS, a `package.json` in the renderer folder pinned to `@antv/gpt-vis-ssr` 0.3.8,
   and on Debian `libexpat1`, `fontconfig` and `fonts-noto-core`. A startup smoke test renders the Arabic
   column spec and compares it with a reference image, which catches a missing font before a user does.
6. **Later, not now.** When number formats, reference lines or a right-aligned title become a real blocker,
   copy that chart's G2 configuration out of the package and drive `@antv/g2-ssr` directly for it.

## Not verified

Windows and Alpine builds of the canvas binary; memory over thousands of renders in one process; the browser
page rendering the parsed JSON with the 1.x package; how the font override behaves on the light theme, which
was worked around rather than solved.
