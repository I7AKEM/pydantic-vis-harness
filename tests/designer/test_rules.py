from vis_agent.designer.catalogue import CATALOGUE
from vis_agent.designer.models import Spec
from vis_agent.designer.recommend import default_binding, recommend_charts
from vis_agent.designer.rules import Context, HARD_RULES, SOFT_RULES, check_rules
from vis_agent.designer.shape import describe

from .conftest import (cities, column, gender_code_and_label, gender_share, grouped, monthly,
                       own_share_by_region, raw_amounts, scatter_points, single_number, table,
                       two_same_unit_measures, two_units)


def candidate(data, name, **context):
    return next(c for c in recommend_charts(*data, **context).candidates if c.name == name)


def rejected(data, name, rule):
    assert any(r.name == name and r.rule == rule for r in recommend_charts(*data).rejected)


def score(data, name, rule, **context):
    return sum(s.score for s in candidate(data, name, **context).breakdown if s.rule == rule)


def direct(rule, name, data, binding=None, entry=None, **context):
    shape = describe(*data)
    entry = entry or CATALOGUE.get(name)
    binding = (default_binding(entry, shape) or {}) if binding is None else {r: shape.column(c) for r, c in binding.items()}
    return next((r for fn in HARD_RULES + SOFT_RULES
                 if (r := fn(entry, shape, binding, Context(**context))) is not None and r.rule == rule), None)


def checked(name, data=None, binding=None, **keys):
    shape = describe(*(data if data is not None else cities()))
    entry = CATALOGUE.get(name)
    bound = default_binding(entry, shape) or {}
    if binding is not None:
        bound = {r: shape.column(c) for r, c in binding.items()}
    spec = Spec(type=name, title="Title", description="Description", **keys)
    return check_rules(entry, spec, shape, bound)


def has(violations, rule):
    return [v for v in violations if v.rule == rule]


def test_h1_shape():
    rejected(single_number(), "column", "H1")
    candidate(cities(), "column")
    # Explicit bindings still require the role's allowed kind.
    failure = direct("H1", "column", cities(), binding={"category": "violations", "value": "violations"})
    assert failure and failure.hard


def test_h2_time_kept():
    columns, result = cities()
    columns.append(column("month", "time"))
    result = table(columns, [r + ["2025-01"] for r in result.rows])
    rejected((columns, result), "column", "H2")
    candidate((columns, result), "table")
    candidate(monthly(), "column")


def test_h3_whole():
    columns, result = cities()
    columns[1] = column("violations", "measure", aggregate="avg")
    rejected((columns, result), "pie", "H3")
    candidate(cities(), "pie")
    candidate(gender_share(), "pie")


def test_h4_sign():
    columns, result = cities()
    result.rows[0][1] = -1
    rejected((columns, result), "pie", "H4")
    candidate(cities(), "pie")


def test_h5_slices():
    for name in ("pie", "donut"):
        rejected(cities(7), name, "H5")
        rejected(cities(1), name, "H5")
        candidate(cities(2), name)
        candidate(cities(6), name)
    rejected(cities(19), "word_cloud", "H5")
    candidate(cities(20), "word_cloud")
    rejected(cities(13), "radar", "H5")
    candidate(cities(12), "radar")


def test_h6_colors():
    columns = [column("city", "category"), column("group", "category"), column("n", "measure", aggregate="sum")]
    for groups, fails in [(10, False), (11, True)]:
        data = columns, table(columns, [[f"C{i}", f"G{j}", 1] for i in range(12) for j in range(groups)])
        if fails:
            rejected(data, "grouped_column", "H6")
        else:
            candidate(data, "grouped_column")


def test_h7_points():
    for name in ("line", "area"):
        rejected(monthly(2), name, "H7")
        candidate(monthly(3), name)
    for points in (2, 3):
        columns, result = monthly(points)
        columns.append(column("group", "category"))
        data = columns, table(columns, [r + ["A"] for r in result.rows])
        if points == 2:
            rejected(data, "multi_line", "H7")
        else:
            candidate(data, "multi_line")
    rejected(monthly(2), "multi_line", "H1")  # No required group in monthly().


def test_h8_order():
    assert direct("H8", "line", cities(), binding={"time": "city", "value": "violations"}).hard
    assert direct("H8", "line", monthly()) is None
    rejected(cities(), "line", "H1")


def test_h9_raw():
    rejected(raw_amounts(29), "histogram", "H9")
    candidate(raw_amounts(30), "histogram")
    rejected(cities(), "histogram", "H9")
    columns, result = raw_amounts(30)
    columns.insert(0, column("group", "category"))
    data = columns, table(columns, [["A", *r] for r in result.rows])
    candidate(data, "boxplot")


def test_h10_units():
    columns, result = two_units()
    candidate((columns, result), "dual_axes")
    columns[1].unit = "SAR"
    rejected((columns, result), "dual_axes", "H10")
    columns[1].unit = columns[2].unit = None
    rejected((columns, result), "dual_axes", "H10")
    failure = direct("H10", "dual_axes", two_same_unit_measures())
    assert "fold" in failure.fix
    assert "grouped column" not in failure.fix


def test_h11_many():
    for name in ("column", "bar"):
        rejected(cities(51), name, "H11")
        candidate(cities(50), name)


def test_h12_empty():
    answer = recommend_charts(*cities(0))
    assert answer.candidates == []
    assert len(answer.rejected) == 1
    assert (answer.rejected[0].name, answer.rejected[0].rule) == ("*", "H12")
    candidate(cities(), "table")


def test_s1_intent():
    assert score(cities(), "column", "S1", intent="rank") == 3
    assert score(cities(), "column", "S1") == 0
    assert score(cities(), "column", "S1", intent="trend") == 0
    for intent in CATALOGUE.get("table").purposes:
        assert direct("S1", "table", cities(), intent=intent) is None
        assert score(cities(), "table", "S1", intent=intent) == 0


def test_h13_alias():
    binding = {"category": "gender_label", "group": "gender", "value": "total_deaths"}
    for name in ("grouped_column", "stacked_column"):
        failure = direct("H13", name, gender_code_and_label(), binding=binding)
        assert failure.hard
        assert failure.explanation == "The group is a label of the category."
        assert failure.fix == "Bind the label as category and drop the group"
        assert direct("H13", name, grouped()) is None
        candidate(grouped(), name)


def test_h14_whole():
    for name in ("pie", "donut", "treemap"):
        failure = direct("H14", name, own_share_by_region())
        assert failure.hard
        assert failure.explanation == "The shares are of different wholes; they do not add up to one."
        assert failure.fix == "Use a bar"
        assert direct("H14", name, gender_share()) is None
        candidate(gender_share(), name)
    # H5 is the first rejection for eight slices; H14 removes treemap too.
    rejected(own_share_by_region(), "treemap", "H14")


def test_h14_checks_unbound_shares_even_when_binding_an_additive_measure():
    columns, result = own_share_by_region()
    columns[1].aggregate = "sum"
    for name in ("pie", "donut", "treemap"):
        assert direct("H14", name, (columns, result),
                      binding={"category": "region", "value": "pop_under_15"}).hard


def test_five_shares_summing_to_100_keep_pie():
    columns = [column("category", "category"), column("share", "share", denominator="all")]
    data = columns, table(columns, [[name, value] for name, value in zip("ABCDE", [40, 25, 20, 10, 5])])
    assert direct("H14", "pie", data) is None
    assert recommend_charts(*data, intent="share").candidates[0].name == "pie"


def test_s2_suggested():
    assert score(cities(), "bar", "S2", suggested="Horizontal Bar") == 3
    assert score(cities(), "bar", "S2", suggested="missing") == 0


def test_s3_caution():
    assert score(cities(), "pie", "S3") == -1
    assert score(cities(), "column", "S3") == 0


def test_s4_count():
    for n, expected in [(12, 1), (15, 0), (25, -2)]:
        assert score(cities(n), "column", "S4") == expected
    assert "Other" in direct("S4", "column", cities(25)).fix
    assert "Other" in next(s.explanation for s in candidate(cities(25), "column").breakdown if s.rule == "S4")


def test_s5_long_labels():
    columns, result = cities()
    for row in result.rows:
        row[0] = row[0].ljust(20, "x")
    assert score((columns, result), "bar", "S5") == 1
    assert score((columns, result), "column", "S5") == -2
    assert score(cities(), "column", "S5") == 0


def test_s6_balance():
    columns, result = gender_share()
    result.rows[0][-1], result.rows[1][-1] = 50.4, 49.6
    assert score((columns, result), "pie", "S6") == -2
    assert score(gender_share(), "pie", "S6") == 0


def test_s7_time_reads():
    assert score(monthly(), "line", "S7") == 2
    assert score(cities(), "bar", "S7") == 0
    # Bar rejects time via H1 because the immutable catalogue excludes that kind.
    assert direct("S7", "bar", monthly(), binding={"category": "month", "value": "visits"}).score == -2


def test_s8_composition():
    assert score(grouped(), "stacked_column", "S8", intent="composition") == 1
    assert score(grouped(), "grouped_column", "S8", intent="compare") == 1
    assert score(grouped(), "stacked_column", "S8", intent="compare") == 0


def test_s9_unbound():
    data = gender_share()
    assert candidate(data, "column").binding == {"category": "label", "value": "n"}
    assert score(data, "column", "S9") == -1  # share unbound; code twin exempt
    assert direct("S9", "column", data, binding={"category": "label", "value": "share"}).score == -1
    assert score(cities(), "column", "S9") == 0
    columns, result = cities()
    columns += [column("label2", "category"), column("id", "identifier")]
    data = columns, table(columns, [r + ["other", str(i)] for i, r in enumerate(result.rows)])
    assert score(data, "column", "S9") == -1  # None sources do not imply code twins.
    assert score(data, "table", "S9") == 0
    columns = [column("city", "category"), *[column(f"m{i}", "measure") for i in range(6)]]
    data = columns, table(columns, [["A", 1, 2, 3, 4, 5, 6], ["B", 6, 5, 4, 3, 2, 1]])
    assert score(data, "column", "S9") == -5  # One penalty per unbound measure, without a cap.


def test_s9_alias_is_exempt_without_a_shared_source():
    columns, result = gender_code_and_label()
    columns[0].source = columns[1].source = None
    assert score((columns, result), "column", "S9") == 0
    assert direct("S9", "column", (columns, result),
                  binding={"category": "gender", "value": "total_deaths"}).score == 0


def test_s10_few_points():
    assert score(scatter_points(9), "scatter", "S10") == -2
    assert score(scatter_points(10), "scatter", "S10") == 0


def test_s11_words():
    entry = CATALOGUE.get("word_cloud").model_copy(update={"category_min": None})
    assert direct("S11", "word_cloud", cities(19), entry=entry).score == -3
    assert direct("S11", "word_cloud", cities(20), entry=entry) is None


def test_s12_fallback():
    columns = [column("id", "identifier")]
    answer = recommend_charts(columns, table(columns, [["a"], ["b"]]))
    assert [(c.name, c.score) for c in answer.candidates] == [("table", 0)]


def test_s13_one_number():
    assert candidate(single_number(), "table").score == 2
    for entry in CATALOGUE.entries:
        expected = 2 if entry.name == "table" else -3 if entry.name == "indicator" else 0
        assert direct("S13", entry.name, single_number()).score == expected
        assert direct("S13", entry.name, single_number(), intent="summary").score == (3 if entry.name == "indicator" else 0)
    assert direct("S13", "column", cities()) is None
    assert direct("S13", "column", single_number(), intent="trend") is None


def test_s14_few_parts():
    assert score(cities(7), "treemap", "S14") == -2
    result = direct("S14", "treemap", cities(7))
    assert result.explanation == "few parts read better as a pie or a bar"
    assert result.fix == "use a pie, a donut, or a bar"
    assert score(cities(8), "treemap", "S14") == 0
    assert direct("S14", "treemap", cities(8)) is None
    assert direct("S14", "column", cities(7)) is None


def test_c4_order():
    assert has(checked("line", monthly(), sort="value desc"), "C4")
    assert not has(checked("line", monthly(), sort="none"), "C4")
    assert not has(checked("line", monthly()), "C4")
    columns, result = cities()
    columns[0].kind = "ordinal"
    assert has(checked("column", (columns, result), sort="category asc"), "C4")


def test_c5_limit():
    assert has(checked("column", limit=3, sort="category asc"), "C5")
    assert not has(checked("column", limit=3, sort="value desc"), "C5")
    assert not has(checked("column", limit=3), "C5")  # Effective default is value desc.
    columns, result = cities()
    columns[1].aggregate = "avg"
    assert has(checked("column", (columns, result), limit=3, sort="value asc"), "C5")


def test_c6_colors():
    assert has(checked("column", palette=["red"] * 5), "C6")
    assert not has(checked("column", palette=["#000000"]), "C6")
    assert not has(checked("column", palette=["#000"] * 5), "C6")
    assert not has(checked("column"), "C6")


def test_c7_contrast():
    assert has(checked("column", palette=["#FFFFFF"] * 5), "C7")
    assert not has(checked("column", palette=["#000000"] * 5), "C7")
    assert has(checked("column", theme="dark", palette=["#000000"] * 5), "C7")
    assert not has(checked("column", theme="dark", palette=["#FFFFFF"] * 5), "C7")
    assert has(checked("column", background_color="#1783FF", emphasis=["City0"]), "C7")
    assert not has(checked("column", emphasis=["City0"]), "C7")
    # GPT-Vis's dark theme uses black: #5A5A5A just clears the 3:1 threshold.
    assert not has(checked("column", theme="dark", palette=["#5A5A5A"] * 5), "C7")
    assert has(checked("column", theme="dark", palette=["#595959"] * 5), "C7")
    assert not has(checked("column", theme="academy", palette=["#000000"] * 5), "C7")


def test_c8_words():
    shape = describe(*cities())
    entry = CATALOGUE.get("column")
    assert has(check_rules(entry, Spec(type="column", title=" "), shape, default_binding(entry, shape)), "C8")
    assert not has(checked("column"), "C8")


def test_c9_emphasis():
    assert has(checked("column", emphasis=["Missing"]), "C9")
    assert not has(checked("column", emphasis=["City0"]), "C9")
    assert has(checked("table", emphasis=["City0"]), "C9")


def test_c9_group_emphasis():
    assert not checked("grouped_column", grouped(), emphasis=["F", "City0"])
    assert has(checked("grouped_column", grouped(), emphasis=["Missing"]), "C9")
    assert has(checked("column", grouped(), emphasis=["F"]), "C9")


def test_c10_hard():
    violations = checked("pie", cities(7))
    assert has(violations, "C10")
    assert "H5" in has(violations, "C10")[0].message
    assert not has(checked("pie", cities(2)), "C10")
    assert has(checked("table", cities(0)), "C10")
    columns, result = cities(7)
    columns[1].aggregate = "avg"
    result.rows[0][1] = -1
    messages = " ".join(v.message for v in has(checked("pie", (columns, result)), "C10"))
    assert all(rule in messages for rule in ("H3", "H4", "H5"))


def test_c11_range():
    assert "inside the range" in has(checked("line", monthly(), axis_y_min=200), "C11")[0].message
    assert "only on" in has(checked("column", monthly(), axis_y_min=200), "C11")[0].message
    assert not has(checked("line", monthly(), axis_y_min=100, axis_y_max=245), "C11")
    assert has(checked("line", monthly(), axis_y_min=245, axis_y_max=100), "C11")
    assert has(checked("line", monthly(), axis_x_min=0), "C11")
    assert has(checked("scatter", scatter_points(), axis_x_min=2), "C11")
    assert not has(checked("scatter", scatter_points(), axis_x_min=1, axis_x_max=40, axis_y_min=10, axis_y_max=400), "C11")
    assert has(checked("dual_axes", two_units(), axis_y_max=500), "C11")


def test_c12_crop():
    assert has(checked("line", monthly(), zero=False), "C12")
    assert has(checked("line", monthly(), axis_y_min=50), "C12")
    columns, result = monthly()
    for i, row in enumerate(result.rows):
        row[1] = 200 + 45 * i / 11
    assert not has(checked("line", (columns, result), zero=False), "C12")
    assert not has(checked("line", monthly(), zero=True), "C12")
    result.rows[0][1] = 122.5
    assert has(checked("line", (columns, result), zero=False), "C12")


def test_c13_percent():
    columns, result = grouped()
    columns[2].aggregate = "avg"
    assert has(checked("stacked_column", (columns, result), percent=True), "C13")
    assert not has(checked("stacked_column", grouped(), percent=True), "C13")
    assert has(checked("column", percent=True), "C13")
    columns[2].aggregate = "sum"
    result.rows[0][2] = -1
    assert has(checked("stacked_column", (columns, result), percent=True), "C13")


def test_c14_log():
    columns, result = monthly(3)
    result.rows = [["2025-01", 1], ["2025-02", 20], ["2025-03", 50]]
    assert has(checked("line", (columns, result), axis_y_scale="log"), "C14")
    result.rows[-1][1] = 1000
    assert not has(checked("line", (columns, result), axis_y_scale="log"), "C14")
    result.rows[-1][1] = 100
    assert not has(checked("line", (columns, result), axis_y_scale="log"), "C14")
    result.rows[0][1] = 0
    assert has(checked("line", (columns, result), axis_y_scale="log"), "C14")
    assert has(checked("column", axis_y_scale="log"), "C14")


def test_c15_labels():
    assert has(checked("column", cities(60), labels="on"), "C15")
    assert not has(checked("column", cities(12), labels="on"), "C15")
    assert not has(checked("column", cities(60), labels="off"), "C15")
    assert has(checked("grouped_column", grouped(30), labels="on"), "C15")
    assert not has(checked("grouped_column", grouped(6), labels="on"), "C15")


def test_c16_contradiction():
    assert has(checked("line", monthly(), zero=True, axis_y_min=10), "C16")
    assert not has(checked("line", monthly(), zero=True, axis_y_min=0), "C16")


def test_c17_format():
    assert not has(checked("column", format="0.0%"), "C17")
    assert not has(checked("column", format="0,0 SAR"), "C17")


def test_checks_collect_all_errors_with_fixes():
    violations = checked("column", palette=["red"], emphasis=["missing"], percent=True,
                         labels="on", data=cities(60), axis_y_min=10, zero=True)
    assert {"C6", "C9", "C10", "C11", "C13", "C15", "C16"} <= {v.rule for v in violations}
    assert all(v.message and v.fix for v in violations)


def test_h10_lets_a_count_and_an_average_share_two_axes_when_no_unit_is_written():
    columns, result = two_units()
    columns[1].unit = columns[2].unit = None
    columns[1].aggregate, columns[2].aggregate = "sum", "avg"
    candidate((columns, result), "dual_axes")
    columns[2].aggregate = "sum"
    rejected((columns, result), "dual_axes", "H10")
