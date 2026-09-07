import pytest

from vis_agent.designer.catalogue import CATALOGUE
from vis_agent.designer.recommend import default_binding, recommend_charts
from vis_agent.designer.shape import describe

from .conftest import cities, column, gender_share, grouped, monthly, single_number, table, two_units


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
