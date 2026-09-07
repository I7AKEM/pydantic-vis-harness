"""Catalogue filters, scores, and written-spec checks as small pure rules."""

import re
from dataclasses import dataclass

from vis_agent.models import Intent

from .catalogue import CATALOGUE, CatalogueEntry
from .models import Spec, Violation
from .shape import ColumnShape, ResultShape

STACKED = {"stacked_column", "stacked_bar", "stacked_area"}
BARS = {"bar", "grouped_bar", "stacked_bar"}
COLUMNS = {"column", "grouped_column", "stacked_column"}
LINES = {"line", "multi_line"}
ADDITIVE = {"sum", "count", "count_distinct"}


@dataclass
class Context:
    intent: Intent | None = None
    suggested: str | None = None


@dataclass
class RuleResult:
    rule: str
    score: int
    explanation: str
    fix: str
    hard: bool = False


def _additive(value):
    return value is not None and (value.aggregate in ADDITIVE or value.kind == "share")


def h1_shape(entry, shape, binding, context):
    if any((role.required and name not in binding) or
           (name in binding and binding[name].kind not in role.kinds)
           for name, role in entry.roles.items()):
        return RuleResult("H1", 0, "Required roles need columns of allowed kinds.", "Choose a chart that fits the columns", True)


def h2_time_kept(entry, shape, binding, context):
    if shape.times and entry.name != "table" and not any(c.kind == "time" for c in binding.values()):
        return RuleResult("H2", 0, "The time column is left unbound.", "Bind the time column", True)


def h3_whole(entry, shape, binding, context):
    if entry.additive_value and "value" in binding and not _additive(binding["value"]):
        return RuleResult("H3", 0, "This chart needs an additive value or share.", "Use a bar for an average", True)


def h4_sign(entry, shape, binding, context):
    if entry.name in {"pie", "donut", "treemap"} | STACKED and "value" in binding and binding["value"].has_negative:
        return RuleResult("H4", 0, "Parts of a whole cannot be negative.", "Use a bar or a line", True)


def h5_slices(entry, shape, binding, context):
    category = binding.get("category")
    if category and ((entry.category_min is not None and category.distinct < entry.category_min) or
                     (entry.category_max is not None and entry.category_max != 50 and category.distinct > entry.category_max)):
        return RuleResult("H5", 0, f"{category.distinct} categories fall outside this chart's limits.", "Use a sorted bar", True)


def h6_colors(entry, shape, binding, context):
    group = binding.get("group")
    if group and entry.group_max is not None and group.distinct > entry.group_max:
        return RuleResult("H6", 0, f"{group.distinct} groups exceed the limit of {entry.group_max}.", "Keep the top groups, or use small multiples later", True)


def h7_points(entry, shape, binding, context):
    time = binding.get("time")
    if time and entry.min_points is not None and time.distinct < entry.min_points:
        return RuleResult("H7", 0, f"The time axis needs at least {entry.min_points} points.", "Use a bar", True)


def h8_order(entry, shape, binding, context):
    time = binding.get("time")
    if time and time.kind not in ("time", "ordinal"):
        return RuleResult("H8", 0, "The horizontal axis needs time or ordinal values.", "Use a bar", True)


def h9_raw(entry, shape, binding, context):
    value = binding.get("value")
    if entry.raw_values and ((entry.min_rows is not None and shape.rows < entry.min_rows) or
                             (value is not None and value.aggregate != "none")):
        return RuleResult("H9", 0, f"This chart needs at least {entry.min_rows} rows of unaggregated values.", "Use a bar of the aggregate", True)


def h10_units(entry, shape, binding, context):
    if entry.name == "dual_axes" and "value" in binding and "value2" in binding and binding["value"].unit == binding["value2"].unit:
        return RuleResult("H10", 0, "The two measures have the same unit.", "Use a grouped column", True)


def h11_many(entry, shape, binding, context):
    category = binding.get("category")
    if entry.category_max == 50 and category and category.distinct > 50:
        return RuleResult("H11", 0, f"{category.distinct} categories exceed fifty.", "Keep the top twenty with Other, or a table", True)


def h12_empty(entry, shape, binding, context):
    if shape.rows == 0:
        return RuleResult("H12", 0, "The result is empty.", "Ask, do not draw", True)


def s1_intent(entry, shape, binding, context):
    if entry.name != "table" and context.intent in entry.purposes:
        return RuleResult("S1", 3, f"This chart serves the {context.intent} intent.", "")


def s2_suggested(entry, shape, binding, context):
    if context.suggested and CATALOGUE.find(context.suggested) == entry:
        return RuleResult("S2", 3, "This chart matches the suggested chart.", "")


def s3_caution(entry, shape, binding, context):
    if entry.rating == "caution":
        return RuleResult("S3", -1, "The catalogue rates this chart use with caution.", "")


def s4_count(entry, shape, binding, context):
    category = binding.get("category")
    if entry.name in BARS | COLUMNS and category:
        count = category.distinct
        score = 1 if count <= 12 else 0 if count <= 20 else -2
        return RuleResult("S4", score, f"{count} categories {'fit' if count <= 20 else 'crowd'} a {entry.name}.",
                          "sort and keep the top N with Other" if count > 20 else "")


def s5_long_labels(entry, shape, binding, context):
    category = binding.get("category")
    if category and category.longest_label > 15:
        if entry.name in BARS:
            return RuleResult("S5", 1, "Long category labels read well on horizontal bars.", "")
        if entry.name in COLUMNS:
            return RuleResult("S5", -2, "Long category labels crowd vertical columns.", "use a horizontal bar")


def s6_balance(entry, shape, binding, context):
    value = binding.get("value")
    if entry.name in ("pie", "donut") and value and value.minimum is not None and value.maximum is not None and value.minimum >= 0.9 * value.maximum:
        return RuleResult("S6", -2, "Slices within ten percent of the largest are hard to compare.", "use a sorted bar")


def s7_time_reads(entry, shape, binding, context):
    axis = binding.get("time") or binding.get("category")
    if axis and axis.kind == "time":
        if entry.name in LINES | {"area", "stacked_area"}:
            return RuleResult("S7", 2, "A line or area makes time easy to read.", "")
        if entry.name in BARS:
            return RuleResult("S7", -2, "Time is harder to read on horizontal bars.", "")


def s8_composition(entry, shape, binding, context):
    if (entry.name in STACKED and context.intent == "composition") or (entry.name in {"grouped_column", "grouped_bar"} and context.intent == "compare"):
        return RuleResult("S8", 1, "The series arrangement supports the requested comparison.", "")


def s9_unbound(entry, shape, binding, context):
    if entry.name == "table":
        return None
    bound = {c.name for c in binding.values()}
    sources = {c.source for c in binding.values() if c.kind in ("category", "ordinal", "geography") and c.source is not None}
    unbound = [c.name for c in shape.measures if c.name not in bound]
    unbound += [c.name for c in shape.labels if c.name not in bound and (c.source is None or c.source not in sources)]
    return RuleResult("S9", -len(unbound),
                      f"Unbound columns: {', '.join(unbound)}." if unbound else "Every measure and independent label is bound.", "")


def s10_few_points(entry, shape, binding, context):
    if entry.name == "scatter" and shape.rows < 10:
        return RuleResult("S10", -2, "Fewer than ten points give little evidence of a relationship.", "")


def s11_words(entry, shape, binding, context):
    if entry.name == "word_cloud" and "category" in binding and binding["category"].distinct < 20:
        return RuleResult("S11", -3, "Fewer than twenty categories give a sparse word cloud.", "")


def s12_fallback(entry, shape, binding, context):
    if entry.name == "table":
        return RuleResult("S12", 0, "A table can show every result column.", "")


def s13_one_number(entry, shape, binding, context):
    if shape.rows == 1 and len(shape.measures) == 1:
        return RuleResult("S13", 2 if entry.name == "table" else -3, "One number is best read directly.", "")


def s14_few_parts(entry, shape, binding, context):
    category = binding.get("category")
    if entry.name == "treemap" and category and category.distinct <= 7:
        return RuleResult("S14", -2, "few parts read better as a pie or a bar", "use a pie, a donut, or a bar")


HARD_RULES = [h1_shape, h2_time_kept, h3_whole, h4_sign, h5_slices, h6_colors,
              h7_points, h8_order, h9_raw, h10_units, h11_many, h12_empty]
SOFT_RULES = [s1_intent, s2_suggested, s3_caution, s4_count, s5_long_labels, s6_balance,
              s7_time_reads, s8_composition, s9_unbound, s10_few_points, s11_words,
              s12_fallback, s13_one_number, s14_few_parts]


_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")
# GPT-Vis SSR dist/cjs/theme.js and Task 5's emphasis default.
ACCENT = "#1783FF"
THEME_BACKGROUNDS = {"default": "#FFFFFF", "academy": "#FFFFFF", "dark": "#000000"}


def _luminance(color):
    digits = color[1:]
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    channels = [int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def _contrast(color, background):
    first, second = sorted((_luminance(color), _luminance(background)))
    return (second + 0.05) / (first + 0.05)


def check_rules(
    entry: CatalogueEntry, spec: Spec, shape: ResultShape, binding: dict[str, ColumnShape],
) -> list[Violation]:
    """Collect C4–C16 errors; syntax owns C17 and resolve owns its warning."""
    violations = []

    def fail(rule, message, fix):
        violations.append(Violation(rule=rule, message=message, fix=fix))

    axis = binding.get("time") or binding.get("category")
    ordered = axis is not None and axis.kind in ("time", "ordinal")
    sort = spec.sort or ("none" if ordered else "value desc")
    value = binding.get("value")
    if ordered and sort != "none":
        fail("C4", "Sort must be none on a time or ordinal axis.", "Remove the sort")
    if spec.limit is not None and (sort not in ("value asc", "value desc") or not _additive(value)):
        fail("C5", "A limit needs a value sort and an additive value for Other.", "Sort by value, or drop the limit")

    category = binding.get("category")
    if spec.palette and (any(not _HEX.fullmatch(c) for c in spec.palette) or
                         (category is not None and len(spec.palette) < category.distinct)):
        fail("C6", "Palette entries must be hex colors, with a color for every category.", "Add colors or drop the palette")
    background = spec.background_color or THEME_BACKGROUNDS[spec.theme]
    colors = [c for c in spec.palette if _HEX.fullmatch(c)]
    if spec.emphasis:
        colors.append(ACCENT)
    if not _HEX.fullmatch(background):
        fail("C7", "The background must be a hex color to check contrast.", "Pick a darker or lighter color")
    elif any(_contrast(c, background) < 3 for c in colors):
        fail("C7", "Every palette color and the accent need at least 3 to 1 contrast with the background.", "Pick a darker or lighter color")
    if not spec.title or not spec.title.strip() or not spec.description or not spec.description.strip():
        fail("C8", "A title and a description are required.", "Write them")
    known = shape._label_values.get(category.name, set()) if category else set()
    group = binding.get("group") if "group" in entry.roles else None
    if group is not None:
        known = known | shape._label_values.get(group.name, set())
    if any(label not in known for label in spec.emphasis):
        target = "category or group" if group is not None else "category"
        fail("C9", f"Every emphasised value must exist in the bound {target}.", "Fix the spelling")
    for rule in HARD_RULES:
        result = rule(entry, shape, binding, Context())
        if result is not None:
            fail("C10", f"{result.rule}: {result.explanation}", result.fix)

    y_values = [binding[r] for r in ("value", "value2", "y") if r in binding]
    ranges = [
        ("Y", spec.axis_y_min, spec.axis_y_max, {"line", "multi_line", "scatter", "boxplot", "dual_axes"}, y_values),
        ("X", spec.axis_x_min, spec.axis_x_max, {"scatter"}, [binding["x"]] if "x" in binding else []),
    ]
    for axis_name, lower, upper, allowed, plotted in ranges:
        if lower is None and upper is None:
            continue
        fix = "Widen the range or drop it"
        if entry.name not in allowed:
            fail("C11", f"axis{axis_name}Min and axis{axis_name}Max are allowed only on {', '.join(sorted(allowed))}.", fix)
        if lower is not None and upper is not None and lower >= upper:
            fail("C11", f"The {axis_name} minimum must be below the maximum.", fix)
        if any((lower is not None and c.minimum is not None and c.minimum < lower) or
               (upper is not None and c.maximum is not None and c.maximum > upper) for c in plotted):
            fail("C11", "Every plotted value must be inside the range.", fix)
    if entry.name in LINES and (spec.zero is False or (spec.axis_y_min is not None and spec.axis_y_min > 0)):
        if value is None or value.minimum is None or value.maximum is None or not (value.maximum > 0 and value.minimum > 0.5 * value.maximum):
            fail("C12", "A cropped line needs positive values with the smallest above half the largest.", "Start at zero")
    if spec.percent and (entry.name not in STACKED or not _additive(value) or value.has_negative):
        fail("C13", "Percent needs a stacked chart and a nonnegative additive value.", "Drop it, or use a share the analyst computed")
    if spec.axis_y_scale == "log":
        if entry.name not in LINES | {"scatter"} or not y_values or any(
            not c.is_numeric or c.minimum is None or c.maximum is None or c.minimum <= 0 or c.maximum < 100 * c.minimum
            for c in y_values
        ):
            fail("C14", "Log needs line, multi_line, or scatter with positive values spanning at least a factor of one hundred.", "Use linear")
    if spec.labels == "on" and shape.rows > 50:
        fail("C15", "More than fifty marks crowd the data labels.", "Turn them off, or limit the rows")
    if spec.zero is True and spec.axis_y_min is not None and spec.axis_y_min != 0:
        fail("C16", "zero true contradicts a nonzero axisYMin.", "Drop one")
    return violations
