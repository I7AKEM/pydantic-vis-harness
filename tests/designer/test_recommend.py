import pytest

from vis_agent.designer.catalogue import CATALOGUE
from vis_agent.designer.recommend import default_binding, recommend_charts
from vis_agent.designer.shape import describe

from .conftest import (cities, column, gender_code_and_label, gender_share, grouped, monthly,
                       own_share_by_region, single_number, table, two_same_unit_measures,
                       two_same_unit_measures_by_city, two_units)


def test_cities_ranking_and_binding():
    answer = recommend_charts(*cities())
    assert answer.candidates[0].name == "column"
    assert answer.candidates[0].binding == {"category": "city", "value": "violations"}
    ranked = recommend_charts(*cities(), intent="rank")
    assert [c.name for c in ranked.candidates[:2]] == ["column", "bar"]
    for candidate in ranked.candidates[:2]:
        assert next(s.score for s in candidate.breakdown if s.rule == "S1") == 3


def test_monthly_ranking():
    assert recommend_charts(*monthly()).candidates[0].name == "line"


def test_alias_binding_uses_readable_label_and_drops_redundant_groups():
    data = gender_code_and_label()
    shape = describe(*data)
    assert default_binding(CATALOGUE.get("column"), shape)["category"].name == "gender_label"
    for name in ("grouped_column", "grouped_bar", "stacked_column", "stacked_bar"):
        assert default_binding(CATALOGUE.get(name), shape) is None
    answer = recommend_charts(*data, intent="compare")
    assert [c.name for c in answer.candidates[:2]] == ["column", "bar"]
    assert all("group" not in c.binding for c in answer.candidates)


def test_alias_preference_keeps_unrelated_cardinality_ties_stable():
    columns = [column("code", "category"), column("label", "category"), column("group", "category"),
               column("value", "measure", aggregate="sum")]
    data = columns, table(columns, [[c, label, g, 1] for c, label in [("F", "Female"), ("M", "Male")]
                                   for g in ["A much longer group A", "A much longer group B"]])
    binding = default_binding(CATALOGUE.get("grouped_column"), describe(*data))
    assert binding["category"].name == "label"
    assert binding["group"].name == "group"


@pytest.mark.parametrize("name", ["pie", "donut", "treemap"])
def test_whole_value_binding_preference(name):
    columns, result = gender_share()
    columns.insert(2, column("average", "measure", aggregate="avg"))
    result = table(columns, [row[:2] + [10] + row[2:] for row in result.rows])
    entry = CATALOGUE.get(name)
    assert default_binding(entry, describe(columns, result))["value"].name == "share"
    result.rows[0][-1] = 20
    assert default_binding(entry, describe(columns, result))["value"].name == "n"
    columns[3].aggregate = "avg"
    assert default_binding(entry, describe(columns, result))["value"].name == "share"


def test_own_shares_reject_whole_charts_and_rank_bars():
    answer = recommend_charts(*own_share_by_region(), intent="share")
    assert answer.candidates[0].name == "bar"
    assert "column" in {c.name for c in answer.candidates}
    assert {"pie", "donut", "treemap"} <= {r.name for r in answer.rejected}


def test_share_ranking_obeys_catalogue_and_scores():
    answer = recommend_charts(*gender_share(), intent="share")
    names = [c.name for c in answer.candidates]
    assert names[:2] == ["pie", "donut"]
    assert [name for name in names if name in {"pie", "donut", "treemap", "table"}] == [
        "pie", "donut", "treemap", "table",
    ]
    # Other zero-score charts retain their earlier catalogue positions.
    assert next(c.score for c in answer.candidates if c.name == "treemap") == 0
    assert next(c.score for c in answer.candidates if c.name == "table") == 0
    assert names.index("pie") < names.index("donut")
    pie, donut = [next(c for c in answer.candidates if c.name == name) for name in ("pie", "donut")]
    assert pie.score == donut.score == 1
    assert pie.binding["value"] == "share"


def test_two_units_and_single_number():
    names = [c.name for c in recommend_charts(*two_units()).candidates]
    assert "dual_axes" in names and "line" in names
    assert recommend_charts(*single_number()).candidates[0].name == "table"


def test_missing_roles_explain_what_the_chart_needs_and_the_result_offers():
    answer = recommend_charts(*two_units(), intent="trend")
    stacked_area = next(rejection for rejection in answer.rejected if rejection.name == "stacked_area")
    assert stacked_area.rule == "H1"
    assert all(text in stacked_area.explanation for text in (
        "needs", "group (category/ordinal/geography)", "month (time)",
        "visits (measure, visits)", "revenue (measure, SAR)",
    ))


def test_same_unit_monthly_measures_fold_into_multi_line():
    answer = recommend_charts(*two_same_unit_measures(), intent="trend")
    assert answer.candidates[0].name == "multi_line"
    assert answer.candidates[0].binding == {"time": "month"}
    assert answer.candidates[0].fold == ["injuries", "deaths"]
    line = next(candidate for candidate in answer.candidates if candidate.name == "line")
    assert any(rule.rule == "S9" and "deaths" in rule.explanation for rule in line.breakdown)
    dual_axes = next(rejection for rejection in answer.rejected if rejection.name == "dual_axes")
    assert dual_axes.rule == "H10"


def test_same_unit_city_measures_fold_into_grouped_charts():
    answer = recommend_charts(*two_same_unit_measures_by_city(), intent="compare")
    assert answer.candidates[0].name in {"grouped_column", "grouped_bar"}
    assert answer.candidates[0].binding == {"category": "city"}
    assert answer.candidates[0].fold == ["revenue", "cost"]
    stacked = next(candidate for candidate in answer.candidates if candidate.name == "stacked_column")
    assert stacked.fold == ["revenue", "cost"]


def test_two_units_and_real_groups_are_not_folded():
    answer = recommend_charts(*two_units(), intent="compare", suggested="dual_axes")
    assert answer.candidates[0].name == "dual_axes"
    assert all(candidate.fold == [] for candidate in answer.candidates)
    grouped_answer = recommend_charts(*grouped(), intent="compare")
    grouped_column = next(candidate for candidate in grouped_answer.candidates if candidate.name == "grouped_column")
    assert grouped_column.fold == []


def test_explanations_and_stable_order():
    answer = recommend_charts(*cities())
    order = {e.name: i for i, e in enumerate(CATALOGUE.entries)}
    assert answer.candidates == sorted(answer.candidates, key=lambda c: (-c.score, order[c.name]))
    for candidate in answer.candidates:
        assert candidate.breakdown
        assert candidate.score == sum(s.score for s in candidate.breakdown)
        assert all(s.rule.startswith("S") and s.explanation for s in candidate.breakdown)
    assert all(r.rule.startswith("H") and r.explanation for r in answer.rejected)


def test_default_binding_cardinality_order_and_optional_roles():
    shape = describe(*grouped())
    binding = default_binding(CATALOGUE.get("grouped_column"), shape)
    assert {r: c.name for r, c in binding.items()} == {"category": "city", "group": "gender", "value": "n"}
    assert default_binding(CATALOGUE.get("scatter"), shape) is None
    assert default_binding(CATALOGUE.get("table"), shape) == {}
    columns, result = monthly()
    columns[0] = column("month", "ordinal")
    assert default_binding(CATALOGUE.get("line"), describe(columns, result))["time"].name == "month"
    # Bar's catalogue role excludes time, even though column accepts it.
    assert default_binding(CATALOGUE.get("bar"), describe(*monthly())) is None


def test_shape_statistics_and_column_lookup():
    columns = [column("label", "category"), column("value", "measure"), column("id", "identifier"),
               column("when", "time"), column("place", "geography"), column("order", "ordinal"),
               column("share", "share", denominator="all")]
    result = table(columns, [["abc", -2, "a", "2025", "x", "low", 0.4],
                             [None, 4.5, "b", "2026", "x", "high", 0.6],
                             ["abc", None, "c", None, None, None, None]])
    shape = describe(columns, result)
    assert shape.rows == 3
    assert [c.name for c in shape.labels] == ["label", "place", "order"]
    assert [c.name for c in shape.measures] == ["value", "share"]
    assert [c.name for c in shape.times] == ["when"]
    assert [c.name for c in shape.identifiers] == ["id"]
    value = shape.column("value")
    assert (value.distinct, value.minimum, value.maximum, value.has_negative, value.is_numeric, value.nulls) == (2, -2, 4.5, True, True, 1)
    assert shape.column("label").longest_label == 3
    assert not shape.column("label").is_numeric
    with pytest.raises(KeyError):
        shape.column("missing")


@pytest.mark.parametrize("values,numeric,minimum,maximum", [
    ([True, 3, None], False, 3, 3), (["2", -1, None], False, -1, -1),
    ([None, None], True, None, None), ([False, True], False, None, None),
])
def test_shape_numeric_cells(values, numeric, minimum, maximum):
    columns = [column("value", "measure")]
    shape = describe(columns, table(columns, [[v] for v in values]))
    value = shape.column("value")
    assert (value.is_numeric, value.minimum, value.maximum) == (numeric, minimum, maximum)
    assert value.nulls == values.count(None)


def test_shape_uses_result_column_names_and_declared_row_count():
    columns = [column("value", "measure"), column("label", "category")]
    result = table(columns, [["abc", 3]])
    result.columns = ["label", "value"]
    result.row_count = 9
    shape = describe(columns, result)
    assert shape.rows == 9
    assert shape.column("value").maximum == 3
    assert shape.column("label").longest_label == 3
