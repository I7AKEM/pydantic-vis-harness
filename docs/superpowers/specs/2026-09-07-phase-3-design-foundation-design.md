# Phase 3: the design foundation, no model

This document designs Phase 3 of the visualization agent described in `2026-09-06-vis-agent-design.md`. That
document remains the authority on the team, the workflow, and the later phases. This one says exactly what the
chart spec is, what the catalogue and the rules contain, how a chart is checked and drawn, and how we will know it
works. The spike that settled the renderer questions is written up in
`docs/spikes/2026-09-07-gpt-vis-server-renderer.md`.

## 1. Purpose

The analyst answers "what is the answer". Phase 3 builds everything the chart designer will stand on, with no
model in it: a written language for charts, a catalogue of the charts we draw, rules that rank and check them,
and a renderer that turns a spec plus a result table into a picture. A person can hand-write a spec today and get
a correct picture; in Phase 4 a model writes the same spec.

Exit test, from the main design: for a fixed set of result shapes and intents, `recommend_charts` returns the
expected top candidate at least nine times in ten; every edge case in section 8 of the main design that is a
rule or a fix has a test; the renderer draws every catalogue entry from a hand-written spec.

## 2. Scope

In scope:

- The spec: GPT-Vis's indented text syntax plus our extension keys, a strict parser and a serializer in Python.
- The catalogue: twenty chart entries as data, one file, validated when loaded.
- The rules: hard rules that filter, soft rules that score, check rules that find what a written spec gets wrong.
- `recommend_charts`: ranked candidates with the score of every rule for every candidate.
- `check_spec`: violations with a suggested fix each, plus the compromises the chosen renderer will make.
- Resolving a spec against a result table: binding columns to roles, sorting, top N with "Other", null handling,
  emphasis colors, reading direction. Code inserts the rows; no model ever retypes a value.
- The GPT-Vis renderer: a Node script spawned per render, a Python wrapper, a capability table, a PNG, an HTML
  page, and the library's own configuration saved beside them.
- Terminal and programmatic entry points, tests without a model, a recommendation evaluation set, lessons.

Out of scope: the designer agent and its rulebook (Phase 4), the reviewer, artifacts and versions, maps, a second
renderer, date format strings, annotations, hiding axes, changes to the lead, and the chat. Nothing in this phase
calls a model.

## 3. What the spike settled

| Question | Answer | Consequence here |
|---|---|---|
| Hosting the Node renderer | A fresh Node process renders a chart in about 0.3 s; a warm one in 0.08 s | One process per render, no server, no port |
| Arabic in server images | Shaped and ordered correctly; on Linux only once a font with Arabic glyphs is installed | A startup smoke render; fonts are a deployment requirement |
| The package's vocabulary | 24 chart types, a fixed set of keys per chart, unknown keys dropped silently | The catalogue names only what it draws; our own check validates keys; extensions it cannot honour are compromises |
| The text syntax | A 559-line parser in the browser package, no DOM, permissive, with traps | Our parser follows its rules and is strict; a conformance test compares the two on base specs |
| Defects | The funnel prints a Chinese label; graph charts break under the dark theme; long labels rotate | Funnel, maps, and graph charts stay out of the catalogue; a rule prefers horizontal bars for long labels |

## 4. The step, end to end

The worked case from Phase 2: the analyst answered, in Arabic, the share of wealthy citizens by gender. Its
result has four columns: the gender code, its label, the count, and the share, and two rows.

1. A person (later, the designer) asks for candidates: `recommend_charts` takes the analyst's column
   descriptions, the rows, and the intent "proportion" from the brief. It returns, in order: donut, pie, bar,
   column, table, each with its score and the rule-by-rule breakdown. Pie and donut pass because the share is a
   part of one whole with two slices; bar scores lower because the intent is proportion.
2. The person writes the spec:

   ```
   vis donut
   title نسبة المواطنين الأثرياء حسب الجنس
   description حلقة تُظهر نسبة الأثرياء لكل جنس: الذكور 61.6% والإناث 38.4%
   language ar
   bind
     category الجنس
     value النسبة
   sort value desc
   ```

3. `check_spec` parses it, confirms donut is in the catalogue and the renderer draws it, confirms both bound
   columns exist with allowed kinds (a category and a share), runs the check rules, and resolves every key
   against the renderer's capability table. It returns no violations and one compromise: the legend stays where
   the package puts it.
4. The renderer resolves the spec against the result: binds the label column to `category` and the share to
   `value`, sorts by value, takes the percent sign from the share column's unit so the labels read "61.6%", and
   builds the library's configuration in memory. It spawns Node with that
   configuration on standard input and gets a PNG back, then writes the PNG, an HTML page that draws the same
   chart in a browser, and the configuration as a file, in one folder.
5. The caller receives the folder, the compromises, and the render time. In Phase 5 the reviewer receives the
   same, plus the spec and the result table.

Nothing in this path guesses a number. The only numbers in the picture are the result's cells.

## 5. The spec

The contract between the designer and every renderer, as decided in the main design: GPT-Vis's indented syntax,
plus keys of our own in the same style. The text is what is written, stored, shown, and exchanged. The parser and
the renderers share one parsed form inside the code; nothing outside them sees it.

### 5.1 Grammar

Taken from the original parser's rules, then made strict. Every deviation from the original is an error on our
side rather than a guess.

- One statement per line. Blank lines are ignored. The first line is `vis <type>`, where the type is a catalogue
  name.
- A key and its value are separated by the first space or by a colon. The value runs to the end of the line and
  may contain spaces and colons, so a title never needs quotes.
- A key with no value on its line and an indented block under it is a section. Our sections are `bind`, `style`,
  `emphasis`, and `palette`. `bind` and `style` hold key-value lines; `emphasis` and `palette` hold list items,
  one per line, written as `- item`.
- Indentation is two spaces per level. Tabs are an error.
- Values are typed by the key, never by their look: `width` and `height` are integers, `limit` an integer,
  `innerRadius` a number, `group` and `stack` are not written at all (the type says it), everything else is text.
  A category called `001` stays `001`.
- Unknown keys, duplicate keys, a missing type line, a type that is not in the catalogue, and a section that
  should be a scalar are errors with a line number. The original parser skips these silently; we do not, because
  a silently dropped key is exactly the failure the check exists to catch.
- No comments, no escapes, no multi-line values, no quoting. Same as the original.

The serializer writes a spec back in canonical form: keys in a fixed order, two-space indentation, one blank
line nowhere. Parse then serialize then parse gives the same spec.

### 5.2 Keys

Base keys from GPT-Vis; axis titles use screen directions and resolve maps them to the package:

| Key | Type | Meaning |
|---|---|---|
| `vis` | type line | The chart type, a catalogue name |
| `title` | text | Chart title, in the caller's language |
| `axisXTitle`, `axisYTitle` | text | Horizontal and vertical screen-axis titles respectively, on every chart, with real units in brackets when present |
| `theme` | `default`, `dark`, `academy` | Appearance |
| `width`, `height` | integers, default 800 by 450 | Canvas size in points; the renderer draws at three times that |
| `innerRadius` | number, donut only | Hole size, default 0.6 |
| `binNumber` | integer, histogram only | Number of bins |
| `style` | section | `backgroundColor` as a color; `palette` as a list of colors by category order |

Our keys:

| Key | Type | Meaning |
|---|---|---|
| `bind` | section | Chart role to result column, one line per role: `category`, `value`, `group`, `time`, `x`, `y`, `value2` for dual axes. The roles each chart takes are in the catalogue |
| `sort` | `value desc`, `value asc`, `category asc`, `category desc`, `none` | Row order before drawing. Default: `none` for time and ordinal axes, `value desc` otherwise |
| `limit` | integer | Keep this many rows after sorting; the rest become one "Other" row |
| `other` | text | Label of the "Other" row. Default `Other` or `أخرى` by language |
| `unknown` | text | Label for a null category. Default `Unknown` or `غير معروف` by language |
| `emphasis` | list | Category values drawn in the accent color; every other category is muted |
| `palette` | list | Colors by category order; brand colors from the brief. Shorthand for `style` `palette` |
| `direction` | `ltr`, `rtl` | Reading direction of category axes. Default by language |
| `language` | `ar`, `en` | The caller's language; drives the defaults above and the page's text direction |
| `description` | text, required | What the chart shows, in words, for accessibility and for the reviewer |
| `zero` | `true`, `false` | Force the value axis to start at zero on line, area, and box plots. Bars always start at zero |
| `axisYMin`, `axisYMax` | numbers | The value axis range. Allowed on line, multi_line, scatter, boxplot, and dual_axes only; a cropped bar, column, or area lies, so they are rejected there. The range must hold every plotted value |
| `axisXMin`, `axisXMax` | numbers | The horizontal range on scatter only |
| `axisYScale` | `linear`, `log` | Log only on line, multi_line, and scatter, only with positive values that span at least two orders of magnitude, and the axis title says so |
| `percent` | `true`, `false` | On stacked_column, stacked_bar, and stacked_area: each category's stack is scaled to 100 so the segments read as shares, computed in code from the result's own cells; the value axis is titled in percent |
| `labels` | `on`, `off` | Data labels. Default: the renderer decides |
| `legend` | `on`, `off` | The legend. Default: on when a group role is bound |
| `subtitle` | text | A second title line, for the unit, the period, or the filter |
| `format` | pattern | How every number is written, on the value axis, the data labels, and the tooltip together. See below |
| `digits` | `western`, `arabic` | The digit shapes: 1,240 or ١٬٢٤٠. Default western in both languages |

The `format` pattern is plain: `0` writes whole digits, `0,0` adds thousands separators, `.0` or `.00` sets
the decimals, `k` writes compact numbers such as 1.2K and 3.4M, and any text after the number is the unit, so
`format 0,0 SAR`, `format 0.0%`, `format 0k`, and `format 0,0.00 ريال` are all valid. A percent sign sits
against the number; any other unit follows a space. Without `format`, numbers get thousands separators and up
to two decimals, and the unit comes from the bound value column's `unit` in the analyst's description, so a
share reads "61.6%" and an amount reads "1,240 ريال" with nothing written in the spec. A unit in `format`
overrides the column's.

Keys named in section 6.3 of the main design and not listed here (date formats, annotations, hiding axes,
interaction hints) wait for the renderer that can draw them. Adding a key
later is safe because unknown keys are errors today, so no stored spec can contain one.

### 5.3 What the spec never holds

Rows. A spec binds result columns to roles; the renderer inserts the cells. This is the main design's decision
"the model never retypes values", and it also keeps every spec small enough to read.

## 6. The catalogue

One JSON file, validated by a Pydantic model when loaded, tested for completeness. Each entry holds: the name,
aliases, the purposes it serves from the fixed vocabulary (comparison, trend, distribution, rank, proportion,
composition, relation), the roles it binds with the column kinds each role accepts and whether it is required,
the row and cardinality limits its hard rules use, the spec keys it accepts, its rating, and how the GPT-Vis
renderer draws it. The same file is rendered into the designer's prompt in Phase 4.

Column kinds are the analyst's: category, ordinal, time, measure, share, geography, identifier. "Label" below
means category, ordinal, or geography.

| Entry | Roles (required in bold) | Purposes | Rating | Drawn as |
|---|---|---|---|---|
| column | **category** label or time, **value** measure or share | comparison, rank | recommended | column |
| bar | **category** label, **value** | comparison, rank | recommended; preferred for long labels | bar |
| grouped_column | **category**, **group** label, **value** | comparison | recommended | column, group |
| stacked_column | **category**, **group**, **value** additive | composition, comparison | recommended | column, stack |
| grouped_bar | as grouped_column | comparison | recommended | bar, group |
| stacked_bar | as stacked_column | composition, comparison | recommended | bar, stack |
| line | **time** time or ordinal, **value** | trend | recommended | line |
| multi_line | **time**, **group** label, **value** | trend, comparison | recommended | line with group |
| area | **time**, **value** additive | trend | recommended | area |
| stacked_area | **time**, **group**, **value** additive | trend, composition | recommended | area, stack |
| pie | **category** label, **value** additive or share | proportion | use with caution | pie |
| donut | as pie | proportion | use with caution | pie with innerRadius |
| scatter | **x** measure, **y** measure, group label | relation | recommended | scatter |
| histogram | **value** measure, raw rows | distribution | recommended | column |
| boxplot | **category** label, **value** measure, raw rows | distribution, comparison | recommended | boxplot |
| treemap | **category** label, **value** additive | proportion, composition | recommended | treemap |
| radar | **category** label, **value**, group label | comparison | use with caution | radar |
| dual_axes | **category** label or time, **value**, **value2** with a different unit | comparison, trend | use with caution | dual-axes |
| word_cloud | **category** label with many values, **value** | rank | use with caution | word-cloud |
| table | every column | any | recommended fallback | spreadsheet |

"Additive" means the column's aggregate is sum, count, or count distinct, or its kind is share. Grouped and
stacked variants are separate entries, not flags, so each carries its own rules and its own score: the design
says rules cannot tell a grouped bar from a stacked bar, and separate candidates with separate breakdowns are
what the designer needs to decide. The stacked entries also accept `percent`, which turns each stack into
shares of its category's total.

Left out on purpose: the funnel until its Chinese label is fixed, maps because the server package has none,
graph charts and diagrams because they are not drawn from a result table, and the stat card because the
renderer has no such type; a single number is delivered as a one-cell table with a note.

## 7. The rules

Small pure functions in one file, each with an ID, a type, a plain explanation, and a suggested fix. Scores are
bounded and additive; every candidate keeps its breakdown for the explanation and the evaluation set.

### 7.1 Hard rules, which filter

| ID | Rule | Fix suggested |
|---|---|---|
| H1 shape | Every required role has a result column of an allowed kind | Choose a chart that fits the columns |
| H2 time kept | A time column in the result is bound, or the chart is a table | Bind the time column |
| H3 whole | Pie, donut, treemap, and the stacked variants need an additive value | Use a bar for an average |
| H4 sign | Pie, donut, treemap, and stacked variants reject negative values | Use a bar or a line |
| H5 slices | Pie and donut take two to six categories | Use a sorted bar |
| H6 colors | A group role takes at most ten distinct values | Keep the top groups, or use small multiples later |
| H7 points | Line and area need at least three points on the time axis | Use a bar |
| H8 order | Line and area need time or ordinal on the horizontal axis | Use a bar |
| H9 raw | Histogram and box plot need raw values: at least thirty rows and an unaggregated measure | Use a bar of the aggregate |
| H10 units | Dual axes need two measures with different units | Use a grouped column |
| H11 many | More than fifty categories on a bar or column | Keep the top twenty with Other, or a table |
| H12 empty | An empty result has no candidates | Ask, do not draw |
| H13 alias | On an entry with a group role, reject when the bound group and category are one-to-one label aliases: "The group is a label of the category." | Bind the label as category and drop the group |
| H14 whole | Pie, donut, and treemap reject when any share column in the result does not sum to one whole, even if unbound: "The shares are of different wholes; they do not add up to one." | Use a bar |

### 7.2 Soft rules, which score

| ID | Rule | Score |
|---|---|---|
| S1 intent | The entry serves the request's intent | +3 |
| S2 suggested | The entry matches the brief's suggested chart, a preference not an order: it wins a tie against charts the rules rate equally, and loses to any hard rule | +3 |
| S3 caution | The entry is rated use with caution | −1 |
| S4 count | Categories on a bar or column: up to twelve +1, thirteen to twenty 0, more −2 with the fix "sort and keep the top N with Other" | as stated |
| S5 long labels | The longest category label is over fifteen characters: bar +1, column −2 | as stated |
| S6 balance | Pie or donut slices within ten percent of each other in size | −2, fix "use a sorted bar" |
| S7 time reads | A time axis on a line or area +2; on a bar −2 | as stated |
| S8 composition | Stacked variants +1 when the intent is composition; grouped variants +1 when it is comparison | as stated |
| S9 unbound | A measure or share left unbound −1 each; a label column left unbound −1, except an alias of any bound column, a code column whose source is the bound label's source, and identifiers | as stated |
| S10 few points | Scatter with fewer than ten rows | −2 |
| S11 words | Word cloud with fewer than twenty categories | −3 |
| S12 fallback | Table is always a candidate at 0 before other rules | 0 |
| S13 one number | A one-row, one-measure result: table +2, every chart −3 | as stated |
| S14 few parts | A treemap whose category has seven or fewer values: pie takes up to six, and a sorted bar takes the rest | −2, fix "use a pie, a donut, or a bar" |

Ranking: sum of the soft scores among the candidates that passed the hard rules, highest first, ties broken by
catalogue order. Intent unknown means S1 scores nothing for everyone. The table never receives S1: its purposes
list every intent so it is always eligible, and it stays the zero-score fallback.

### 7.3 Check rules, on a written spec

| ID | Rule | Fix suggested |
|---|---|---|
| C1 type | The type is in the catalogue and the renderer draws it | Name a catalogue entry |
| C2 bound | Every bound column exists in the result with a kind the role accepts; every required role is bound | Bind the missing role |
| C3 keys | Every key is one the entry accepts | Remove the key |
| C4 order | Sort is `none` on a time or ordinal axis | Remove the sort |
| C5 limit | `limit` needs a category axis, a sort by value, and additive values (including `value2`) for Other | Sort by value, or drop the limit |
| C6 colors | Palette entries are hex colors; cover the bound group when present, otherwise category for pie, donut, treemap, and word cloud; one colour suffices for single-series entries, two for dual axes | Add colors or drop the palette |
| C7 contrast | Every palette color and the accent contrast with the theme background at least 3 to 1 | Pick a darker or lighter color |
| C8 words | A title and a description are present | Write them |
| C9 emphasis | Emphasised values exist in the bound category, or in the bound group on charts with a group role | Fix the spelling |
| C10 hard | The hard rules of section 7.1 pass for this type on this result | As the hard rule says |
| C11 range | `axisYMin` and `axisYMax` only on line, multi_line, scatter, boxplot, and dual_axes; `axisXMin` and `axisXMax` only on scatter; minimum below maximum; every plotted value inside the range | Widen the range or drop it |
| C12 crop | A line's value axis may start above zero, through `zero false` or `axisYMin`, only when the values are narrow: the smallest is above half the largest. The start value is recorded as a compromise so the explanation states it | Start at zero |
| C13 percent | `percent` only on the stacked entries, with an additive value and no negative values | Drop it, or use a share the analyst computed |
| C14 log | `axisYScale log` only on line, multi_line, and scatter, every value positive, largest at least a hundred times the smallest | Use linear |
| C15 labels | `labels on` with more than twelve displayed marks on bar and column entries, or fifty elsewhere (category count times group count after a valid limit, capped by raw rows) | Turn them off, or limit the rows |
| C16 contradiction | `zero true` together with an `axisYMin` other than zero | Drop one |
| C17 format | `format` follows the pattern of section 5.2; `k` and decimals together are allowed, `%` as a unit on a value that is not a share is a warning-level compromise, not an error | Rewrite the pattern |
| C18 sort target | An explicit `sort value …` requires a bound `value`; `sort category …` requires a bound `category`. A derived default sort does not trigger this rule | Remove the sort |
| C19 limit positive | `limit` must be at least 1 | Use a limit of 1 or more |

`check_spec` reports every violation at once, each with its fix, so a repair is one turn.

### 7.4 The main design's edge cases, mapped

Each edge case in section 8 of the main design that is a rule or a fix gets a test that names the rule.

| Edge case | Rule |
|---|---|
| More than about twenty categories on a bar | S4, H11 |
| Pie with more than six slices or slices too close | H5, S6 |
| A second categorical column with high cardinality | H6 |
| Long category labels | S5 |
| Unique-per-row values are identifiers | S9 exempts them; the analyst's kind says identifier |
| Line and area need time or ordinal | H8 |
| Fewer than three time points is not a trend | H7 |
| Never truncate a bar's value axis | C11 rejects an axis range on bars, columns, and areas; the renderer starts bars at zero |
| A line may start above zero only when the range is narrow, with a note | C12 |
| Log scale only for positive values spanning orders of magnitude, always labelled | C14 |
| Negative values rule out pie and percent-stacked | H4 |
| Dual axes only when units differ | H10; the brief's ask is S2 |
| Percentages with the denominator stated | The analyst's job; a share without a denominator does not validate |
| Units and number formats come from the profile and the brief | The unit default from the analyst's column description; `format` overrides it, C17 |
| A single number is not a chart | S13 |
| Empty result: ask | H12 |
| Data labels only when marks are few | C15 |
| Palettes cap at ten colors, colorblind-safe | H6; the default palette is the renderer's ten |
| Emphasis on a few marks | `emphasis`, section 9 |
| Colors the caller names are honoured by category | `palette`, C6, C7 |
| Portrait favours horizontal bars | Not in this phase: the canvas is always landscape |

Edge cases that are query patterns or profiler flags (mixed granularity, wide to long, sampling, time zones) are
already the analyst's and the profiler's and are not repeated here.

## 8. The two functions

Plain functions with typed inputs and outputs, so Phase 4 registers them as tools without change.

`recommend_charts(columns, result, intent=None, suggested=None) -> Recommendation`. `columns` are the
analyst's `ResultColumn` descriptions, `result` the analyst's `QueryResult`. It measures what it needs from the
rows in code: distinct counts, the longest label, signs, slice balance, whether a time column is bound. It returns
the candidates in rank order, each with its name, total score, the rule breakdown as a list of rule ID, score,
and explanation, and the hard rules that removed the entries that failed, so the explanation can say why a
suggested chart was overridden.

`check_spec(text, columns, result, renderer="gptvis") -> SpecCheck`. Parses the text, returning parse errors
with line numbers as violations when it cannot; runs the check rules; asks the renderer's capability table about
every key and value. It returns the violations with fixes, the compromises (the keys the renderer will honour
only partly, each with what it will do instead), and the canonical text when the spec passed.

Both run in milliseconds and call no model.

`describe` retains raw alias and share-whole facts on `ResultShape`, including after a display limit.
New pair counts and share sums are DuckDB queries over the bounded result; Python assigns the flags.

| Binding fact | Measurement and default binding |
|---|---|
| Label aliases | For every pair of category, ordinal, or geography columns, the distinct pair count must equal both columns' distinct counts and be nonzero. Counts of individual labels exclude nulls; pairs containing nulls do not establish an alias. `ResultShape.aliases` stores unordered pairs and `is_alias(a, b)` tests membership. Keep the existing cardinality and column-order preference between independent labels; among aliases, prefer the longest longest label as category, retaining column order on a tie. Never bind an alias of category as group. If a required group is unavailable, recommendation rejects via H1; explicit alias-group bindings fail H13 through C10. |
| Share wholes | `ColumnShape.sums_to_whole` is true for numeric share columns whose non-null sum is in inclusive [99, 101] or [0.99, 1.01], false otherwise (including empty, all-null, or nonnumeric shares), and null for other kinds. Either scale is accepted without guessing from unit text. Pie, donut, and treemap prefer a share summing to a whole, then an additive measure (`sum`, `count`, `count_distinct`), then any share, then remaining measures subject to H3. H14 still checks every share in the raw result, so binding a count or applying a limit cannot hide shares of different wholes. |

## 9. Resolving the data

The renderer, not the spec, holds the rows. Resolving happens in code, once, before the library sees anything:

1. Bind: for each role, take the bound column's cells. Measures must be numeric; a text cell in a measure column
   is an error, not a coerced number.
2. Nulls: a row with a null value is dropped and counted in a compromise note. A null category is labelled with
   `unknown`.
3. Sort: as the spec says, or the default for the axis kind.
4. Limit: keep the first `limit` categories after sorting, including every group record; add one `other` record
   per group only when a tail exists. All folded measures must be additive (including `value2`); C5 rejects a
   missing category axis or non-additive measure. Row counts include what was folded. Checks count displayed
   categories as `min(distinct, limit + 1)` after a valid limit; all value statistics and label membership stay raw.
5. Percent: on a stacked entry with `percent true`, each value is divided by its category's total and
   multiplied by 100, so the stack reads as shares. C13 has already required an additive value. The axis title
   becomes the percent sign unless the spec gives one, and the range checks run on the scaled values.
6. Colors: `palette` follows the package's colour domain order: bound groups first, otherwise categories or
   series as C6 specifies. On single-series column, bar, line, area, scatter, histogram, and boxplot entries,
   a written palette uses only its first colour. A scatter with a bound group, the grouped and stacked entries,
   pie, donut, treemap, word cloud, radar, and dual axes keep the whole list. `emphasis`
   builds the palette for the bound group when present, otherwise category, using the accent and muted grey.
7. Direction: `rtl` reverses the category domain only for `column`, `grouped_column`, and `stacked_column`,
   putting the first category on the right. Bars keep the sorted category order top to bottom. The title is
   right-aligned through the renderer's overrides; the legend stays where the package puts it. Time axes are
   never reversed.
8. Numbers: the format is written as a small description, the digit pattern, the decimals, compact or not, the
   unit and its side, and the digit shapes, taken from `format` and `digits` or from the defaults and the bound
   column's unit. Inherited units whose stripped, lowercased text is `count`, `counts`, `number`, `n`, `عدد`,
   or `رقم` become null; an explicit format unit is kept as written. Histogram count-axis formats remain unitless,
   and the second dual-axis series uses its own column's cleaned unit. It travels in the configuration as data;
   the Node script and the page each build the same formatting function from it, from one shared file,
   so the picture and the page write every number alike.
9. Shape: rows become the library's records for the entry, `category`, `value`, `group`, `time`, `x`, `y`, or
   `name` and `value`, as the catalogue says. Every category, group, and time value is text: integers use
   their digits, floats their shortest representation without a trailing `.0`, and strings stay unchanged.
   Time columns (including those bound as category) whose displayed values all parse as `YYYY-MM-DD` with
   an optional T/space time and zone use one precision for the whole column: `YYYY` for January 1 midnight
   buckets, `YYYY-MM` for first-of-month midnight buckets, `YYYY-MM-DD` for other midnight dates, and
   `YYYY-MM-DD HH:MM` otherwise. Keep local clock values without converting zones; an unparseable value
   leaves the whole column as text. Conversion precedes sorting, folding, emphasis matching, and RTL domains.
   Choose the coarsest pattern satisfying those zero-unit conditions that preserves the number of distinct
   source values, increasing to `YYYY-MM-DD HH:MM:SS` and then `YYYY-MM-DD HH:MM:SS.ffffff` when needed,
   or retaining the original text if none preserves distinctness.
   Gregorian time text is drawn in chronological order whatever order the analyst returned; Hijri and
   other non-Gregorian time text is never shortened or reordered.
   Histogram resolution measures `binNumber` equal-width bins (default 10) over the bound value's minimum
   and maximum in DuckDB, using the result's own cells. Bins include their lower bound and exclude their
   upper bound, except the last includes the maximum. Empty bins retain zero counts. Python writes each
   `category` as `<low>–<high>` with the shared default number description (thousands separators, initially up to two
   decimals with trailing zeros trimmed, the spec's digit shapes, no unit or compact notation); `value` is
   the measured count. Boundary precision shows the bin width's first significant digit plus one (at least two decimal
   places), increasing one place at a time until all bin labels are unique while trimming trailing zeros
   and keeping integer boundaries as integers, or raising a resolve error if numeric boundaries coincide.
   These records go to the package's `column` type in ascending numeric bin order,
   never reversed by RTL. `binNumber` remains a histogram spec key and is consumed by resolve. A constant
   range becomes one `<value>–<value>` bin; no non-null values produces no bins; a nonpositive bin count
   raises a resolve error. Drawn-row accounting retains the number of non-null source observations.

Tables retain every column and row in result order. Headers and record keys use the analyst's column meanings;
empty or whitespace-only meanings and all colliding headers fall back to column names, repeating fallback if it
causes another collision. A `tableFormats` map holds each header's NumberFormat description with its cleaned
column unit, decimals null (up to two, trimmed), and the spec's digits. A table's global `format` remains
degraded: each column uses its own default description.

Axis titles name screen axes in the spec. For bar, grouped_bar, and stacked_bar, resolve sends the spec's
`axisYTitle` to the package's vertical category `axisXTitle`, and the spec's `axisXTitle` to its horizontal
value `axisYTitle`. Defaults remain the category name vertically and the value name horizontally; a percent
stack defaults the value-axis title to `%` unless explicitly titled. Other chart mappings are unchanged.
Histogram axis titles default to the bound value column on X and the language's count word on Y (`Count` / `العدد`); explicit titles override both.

Every transformation here is arithmetic on the result's own cells, in line with rule 6 of the main design.

## 10. The renderer

One renderer in this phase, in code, with a declared capability table.

**The Node side.** A folder holding a `package.json` pinned to `@antv/gpt-vis-ssr` 0.3.8 with its lock file,
and one small script. The script reads the library configuration as JSON on standard input,
installs the one-line no-op loader for CSS files that the package needs, renders, writes the PNG to the path
given on the command line, and prints a JSON line with the render time, the pixel size, and the share of pixels
that differ from the background, then exits. Any error is a JSON line on standard error and a non-zero exit. The
script is the whole Node surface; nothing else in the project runs JavaScript. For spreadsheet configurations,
it builds `makeFormatter(tableFormats[header])` from the shared formatter and replaces numeric cells with
formatted strings before drawing. Text and null cells are untouched. The script returns that formatted
configuration to Python so `config.json` and the standalone page use exactly the strings drawn in the PNG.

**The overrides.** The package reads a fixed set of keys and drops the rest, so the script honours our keys by
merging a small set of settings into the configuration the package builds, through one hook on the library's
chart-creation function, the point the spike showed can be intercepted: the axis range and scale, the title
alignment and the category order for right-to-left, the label and legend switches, the subtitle, and the number
formatting function on the value axis and the data labels. The overrides are plain G2 options, listed in one
place in the script, and the package version is pinned so a change to its internals shows up as a failing render
test rather than a silent loss. On request the script also lists every piece of text it drew, which is how the
tests assert that a label reads "61.6%" without decoding pixels.
`labels on` forces formatted value labels (`y` for scatter, `value` for bars, columns, histogram bin counts,
pie/donut, boxplot, treemap, and word cloud); histograms use resolved column records with unitless count
formatting, not the package's histogram binning. Child-built line/area/dual-axis charts, pivoted radar, and tables
report a compromise. `legend on` removes the package legend setting to allow G2's default colour legend;
charts without a meaningful colour encoding report "no legend: the chart has one series". `off` suppresses both
switches recursively. Radar tick formatting applies to every `position`, `position1`, … axis as well as `y`.

**The Python side.** `render(spec, columns, result, out_dir, *, compromises=()) -> Rendered`: resolves the data, builds the
configuration, spawns `node` with a 20 second timeout, and writes three files in `out_dir`: `chart.png`,
`chart.html`, and `config.json`. `Rendered` carries the three paths, the pixel size, the compromises, the
non-background share, and the seconds. A missing `node` or an uninstalled package raises a failure whose message
holds the install command; a timeout kills the process and raises. Nothing is retried.
The CLI passes check-time compromises; render combines them with resolve and page compromises, deduplicated
by `(key, message)` in first-appearance order. A `ResolveError` is a spec error: CLI exit 2 with JSON `error`.

**The page.** A standalone HTML file that draws the chart in a browser from the same G2 configuration the
script captured after its overrides, with G2's browser build from a pinned CDN address, so the page and the PNG
are one chart: the same axis range, order, formats, and labels. The configuration is inline as JSON with the
number description of section 9, and the page rebuilds the formatting function from it with the shared file. The
description is the image's alternative text, the page direction follows the spec's language, and the PNG is
embedded as a fallback so the page shows the chart offline. The table entry is a plain HTML table on the page,
not a G2 chart; Python builds it from the formatted spreadsheet configuration also saved in `config.json`,
with escaped meaning headers and cells, so it works offline without fetching a file. `config.json` beside them
holds that same captured configuration and the table format descriptions, which is what "the library's
own configuration" means from here on.

**The capability table.** Per catalogue entry, which keys the renderer honours, which it degrades and how, and
which it rejects. Honoured: the base keys, `bind`, `sort`, `limit`, `other`, `unknown`, `emphasis`, `palette`,
`language`, `description`, `subtitle`, `percent`, `zero`, `axisYMin`, `axisYMax`, `axisXMin`, `axisXMax`,
`axisYScale`, `labels`, `legend`, `format`, `digits`, the unit default, and `direction` for the title and the
category order. Degraded: `direction` for the legend, which stays where the package puts it. Rejected: nothing
in the Phase 3 vocabulary.

**Size.** The default canvas is 800 by 450 points, drawn at three times that. Line and area charts with more
than twelve points use 1200 wide unless the spec says otherwise, because the spike showed monthly labels rotate
below that.

**Deployment.** Node 22 LTS on the path and `npm ci` in the renderer folder. On Debian also `libexpat1`,
`fontconfig`, and `fonts-noto-core`; on macOS nothing more. At startup the application renders the Arabic column
spec from the test set once and refuses to start rendering when the non-background share is below what a drawn
chart produces, which catches a missing font before a user sees boxes. The folder of installed packages is about
540 MB and is never committed.

## 11. Entry points

- Terminal: `vis recommend REPORT.json [--intent trend] [--suggested line]` prints the ranked candidates with
  breakdowns; `vis check SPEC [--report REPORT.json]` prints violations and compromises; `vis render SPEC
  --report REPORT.json [--out DIR]` checks, renders, and prints the three paths. `REPORT.json` is the file
  `vis ask` prints, so the whole path from a question to a picture runs by hand in three commands.
- Program: `recommend_charts`, `check_spec`, and `render` as in sections 8 and 10.

The lead is unchanged in this phase. Rendered folders go under the data directory beside the uploads, one folder
per render named by a hash of the spec and the result, until artifacts arrive in Phase 6.

## 12. Tests

No model anywhere in this phase, so every test is plain input and expected output:

- The parser: each key type, both separators, sections and lists, canonical round trip, and one test per error
  class with its line number.
- Conformance: the base-vocabulary specs from the catalogue tests parsed by our parser and by the original
  parser through Node give the same JSON. Skipped with a reason when Node or the package is absent.
- The catalogue: loads, every entry names a drawn type and at least one purpose, every role names allowed kinds,
  and every alias is unique.
- Every rule of section 7 with one input that violates it and one that satisfies it, named by rule ID, covering
  the table in section 7.4.
- `recommend_charts` on the evaluation set of section 13, asserting the exit threshold.
- `check_spec` on a passing spec, a spec with three violations reported together, and a spec with compromises.
- Resolving: sort orders, limit with Other, a non-additive limit rejected, nulls, emphasis palettes, right-to-left
  reversal, text in a measure column.
- The renderer: every catalogue entry renders from a hand-written spec to a PNG of the expected size with a
  non-background share above the floor; the Arabic column spec; a timeout; a missing package. Skipped with a
  reason when Node or the package is absent. The images are written to a folder for inspection by eye.
- The overrides: for each key the hook honours, the configuration handed to the library carries the expected
  setting, checked by capturing it, and the chart still renders.
- Formats: the pattern parser on every form of section 5.2 and the invalid ones; the default unit from the
  column; and, through the script's text listing, a rendered chart whose labels read "61.6%", "1,240 ريال",
  "1.2K", and "١٬٢٤٠".
- The three terminal commands.

Pictures are checked by size and non-background share, not by pixel equality, because fonts differ between macOS
and Linux and a reference image from one does not match the other. The render tests write every picture to an
ignored folder when asked with an environment variable, for people to look at; the pictures are not committed.

## 13. The evaluation set

At least thirty cases of result shape plus intent with the expected top candidate and the acceptable
alternatives, in `evals/designer/cases.json`, with the reasons in `decisions.json`. Shapes come from the
analyst's evaluation set: its sixty-one expected tables give real column kinds, cardinalities, and label lengths,
and its questions give intents. Cases are chosen to cover every catalogue entry at least once as the expected
top, plus the fallbacks: a one-number result, an empty result, fifty categories, seven slices, two time points,
raw values for a histogram, two measures with different units.

Scoring: a case passes when the top candidate is the expected one or an acceptable alternative. The exit
threshold is nine in ten. There is no model, so the score is deterministic; the threshold exists because a few
shapes are genuinely ambiguous between two good charts, and a rule change that helps one case may cost another.
The runner prints the failing cases with their breakdowns so the rule at fault is visible.

## 14. Files

Phase 3 adds two packages: the designer's tools, which the designer agent joins in Phase 4, and the render step.

| File | Purpose |
|---|---|
| `vis_agent/designer/models.py` | The spec, the recommendation, the spec check, the compromise |
| `vis_agent/designer/syntax.py` | Parser and serializer of section 5 |
| `vis_agent/designer/catalogue.json`, `catalogue.py` | The entries of section 6 and their loader |
| `vis_agent/designer/rules.py` | The rules of section 7, one function each |
| `vis_agent/designer/recommend.py`, `check.py` | The two functions of section 8 |
| `vis_agent/designer/resolve.py` | Section 9 |
| `vis_agent/render/base.py` | The renderer protocol, the capability table shape, `Rendered` |
| `vis_agent/render/gptvis.py`, `vis_agent/render/gptvis/{package.json,package-lock.json,render.mjs,format.js,page.html}` | Section 10; `format.js` is the one formatting function, used by the script and inlined into the page |
| `vis_agent/cli.py` | `recommend`, `check`, `render` |
| `evals/designer/{cases.json,decisions.json,run.py}` | Section 13 |
| `tests/designer/`, `tests/render/` | Section 12 |
| `README.md`, `AGENTS.md`, `docs/phase-3-lessons.md` | How to write a spec and render it; the new package rule; lessons |

## 15. Decisions taken before the plan

1. **One Node process per render.** Decided from the spike's numbers. A warm server is kept as a measured
   fallback, not built.
2. **Our own strict parser in Python.** Decided. The original parser's silent skips are the failure mode the
   check exists to catch; a conformance test keeps the two in step on the base vocabulary.
3. **Values typed by key, not by look.** Decided, so `001` and `1446` stay text when they are categories.
4. **Grouped and stacked charts as separate catalogue entries.** Decided, so each carries its own rules and
   score. The renderer maps them to the library's flags.
5. **Extensions limited to what has a consumer now.** Decided: bind, sort, limit and Other, unknown, emphasis,
   palette, direction, language, description, subtitle, zero, and, added at the owner's request on 2026-09-07,
   the axis ranges, the log scale, percent stacks, the label and legend switches, number formats, and digit
   shapes. Date formats, annotations, and hidden axes wait for a renderer that draws them; the strict parser
   makes adding them later safe.
6. **Pictures checked by size and non-background share, not by pixel equality.** Decided, for the font reason
   in section 12; the pictures are inspected by eye and kept out of git. Exact references generated on Linux in
   a container remain an option.
7. **Funnel, maps, graph charts, and the stat card left out.** Decided from the spike. A single number is a
   one-cell table with a note.
8. **No lead change and no chat in this phase.** Decided: the phase has no model, and the three terminal
   commands cover "a human hand-writes a spec and gets a picture".
9. **A hook for overrides.** Recommended and assumed: the script merges the axis range and scale, the
   right-to-left title and order, the label and legend switches, and the subtitle into the configuration the
   package builds, through the chart-creation function the spike showed can be intercepted. The package version
   is pinned and the render tests guard it. The alternative, driving G2 directly per chart, costs a file per
   entry and is kept for when the hook is not enough.
10. **Numbers formatted once, from a description.** Decided on 2026-09-07: the unit comes from the analyst's
    column by default, `format` overrides it, and one shared formatting function serves the script and the
    page, so the page draws the captured G2 configuration rather than the GPT-Vis browser component, which
    would not see any override.

## 16. Lessons to record

Which rules disagreed with a human on the evaluation set and how the scores were tuned. Which specs a person
found hard to write by hand, which tells Phase 4 what the designer's rulebook must say. Which compromises the
renderer made most often. Render time and image size per entry on macOS and on Linux. Whether the
non-background check caught anything. Whether the conformance test ever failed and why.

## 17. Capturing mistakes so they do not return

The designer has no rulebook yet because it has no model. Its code is the rulebook: every confirmed mistake in
a recommendation, a check, or a picture becomes a case in `evals/designer` plus a rule or a rule score change,
with the story in the lessons file, as the standing rules of Phase 2 require. The compromises list is where the
renderer's limits are written down, so the reviewer in Phase 5 judges the designer, not the library. The
recommendation set runs before every merge like the profiler's and the analyst's sets.

## 18. Effort

Seven to ten working days: two for the spec and the parser with its conformance test, two for the catalogue and
the rules with their tests, one for the two functions and resolving, two for the renderer, the page, and the
terminal commands, one for the evaluation set, one for the Linux check, the startup smoke test, and the
documents. The main design estimated eight to twelve before the spike removed the renderer unknowns.

## Appendix: how this maps to Pydantic AI

| Design idea | Pydantic mechanism |
|---|---|
| The spec, the recommendation, the check, the compromises | `BaseModel` contracts with field descriptions, so Phase 4 exposes them as tool schemas unchanged |
| The catalogue as data | A JSON file validated into a model at import; the same model renders the designer's prompt in Phase 4 |
| The two functions as future tools | Plain functions with typed parameters and typed returns; Phase 4 registers them with `agent.tool` and returns their models as tool results |
| The renderer failure | A plain exception in this phase; Phase 4 maps it to `ToolFailed` because the model cannot fix a missing font |
| The evaluation set | A `pydantic_evals` dataset with a top-candidate evaluator, no model in the task |
| Tests | `pytest` with fixed inputs; the Node-dependent tests skip with a stated reason when the runtime is absent |
