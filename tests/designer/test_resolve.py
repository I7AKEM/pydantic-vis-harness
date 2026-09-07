"""Resolve result cells into renderer options without calling a model."""

from copy import deepcopy

import pytest

from vis_agent.designer.catalogue import CATALOGUE
from vis_agent.designer.models import NumberFormat, Spec
from vis_agent.designer.resolve import ResolveError, resolve
from vis_agent.designer.syntax import parse

from .conftest import (cities, column, gender_share, grouped, monthly, raw_amounts,
                       scatter_points, single_number, table, two_units)


def city_spec(chart="column", **kwargs):
    return Spec(type=chart, bind={"category": "city", "value": "violations"}, **kwargs)


def group_spec(chart="grouped_column", **kwargs):
    return Spec(type=chart, bind={"category": "city", "group": "gender", "value": "n"}, **kwargs)


def line_spec(chart="line", **kwargs):
    return Spec(type=chart, bind={"time": "month", "value": "visits"}, **kwargs)


def test_bind_column_by_name_not_description_order():
    columns, result = cities()
    resolved = resolve(city_spec(), columns[::-1], result)
    assert resolved.config["data"] == [
        {"category": f"City{i}", "value": (5 - i) * 10} for i in range(5)
    ]
    assert resolved.config["type"] == "column"
    assert (resolved.width, resolved.height) == (800, 450)
    assert (resolved.config["width"], resolved.config["height"]) == (800, 450)
    assert (resolved.drawn_rows, resolved.folded_rows, resolved.dropped_rows) == (5, 0, 0)


@pytest.mark.parametrize("chart,field", [("treemap", "name"), ("radar", "name"), ("word_cloud", "text")])
def test_catalogue_field_renaming_after_sort_and_fold(chart, field):
    resolved = resolve(city_spec(chart, limit=2), *cities())
    assert resolved.config["type"] == CATALOGUE.get(chart).draw.type
    assert resolved.config["data"] == [
        {field: "City0", "value": 50}, {field: "City1", "value": 40}, {field: "Other", "value": 60},
    ]


@pytest.mark.parametrize("chart,flag", [("grouped_column", "group"), ("grouped_bar", "group"),
                                       ("stacked_column", "stack"), ("stacked_bar", "stack")])
def test_grouped_and_stacked_catalogue_options(chart, flag):
    resolved = resolve(group_spec(chart), *grouped())
    assert resolved.config[flag] is True
    assert resolved.config["data"][0] == {"category": "City4", "group": "F", "value": 14}


@pytest.mark.parametrize("bin_number,labels,count", [
    (None, ["1–6.9", "6.9–12.8", "12.8–18.7", "18.7–24.6", "24.6–30.5",
            "30.5–36.4", "36.4–42.3", "42.3–48.2", "48.2–54.1", "54.1–60"], 6),
    (4, ["1–15.75", "15.75–30.5", "30.5–45.25", "45.25–60"], 15),
])
@pytest.mark.parametrize("direction", ["ltr", "rtl"])
def test_histogram_resolves_ascending_equal_width_bins(bin_number, labels, count, direction):
    spec = Spec(type="histogram", bind={"value": "amount"}, bin_number=bin_number,
                direction=direction, sort="value desc", labels="on")
    columns, result = raw_amounts()
    result.rows = result.rows[::2][::-1] + result.rows[1::2]
    resolved = resolve(spec, columns, result)
    assert resolved.config["type"] == "column"
    assert resolved.config["data"] == [{"category": label, "value": count} for label in labels]
    assert "binNumber" not in resolved.config
    assert "x" not in resolved.overrides.get("scale", {})
    assert resolved.overrides["labels"] == [{"text": "value"}]
    assert (resolved.drawn_rows, resolved.folded_rows, resolved.dropped_rows) == (60, 0, 0)


@pytest.mark.parametrize("digits", ["western", "arabic"])
def test_histogram_keeps_empty_bins_and_counts_boundaries_once(digits):
    columns, _ = raw_amounts()
    result = table(columns, [[v] for v in [1100, 300, 1000, 100] * 15] + [[None]])
    spec = Spec(type="histogram", bind={"value": "amount"}, digits=digits, format="0k SAR")
    resolved = resolve(spec, columns, result)
    labels = ["100–200", "200–300", "300–400", "400–500", "500–600",
              "600–700", "700–800", "800–900", "900–1,000", "1,000–1,100"]
    if digits == "arabic":
        labels = [label.translate(str.maketrans("0123456789,", "٠١٢٣٤٥٦٧٨٩٬")) for label in labels]
    assert resolved.config["data"] == [
        {"category": label, "value": count}
        for label, count in zip(labels, [15, 0, 15, 0, 0, 0, 0, 0, 0, 30])
    ]
    assert (resolved.drawn_rows, resolved.dropped_rows) == (60, 1)
    assert resolved.number.unit is None


def test_histogram_bin_labels_match_shared_default_rounding():
    columns, _ = raw_amounts()
    result = table(columns, [[-1], [0]] * 30)
    spec = Spec(type="histogram", bind={"value": "amount"}, bin_number=8)
    resolved = resolve(spec, columns, result)
    assert [row["category"] for row in resolved.config["data"]] == [
        "-1–-0.88", "-0.88–-0.75", "-0.75–-0.63", "-0.63–-0.5",
        "-0.5–-0.38", "-0.38–-0.25", "-0.25–-0.13", "-0.13–0",
    ]
    assert [row["value"] for row in resolved.config["data"]] == [30, 0, 0, 0, 0, 0, 0, 30]


@pytest.mark.parametrize("digits", ["western", "arabic"])
def test_histogram_small_range_keeps_ten_distinct_labels(digits):
    columns, _ = raw_amounts()
    result = table(columns, [[i / 100000] for i in range(30)])
    spec = Spec(type="histogram", bind={"value": "amount"}, digits=digits)
    resolved = resolve(spec, columns, result)
    labels = [row["category"] for row in resolved.config["data"]]
    assert len(labels) == len(set(labels)) == 10
    expected = ["0–0.000029", "0.000261–0.00029"]
    if digits == "arabic":
        expected = [label.translate(str.maketrans("0123456789.", "٠١٢٣٤٥٦٧٨٩٫")) for label in expected]
    assert [labels[0], labels[-1]] == expected
    assert [row["value"] for row in resolved.config["data"]] == [3] * 10
    assert resolved.drawn_rows == 30


def test_histogram_half_unit_width_trims_trailing_zeros():
    columns, _ = raw_amounts()
    result = table(columns, [[1], [2]])
    spec = Spec(type="histogram", bind={"value": "amount"}, bin_number=2)
    assert resolve(spec, columns, result).config["data"] == [
        {"category": "1–1.5", "value": 1}, {"category": "1.5–2", "value": 1},
    ]


def test_histogram_rejects_boundaries_that_precision_cannot_distinguish():
    columns, _ = raw_amounts()
    result = table(columns, [[1], [1.0000000000000002]])
    spec = Spec(type="histogram", bind={"value": "amount"})
    with pytest.raises(ResolveError, match="reduce binNumber"):
        resolve(spec, columns, result)


def test_histogram_constant_values_have_one_degenerate_bin():
    columns, _ = raw_amounts()
    result = table(columns, [[-2.5]] * 30)
    resolved = resolve(Spec(type="histogram", bind={"value": "amount"}), columns, result)
    assert resolved.config["data"] == [{"category": "-2.5–-2.5", "value": 30}]


@pytest.mark.parametrize("rows", [[], [[None]] * 30])
def test_histogram_without_values_has_no_bins(rows):
    columns, _ = raw_amounts()
    resolved = resolve(Spec(type="histogram", bind={"value": "amount"}), columns, table(columns, rows))
    assert resolved.config["data"] == []
    assert (resolved.drawn_rows, resolved.dropped_rows) == (0, len(rows))


@pytest.mark.parametrize("bin_number", [0, -1])
def test_histogram_rejects_nonpositive_bin_number(bin_number):
    spec = Spec(type="histogram", bind={"value": "amount"}, bin_number=bin_number)
    with pytest.raises(ResolveError, match="binNumber must be positive"):
        resolve(spec, *raw_amounts())


def test_dual_axes_series_and_categories_remain_aligned_after_null_drop():
    columns, result = two_units()
    result.rows[1][2] = None
    spec = Spec(type="dual_axes", bind={"category": "month", "value": "visits", "value2": "revenue"})
    resolved = resolve(spec, columns, result)
    rows = [row for row in result.rows if row[2] is not None]
    assert resolved.config["type"] == "dual-axes"
    assert resolved.config["categories"] == [row[0] for row in rows]
    assert resolved.config["series"] == [
        {"type": "column", "data": [row[1] for row in rows], "axisYTitle": "visits"},
        {"type": "line", "data": [row[2] for row in rows], "axisYTitle": "revenue"},
    ]
    assert (resolved.drawn_rows, resolved.dropped_rows) == (11, 1)


@pytest.mark.parametrize("builder", [single_number, gender_share])
def test_table_preserves_all_columns_cells_and_order(builder):
    columns, result = builder()
    result.rows[0][-1] = None
    resolved = resolve(Spec(type="table", sort="value desc", limit=1, percent=True), columns, result)
    assert resolved.config == {"type": "spreadsheet", "columns": result.columns,
                               "data": [dict(zip(result.columns, row)) for row in result.rows],
                               "width": 800, "height": 450}
    assert (resolved.drawn_rows, resolved.folded_rows, resolved.dropped_rows) == (len(result.rows), 0, 0)


@pytest.mark.parametrize("cell", ["12", "text", True, False])
def test_measure_rejects_text_and_bool_without_coercion(cell):
    columns, result = cities()
    result.rows[1][1] = cell
    with pytest.raises(ResolveError, match="column 'violations'.*row 1.*numeric"):
        resolve(city_spec(), columns, result)


@pytest.mark.parametrize("role,index", [("x", 0), ("y", 1)])
def test_scatter_validates_and_drops_either_measure(role, index):
    columns, result = scatter_points(3)
    spec = Spec(type="scatter", bind={"x": "age", "y": "amount"})
    result.rows[0][index] = "bad"
    with pytest.raises(ResolveError, match=spec.bind[role]):
        resolve(spec, columns, result)
    result.rows[0][index] = None
    resolved = resolve(spec, columns, result)
    assert resolved.config["data"] == [{"x": 2, "y": 20}, {"x": 3, "y": 30}]
    assert resolved.dropped_rows == 1


@pytest.mark.parametrize("language,unknown", [("en", "Unknown"), ("ar", "غير معروف")])
def test_null_values_drop_rows_and_null_labels_use_language(language, unknown):
    columns, result = cities(3)
    result.rows[0][1] = None
    result.rows[1][0] = None
    resolved = resolve(city_spec(language=language), columns, result)
    assert resolved.config["data"] == [{"category": unknown, "value": 20}, {"category": "City2", "value": 10}]
    assert (resolved.drawn_rows, resolved.dropped_rows) == (2, 1)
    assert any("1" in c.message and "drop" in c.message.lower() for c in resolved.compromises)


def test_custom_unknown_applies_to_group_and_category():
    columns, result = grouped(1)
    result.rows[0][:2] = [None, None]
    resolved = resolve(group_spec(unknown="Missing"), columns, result)
    assert resolved.config["data"][0] == {"category": "Missing", "group": "Missing", "value": 10}


@pytest.mark.parametrize("sort,expected", [(None, ["A", "C", "B"]), ("value asc", ["B", "C", "A"]),
                                          ("category asc", ["A", "B", "C"]),
                                          ("category desc", ["C", "B", "A"]), ("none", ["B", "A", "C"])])
def test_sort_orders(sort, expected):
    columns, _ = cities()
    result = table(columns, [["B", 10], ["A", 30], ["C", 20]])
    assert [r["category"] for r in resolve(city_spec(sort=sort), columns, result).config["data"]] == expected


def test_category_sort_uses_text_for_numeric_labels():
    columns, _ = cities()
    result = table(columns, [[2, 20], [10, 10]])
    assert [r["category"] for r in resolve(city_spec(sort="category asc"), columns, result).config["data"]] == ["10", "2"]


@pytest.mark.parametrize("kind", ["time", "ordinal"])
def test_ordered_category_axis_preserves_input_order(kind):
    columns, result = cities()
    columns[0] = column("city", kind)
    result.rows.reverse()
    resolved = resolve(city_spec(), columns, result)
    assert [r["category"] for r in resolved.config["data"]] == [r[0] for r in result.rows]


def test_group_sort_uses_category_total_and_preserves_group_order():
    columns, _ = grouped()
    result = table(columns, [["A", "F", 1], ["B", "F", 40], ["A", "M", 60], ["B", "M", 10]])
    resolved = resolve(group_spec(), columns, result)
    assert [(r["category"], r["group"]) for r in resolved.config["data"]] == [
        ("A", "F"), ("A", "M"), ("B", "F"), ("B", "M"),
    ]


@pytest.mark.parametrize("language,other", [("en", "Other"), ("ar", "أخرى")])
def test_limit_folds_after_sort(language, other):
    resolved = resolve(city_spec(limit=5, language=language), *cities(8))
    assert len(resolved.config["data"]) == 6
    assert resolved.config["data"][-1] == {"category": other, "value": 60}
    assert (resolved.drawn_rows, resolved.folded_rows, resolved.dropped_rows) == (6, 3, 0)


def test_group_limit_counts_categories_and_sums_other_per_group():
    resolved = resolve(group_spec(limit=5, other="Rest"), *grouped(8))
    assert resolved.config["data"][-2:] == [
        {"category": "Rest", "group": "F", "value": 33},
        {"category": "Rest", "group": "M", "value": 33},
    ]
    assert (resolved.drawn_rows, resolved.folded_rows) == (12, 6)


def test_limit_with_no_tail_adds_no_other():
    resolved = resolve(city_spec(limit=5), *cities(5))
    assert resolved.drawn_rows == 5 and resolved.folded_rows == 0


def test_non_additive_limit_is_rejected():
    columns, result = cities()
    columns[1] = column("violations", "measure", aggregate="avg")
    with pytest.raises(ResolveError, match="additive"):
        resolve(city_spec(limit=2), columns, result)


@pytest.mark.parametrize("chart", ["stacked_column", "stacked_bar", "stacked_area"])
def test_percent_stacks_sum_to_100_and_default_to_percent_unit(chart):
    columns, result = grouped()
    spec = group_spec(chart, percent=True)
    axis = "category"
    if chart == "stacked_area":
        columns[0] = column("city", "time")
        spec.bind["time"] = spec.bind.pop("category")
        axis = "time"
    resolved = resolve(spec, columns, result)
    data = resolved.config["data"]
    for label in {r[axis] for r in data}:
        assert sum(r["value"] for r in data if r[axis] == label) == pytest.approx(100, abs=1e-9)
    assert resolved.config["axisYTitle"] == "%"
    assert resolved.number.unit == "%"
    assert not any(c.key == "format" for c in resolved.compromises)


def test_percent_runs_after_folding_and_honours_explicit_title_and_format():
    columns, _ = grouped()
    result = table(columns, [["A", "F", 50], ["A", "M", 50], ["B", "F", 9],
                             ["B", "M", 1], ["C", "F", 0], ["C", "M", 20]])
    resolved = resolve(group_spec("stacked_column", limit=1, percent=True,
                                  axis_y_title="Share", format="0.0 pct"), columns, result)
    assert resolved.config["data"][-2:] == [
        {"category": "Other", "group": "F", "value": 30},
        {"category": "Other", "group": "M", "value": 70},
    ]
    assert resolved.config["axisYTitle"] == "Share"
    assert resolved.number.unit == "pct"


def test_zero_percent_total_is_disclosed_without_dividing_by_zero():
    columns, result = grouped(1)
    for row in result.rows:
        row[2] = 0
    resolved = resolve(group_spec("stacked_column", percent=True), columns, result)
    assert all(r["value"] == 0 for r in resolved.config["data"])
    assert any(c.key == "percent" and "zero" in c.message for c in resolved.compromises)


@pytest.mark.parametrize("theme,muted", [("default", "#C9CDD4"), ("dark", "#4E5969")])
def test_emphasis_colors_follow_sorted_categories(theme, muted):
    columns, _ = cities()
    result = table(columns, [["Jeddah", 20], ["Riyadh", 1240], ["Dammam", 10]])
    resolved = resolve(city_spec(emphasis=["Jeddah"], theme=theme), columns, result)
    assert resolved.config["style"]["palette"] == [muted, "#1783FF", muted]


def test_group_emphasis_colors_groups():
    resolved = resolve(group_spec(emphasis=["M"]), *grouped())
    assert resolved.config["style"]["palette"] == ["#C9CDD4", "#1783FF"]


def test_explicit_palette_wins_and_style_background_passes_through():
    spec = parse("vis column\nbind\n  category city\n  value violations\nemphasis\n  - City0\n"
                 "style\n  backgroundColor #000000\n  palette\n    - #FFFFFF\n    - #1783FF\n")
    resolved = resolve(spec, *cities(2))
    assert resolved.config["style"] == {"backgroundColor": "#000000", "palette": spec.palette[:1]}


@pytest.mark.parametrize("chart", ["column", "grouped_column", "stacked_column"])
def test_arabic_columns_reverse_final_category_domain_and_align_title(chart):
    spec, data = (group_spec(chart, language="ar", limit=2), grouped(3)) if "_" in chart else (
        city_spec(chart, language="ar", limit=2), cities(3))
    resolved = resolve(spec, *data)
    categories = list(dict.fromkeys(r["category"] for r in resolved.config["data"]))
    assert resolved.overrides["scale"]["x"]["domain"] == categories[::-1]
    assert resolved.overrides["title"]["align"] == "right"
    assert any(c.key == "direction" and "legend" in c.message for c in resolved.compromises)


@pytest.mark.parametrize("chart", ["bar", "grouped_bar", "stacked_bar"])
def test_arabic_bars_keep_value_desc_order_and_align_title(chart):
    if chart == "bar":
        spec = city_spec(chart, language="ar", sort="value desc")
        columns, result = cities(3)
        result.rows.reverse()
        expected = [{"category": f"City{i}", "value": (3 - i) * 10} for i in range(3)]
    else:
        spec = group_spec(chart, language="ar", sort="value desc")
        columns, result = grouped(3)
        expected = [{"category": f"City{i}", "group": group, "value": 10 + i}
                    for i in [2, 1, 0] for group in ["F", "M"]]
    resolved = resolve(spec, columns, result)
    assert "domain" not in resolved.overrides.get("scale", {}).get("x", {})
    assert resolved.config["data"] == expected
    assert resolved.overrides["title"]["align"] == "right"
    assert any(c.key == "direction" and "legend" in c.message for c in resolved.compromises)


def test_arabic_explicit_ltr_overrides_language_default():
    resolved = resolve(city_spec(language="ar", direction="ltr"), *cities())
    assert "domain" not in resolved.overrides.get("scale", {}).get("x", {})
    assert resolved.overrides.get("title", {}).get("align") != "right"


@pytest.mark.parametrize("chart", ["line", "column"])
def test_time_axes_never_reverse_even_on_column(chart):
    spec = line_spec(language="ar") if chart == "line" else Spec(
        type="column", bind={"category": "month", "value": "visits"}, language="ar")
    resolved = resolve(spec, *monthly())
    assert "domain" not in resolved.overrides.get("scale", {}).get("x", {})
    assert resolved.overrides["title"]["align"] == "right"


def test_number_defaults_come_from_value_unit_and_language_does_not_change_digits():
    columns, result = cities()
    columns[1].unit = "ريال"
    assert resolve(city_spec(language="ar"), columns, result).number == NumberFormat(unit="ريال")


@pytest.mark.parametrize("pattern", [None, "0,0 SAR"])
def test_histogram_count_format_has_no_unit(pattern):
    spec = Spec(type="histogram", bind={"value": "amount"}, format=pattern)
    resolved = resolve(spec, *raw_amounts())
    assert resolved.number == NumberFormat(thousands=True, unit=None)
    assert resolved.number2 is None


@pytest.mark.parametrize("pattern,digits", [(None, "western"), ("0,0.0", "arabic")])
def test_dual_axes_have_separate_units_and_measure_names(pattern, digits):
    spec = Spec(type="dual_axes", bind={"category": "month", "value": "visits", "value2": "revenue"},
                format=pattern, digits=digits)
    resolved = resolve(spec, *two_units())
    decimals = 1 if pattern else None
    assert resolved.number == NumberFormat(unit="visits", decimals=decimals, digits=digits)
    assert resolved.number2 == NumberFormat(unit="SAR", decimals=decimals, digits=digits)
    assert [series["axisYTitle"] for series in resolved.config["series"]] == ["visits", "revenue"]
    assert resolved.config["axisXTitle"] == "month"
    assert resolved.config["axisYTitle"] == "visits"


def test_dual_axes_second_unit_does_not_inherit_first_format_unit():
    columns, result = two_units()
    columns[2].unit = None
    spec = Spec(type="dual_axes", bind={"category": "month", "value": "visits", "value2": "revenue"},
                format="0,0.0 people")
    resolved = resolve(spec, columns, result)
    assert resolved.number.unit == "people"
    assert resolved.number2 == NumberFormat(decimals=1, unit=None)


@pytest.mark.parametrize("spec,builder", [(city_spec(), cities), (Spec(type="table"), single_number)])
def test_other_entries_have_no_second_number_description(spec, builder):
    assert resolve(spec, *builder()).number2 is None


@pytest.mark.parametrize("spec,builder,x_title,y_title", [
    (city_spec(), cities, "city", "violations"),
    (line_spec(), monthly, "month", "visits"),
    (Spec(type="scatter", bind={"x": "age", "y": "amount"}), scatter_points, "age", "amount"),
])
@pytest.mark.parametrize("explicit", [False, True])
def test_axis_titles_use_bound_names_unless_explicit(spec, builder, x_title, y_title, explicit):
    if explicit:
        spec = spec.model_copy(update={"axis_x_title": "Horizontal", "axis_y_title": "Vertical"})
    config = resolve(spec, *builder()).config
    assert config["axisXTitle"] == ("Horizontal" if explicit else x_title)
    assert config["axisYTitle"] == ("Vertical" if explicit else y_title)


@pytest.mark.parametrize("chart", ["pie", "donut", "treemap", "radar", "word_cloud", "table"])
@pytest.mark.parametrize("explicit", [False, True])
def test_entries_without_axes_have_no_axis_titles(chart, explicit):
    spec = city_spec(chart, **({"axis_x_title": "Unused", "axis_y_title": "Unused"} if explicit else {}))
    config = resolve(spec, *cities()).config
    assert "axisXTitle" not in config and "axisYTitle" not in config


def test_scatter_number_unit_comes_from_y():
    columns, result = scatter_points()
    columns[0].unit, columns[1].unit = "years", "SAR"
    assert resolve(Spec(type="scatter", bind={"x": "age", "y": "amount"}), columns, result).number.unit == "SAR"


def test_number_format_percent_and_digits_travel_with_compromise():
    resolved = resolve(city_spec(format="0.0%", digits="arabic"), *cities())
    assert resolved.number == NumberFormat(thousands=False, decimals=1, unit="%", digits="arabic")
    assert any(c.key == "format" for c in resolved.compromises)
    assert resolved.config["data"][0]["value"] == 50


def test_share_percent_format_has_no_non_share_compromise():
    spec = Spec(type="donut", bind={"category": "label", "value": "share"}, format="0.0%")
    resolved = resolve(spec, *gender_share())
    assert not any(c.key == "format" for c in resolved.compromises)
    assert resolved.config["innerRadius"] == 0.6


def test_format_without_unit_inherits_column_unit():
    columns, result = cities()
    columns[1].unit = "SAR"
    assert resolve(city_spec(format="0k"), columns, result).number == NumberFormat(
        thousands=False, compact=True, unit="SAR")


def test_inherited_percent_unit_does_not_claim_the_format_added_a_percent_sign():
    columns, result = cities()
    columns[1].unit = "%"
    resolved = resolve(city_spec(format="0.0"), columns, result)
    assert resolved.number.unit == "%"
    assert not any(c.key == "format" for c in resolved.compromises)


def test_axis_ranges_scale_switches_and_subtitle_merge():
    spec = line_spec(axis_y_min=80, axis_y_max=300, subtitle="Monthly", labels="off", legend="off")
    resolved = resolve(spec, *monthly())
    assert resolved.overrides == {"scale": {"y": {"domainMin": 80, "domainMax": 300, "nice": False}},
                                  "title": {"subtitle": "Monthly"}, "labels": [], "legend": False}
    assert resolve(line_spec(axis_y_scale="log"), *monthly()).overrides["scale"]["y"] == {"type": "log"}


def test_scatter_ranges_keep_both_axes():
    spec = Spec(type="scatter", bind={"x": "age", "y": "amount"}, axis_x_min=0, axis_x_max=50,
                axis_y_min=0, axis_y_max=500)
    scale = resolve(spec, *scatter_points()).overrides["scale"]
    assert scale["x"] == {"domainMin": 0, "domainMax": 50}
    assert scale["y"] == {"domainMin": 0, "domainMax": 500, "nice": False}


@pytest.mark.parametrize("zero,expected", [(None, True), (True, True), (False, False)])
def test_line_zero_default_and_override(zero, expected):
    assert resolve(line_spec(zero=zero), *monthly()).config["style"]["startAtZero"] is expected


@pytest.mark.parametrize("chart", ["line", "multi_line", "area", "stacked_area"])
@pytest.mark.parametrize("points,width", [(12, 800), (13, 1200), (24, 1200)])
def test_width_uses_distinct_plotted_time_points(chart, points, width):
    columns, result = monthly(points)
    spec = line_spec(chart)
    if chart in {"multi_line", "stacked_area"}:
        columns.append(column("group", "category"))
        result = table(columns, [row + [g] for row in result.rows for g in ["F", "M"]])
        spec.bind["group"] = "group"
    resolved = resolve(spec, columns, result)
    assert resolved.width == width
    assert resolved.config["style"]["startAtZero"] is True


def test_explicit_size_and_base_options():
    spec = city_spec("donut", width=900, height=500, inner_radius=0.4, title="Cities", theme="academy",
                     axis_x_title="City", axis_y_title="Count")
    config = resolve(spec, *cities()).config
    assert {key: config[key] for key in ("width", "height", "innerRadius", "title", "theme")} == {
        "width": 900, "height": 500, "innerRadius": 0.4, "title": "Cities", "theme": "academy",
    }
    assert "axisXTitle" not in config and "axisYTitle" not in config
    assert resolve(line_spec(width=900), *monthly(24)).width == 900


def test_resolution_does_not_mutate_inputs_or_catalogue():
    columns, result = grouped(8)
    spec = group_spec("stacked_column", limit=5, percent=True, palette=["#FFFFFF", "#1783FF"])
    before = deepcopy((spec, columns, result, CATALOGUE))
    resolved = resolve(spec, columns, result)
    resolved.config["style"]["palette"].append("#000000")
    resolved.config["data"][0]["value"] = -1
    assert (spec, columns, result, CATALOGUE) == before


@pytest.mark.parametrize("language,count", [("en", "Count"), ("ar", "العدد")])
@pytest.mark.parametrize("explicit", [False, True])
def test_histogram_axis_titles(language, count, explicit):
    spec = Spec(type="histogram", bind={"value": "amount"}, language=language,
                axis_x_title="Amount" if explicit else None,
                axis_y_title="Frequency" if explicit else None)
    config = resolve(spec, *raw_amounts()).config
    assert config["axisXTitle"] == ("Amount" if explicit else "amount")
    assert config["axisYTitle"] == ("Frequency" if explicit else count)


@pytest.mark.parametrize("chart", ["line", "area"])
def test_switch_on_compromises_for_child_marks_and_single_series(chart):
    resolved = resolve(line_spec(chart, labels="on", legend="on"), *monthly())
    assert {c.key for c in resolved.compromises} == {"labels", "legend"}
    assert any(c.message == "no legend: the chart has one series" for c in resolved.compromises)
    assert "labels" not in resolved.overrides and "legend" not in resolved.overrides


def test_group_palette_passes_through_in_group_order():
    palette = ["#000000", "#123456"]
    resolved = resolve(group_spec(palette=palette), *grouped())
    assert resolved.config["style"]["palette"] == palette
    assert list(dict.fromkeys(row["group"] for row in resolved.config["data"])) == ["F", "M"]


@pytest.mark.parametrize("values,expected", [
    ([2021, 2022], ["2021", "2022"]),
    ([2021.0, 2022.5], ["2021", "2022.5"]),
    (["2024-01-01T00:00:00", "2024-02-01T00:00:00"], ["2024-01", "2024-02"]),
    (["2020-01-01T00:00:00+03:00", "2021-01-01T00:00:00+03:00"], ["2020", "2021"]),
    (["2024-01-01", "2024-01-02T00:00:00Z"], ["2024-01-01", "2024-01-02"]),
    (["2024-01-01T00:00:00", "2024-01-02 12:30:45+03:00"],
     ["2024-01-01 00:00", "2024-01-02 12:30"]),
    (["2024-01-01T12:00:10", "2024-01-01T12:00:20", "2024-01-01T12:00:30"],
     ["2024-01-01 12:00:10", "2024-01-01 12:00:20", "2024-01-01 12:00:30"]),
    (["2024-01-01T12:00:10.000001", "2024-01-01T12:00:10.000002"],
     ["2024-01-01 12:00:10.000001", "2024-01-01 12:00:10.000002"]),
    (["2024-01-01T12:00:10", "2024-01-01T12:00:10", "2024-01-01T12:01:20"],
     ["2024-01-01 12:00", "2024-01-01 12:00", "2024-01-01 12:01"]),
    (["2024-01-01T12:00:00+03:00", "2024-01-01T12:00:00+04:00"],
     ["2024-01-01T12:00:00+03:00", "2024-01-01T12:00:00+04:00"]),
    (["2024-01-01T00:00:00", "2024-02-30T00:00:00"],
     ["2024-01-01T00:00:00", "2024-02-30T00:00:00"]),
    (["2024-01-01T00:00:00", "Not a date"], ["2024-01-01T00:00:00", "Not a date"]),
])
@pytest.mark.parametrize("chart", ["column", "line", "dual_axes"])
def test_time_labels_are_text_with_consistent_precision(values, expected, chart):
    columns = [column("period", "time"), column("value", "measure"), column("value2", "measure")]
    result = table(columns, [[value, i + 1, 10 * (i + 1)] for i, value in enumerate(values)])
    role = "time" if chart == "line" else "category"
    spec = Spec(type=chart, bind={role: "period", "value": "value"}, language="ar")
    if chart == "dual_axes":
        spec.bind["value2"] = "value2"
    resolved = resolve(spec, columns, result)
    labels = resolved.config["categories"] if chart == "dual_axes" else [r[role] for r in resolved.config["data"]]
    assert labels == expected
    assert len(set(labels)) == len(set(values))
    assert "domain" not in resolved.overrides.get("scale", {}).get("x", {})
    assert [row[0] for row in result.rows] == values


@pytest.mark.parametrize("values", [
    ["1447-02", "1447-03", "1447-04"],
    ["صفر 1447", "ربيع الأول 1447", "ربيع الآخر 1447"],
    ["١٤٤٧-٠٢", "١٤٤٧-٠٣", "١٤٤٧-٠٤"],
    ["1447-02-01", "1447-03-01", "1447-04-01"],
    ["1446", "1447", "1448"],
])
@pytest.mark.parametrize("chart", ["line", "column"])
@pytest.mark.parametrize("direction", ["ltr", "rtl"])
@pytest.mark.parametrize("sort", [None, "none"])
def test_hijri_time_labels_and_analyst_order_are_preserved(values, chart, direction, sort):
    columns = [column("period", "time"), column("value", "measure")]
    result = table(columns, [[label, value] for label, value in zip(values, [20, 10, 30])])
    role = "time" if chart == "line" else "category"
    spec = Spec(type=chart, bind={role: "period", "value": "value"},
                language="ar", direction=direction, sort=sort)
    resolved = resolve(spec, columns, result)
    assert resolved.config["data"] == [
        {role: label, "value": value} for label, value in result.rows
    ]
    assert "domain" not in resolved.overrides.get("scale", {}).get("x", {})
    assert [row[0] for row in result.rows] == values


@pytest.mark.parametrize("value", [
    "1447-03-01", "1599-01-01T00:00:00", "١٤٤٧-٠٣-٠١", "٢٠٢٤-٠٣-٠١",
    "2024-03-01T٠٠:00:00", "ربيع الأول 1447", "March 2024",
])
def test_one_non_gregorian_label_keeps_the_whole_time_column_unchanged(value):
    columns = [column("period", "time"), column("value", "measure")]
    result = table(columns, [["2024-02-01T00:00:00", 20], [value, 10]])
    spec = Spec(type="line", bind={"time": "period", "value": "value"}, sort="none")
    resolved = resolve(spec, columns, result)
    assert resolved.config["data"] == [
        {"time": label, "value": measure} for label, measure in result.rows
    ]


@pytest.mark.parametrize("year", ["1600", "2024"])
def test_gregorian_monthly_series_still_shortens_in_analyst_order(year):
    columns = [column("period", "time"), column("value", "measure")]
    result = table(columns, [[f"{year}-02-01", 20], [f"{year}-03-01", 10]])
    spec = Spec(type="line", bind={"time": "period", "value": "value"},
                sort="none", direction="rtl")
    resolved = resolve(spec, columns, result)
    assert resolved.config["data"] == [
        {"time": f"{year}-02", "value": 20}, {"time": f"{year}-03", "value": 10},
    ]
    assert "domain" not in resolved.overrides.get("scale", {}).get("x", {})


def test_numeric_categories_and_groups_use_text_for_sort_rtl_emphasis_and_other():
    columns, _ = cities()
    result = table(columns, [[2, 20], [10.0, 30], [1.25, 10], ["2.0", 5]])
    resolved = resolve(city_spec(sort="category asc", language="ar", emphasis=["10"]), columns, result)
    assert [r["category"] for r in resolved.config["data"]] == ["1.25", "10", "2", "2.0"]
    assert resolved.overrides["scale"]["x"]["domain"] == ["2.0", "2", "10", "1.25"]
    assert resolved.config["style"]["palette"] == ["#C9CDD4", "#1783FF", "#C9CDD4", "#C9CDD4"]
    folded = resolve(city_spec(limit=1), columns, result)
    assert folded.config["data"] == [{"category": "10", "value": 30}, {"category": "Other", "value": 35}]
    columns, result = grouped(1)
    result.rows[0][1], result.rows[1][1] = 1, 2.0
    resolved = resolve(group_spec(emphasis=["2"]), columns, result)
    assert [r["group"] for r in resolved.config["data"]] == ["1", "2"]
    assert resolved.config["style"]["palette"] == ["#C9CDD4", "#1783FF"]


@pytest.mark.parametrize("meanings,expected", [
    (["Region", "Total", "Share"], ["Region", "Total", "Share"]),
    (["", "  ", "Share"], ["a", "b", "Share"]),
    (["Repeated", "Repeated", "Share"], ["a", "b", "Share"]),
    (["b", "", "Share"], ["a", "b", "Share"]),
    (["b", "Same", "Same"], ["a", "b", "c"]),
])
def test_table_headers_use_meanings_with_collision_safe_fallback(meanings, expected):
    columns = [column(name, "measure") for name in ["a", "b", "c"]]
    for c, meaning in zip(columns, meanings):
        c.meaning = meaning
    result = table(columns, [[1, 2, 3]])
    resolved = resolve(Spec(type="table"), columns[::-1], result)
    assert resolved.config["columns"] == expected
    assert resolved.config["data"] == [dict(zip(expected, [1, 2, 3]))]


@pytest.mark.parametrize("unit,expected", [("count", None), (" COUNTS ", None), ("number", None),
                                         ("N", None), ("عدد", None), ("رقم", None), ("SAR", "SAR")])
def test_inherited_count_units_are_removed_from_charts_and_tables(unit, expected):
    columns, result = gender_share()
    columns[2].unit = unit
    spec = Spec(type="column", bind={"category": "label", "value": "n"})
    assert resolve(spec, columns, result).number.unit == expected
    spec.format = "0.0"
    assert resolve(spec, columns, result).number.unit == expected
    spec.format = "0.0 count"
    assert resolve(spec, columns, result).number.unit == "count"
    resolved = resolve(Spec(type="table", digits="arabic", format="0.0 SAR"), columns, result)
    assert resolved.table_formats["n"] == NumberFormat(unit=expected, digits="arabic").model_dump()
    assert resolved.table_formats["share"]["unit"] == "%"


@pytest.mark.parametrize("chart,builder,bindings", [
    ("column", cities, {"category": "city", "value": "violations"}),
    ("bar", cities, {"category": "city", "value": "violations"}),
    ("line", monthly, {"time": "month", "value": "visits"}),
    ("area", monthly, {"time": "month", "value": "visits"}),
    ("scatter", scatter_points, {"x": "age", "y": "amount"}),
    ("histogram", raw_amounts, {"value": "amount"}),
    ("boxplot", cities, {"category": "city", "value": "violations"}),
])
def test_single_series_palette_uses_first_brand_colour(chart, builder, bindings):
    spec = Spec(type=chart, bind=bindings, palette=["#1F4E79", "#C0504D"])
    assert resolve(spec, *builder()).config["style"]["palette"] == ["#1F4E79"]
    assert spec.palette == ["#1F4E79", "#C0504D"]


@pytest.mark.parametrize("chart", ["pie", "donut", "treemap", "word_cloud", "radar"])
def test_category_colour_palettes_keep_all_colours(chart):
    palette = ["#1F4E79", "#C0504D"]
    assert resolve(city_spec(chart, palette=palette), *cities(2)).config["style"]["palette"] == palette


@pytest.mark.parametrize("chart", ["bar", "grouped_bar", "stacked_bar", "column"])
@pytest.mark.parametrize("explicit", [False, True])
def test_axis_titles_follow_screen_axes(chart, explicit):
    spec, data = (group_spec(chart), grouped()) if "_" in chart else (city_spec(chart), cities())
    if explicit:
        spec.axis_x_title, spec.axis_y_title = "Share (%)", "Region"
    config = resolve(spec, *data).config
    expected = ("city", spec.bind["value"])
    if explicit:
        expected = ("Share (%)", "Region") if chart == "column" else ("Region", "Share (%)")
    assert (config["axisXTitle"], config["axisYTitle"]) == expected


@pytest.mark.parametrize("x,y,expected", [(None, None, "%"), ("Share", None, "Share"), (None, "Region", "%")])
def test_percent_bar_default_title_is_on_horizontal_value_axis(x, y, expected):
    config = resolve(group_spec("stacked_bar", percent=True, axis_x_title=x, axis_y_title=y), *grouped()).config
    assert config["axisXTitle"] == (y if y is not None else "city")
    assert config["axisYTitle"] == expected


@pytest.mark.parametrize("chart,builder,bindings", [
    ("radar", grouped, {"category": "city", "group": "gender", "value": "n"}),
    ("dual_axes", two_units, {"category": "month", "value": "visits", "value2": "revenue"}),
    ("table", cities, {}),
])
def test_labels_on_reports_unsupported_mark_structure(chart, builder, bindings):
    resolved = resolve(Spec(type=chart, bind=bindings, labels="on"), *builder())
    assert any(c.key == "labels" for c in resolved.compromises)
    assert "labels" not in resolved.overrides


@pytest.mark.parametrize("chart, role", [("line", "time"), ("column", "category")])
def test_gregorian_time_is_drawn_in_order_whatever_the_analyst_returned(chart, role):
    columns = [column("period", "time"), column("value", "measure")]
    result = table(columns, [["2026", 5], ["2024", 20], ["2025", 10]])
    spec = Spec(type=chart, bind={role: "period", "value": "value"}, sort="none")
    resolved = resolve(spec, columns, result)
    assert [record[role] for record in resolved.config["data"]] == ["2024", "2025", "2026"]


def test_integer_years_bound_as_time_are_drawn_in_order():
    columns = [column("year", "ordinal"), column("value", "measure")]
    result = table(columns, [[2026, 5], [2025, 10], [2024, 20]])
    spec = Spec(type="line", bind={"time": "year", "value": "value"})
    resolved = resolve(spec, columns, result)
    assert [record["time"] for record in resolved.config["data"]] == ["2024", "2025", "2026"]


@pytest.mark.parametrize("values", [
    ["1447-04", "1447-03", "1447-02"], ["١٤٤٧-٠٤", "١٤٤٧-٠٣"], ["ربيع الآخر 1447", "صفر 1447"],
])
def test_hijri_time_keeps_the_analyst_order(values):
    columns = [column("period", "time"), column("value", "measure")]
    result = table(columns, [[label, 10] for label in values])
    spec = Spec(type="line", bind={"time": "period", "value": "value"})
    resolved = resolve(spec, columns, result)
    assert [record["time"] for record in resolved.config["data"]] == values
