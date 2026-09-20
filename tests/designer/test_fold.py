import pytest

from vis_agent.designer.fold import FoldError, fold, foldable
from tests.designer.conftest import column, table


def injuries_and_deaths():
    columns = [column("month", "time"),
               column("injuries", "measure", "injury_count", aggregate="sum", unit="person"),
               column("deaths", "measure", "death_count", aggregate="sum", unit="person")]
    columns[1].meaning, columns[2].meaning = "Total injuries", "Total deaths"
    rows = [["2025-01-01", 15, 2], ["2025-02-01", 17, 3], ["2025-03-01", 19, 4]]
    return columns, table(columns, rows, types=["DATE", "HUGEINT", "HUGEINT"])


def test_fold_makes_one_row_per_source_row_and_measure():
    columns, result = injuries_and_deaths()
    folded = fold(columns, result, ["injuries", "deaths"])
    assert [c.name for c in folded.columns] == ["month", "Series", "Value"]
    assert folded.series == "Series" and folded.value == "Value"
    series, value = folded.columns[1], folded.columns[2]
    assert series.kind == "category" and series.unit is None and series.aggregate == "none"
    assert value.kind == "measure" and value.unit == "person" and value.aggregate == "sum"
    assert folded.result.rows[:2] == [["2025-01-01", "injuries", 15], ["2025-01-01", "deaths", 2]]
    assert folded.result.row_count == 6 and folded.result.types == ["DATE", "VARCHAR", "HUGEINT"]
    assert folded.result.columns == ["month", "Series", "Value"]


def test_fold_labels_fall_back_to_names_when_meanings_repeat_and_arabic_names_the_pseudo_columns():
    columns, result = injuries_and_deaths()
    columns[1].meaning = columns[2].meaning = "Total"
    folded = fold(columns, result, ["injuries", "deaths"], language="ar")
    assert folded.series == "السلسلة" and folded.value == "القيمة"
    assert [row[1] for row in folded.result.rows[:2]] == ["injuries", "deaths"]


def test_fold_avoids_a_name_the_result_already_uses():
    columns, result = injuries_and_deaths()
    columns[0].name = "Series"
    result.columns[0] = "Series"
    folded = fold(columns, result, ["injuries", "deaths"])
    assert folded.series == "Series 2" and folded.result.columns == ["Series", "Series 2", "Value"]


def test_fold_keeps_shares_as_shares_with_their_denominator():
    columns = [column("region", "category"),
               column("share_a", "share", aggregate="share", unit="%", denominator="all"),
               column("share_b", "share", aggregate="share", unit="%", denominator="all")]
    folded = fold(columns, table(columns, [["R1", 40.0, 60.0]]), ["share_a", "share_b"])
    assert folded.columns[-1].kind == "share" and folded.columns[-1].aggregate == "share"
    assert folded.columns[-1].denominator == "all"


def test_fold_refuses_a_count_beside_an_average():
    columns = [column("status", "category"), column("orders", "measure", aggregate="count"),
               column("avg_price", "measure", aggregate="avg")]
    with pytest.raises(FoldError, match="aggregated the same way.*orders \\(count\\), avg_price \\(avg\\)"):
        fold(columns, table(columns, [["new", 12, 250.0]]), ["orders", "avg_price"])


@pytest.mark.parametrize("names, fragment", [
    (["injuries"], "two or more"),
    (["injuries", "nowhere"], "not in the result: nowhere"),
    (["injuries", "injuries"], "twice"),
    (["month", "injuries"], "measures or shares only; month"),
])
def test_fold_refuses_bad_lists(names, fragment):
    columns, result = injuries_and_deaths()
    with pytest.raises(FoldError, match=fragment):
        fold(columns, result, names)


def test_fold_refuses_two_units_and_points_at_dual_axes():
    columns, result = injuries_and_deaths()
    columns[2].unit = "SAR"
    with pytest.raises(FoldError, match="one kind and one unit.*dual_axes"):
        fold(columns, result, ["injuries", "deaths"])


def test_foldable_picks_the_largest_same_unit_set_or_nothing():
    columns, _ = injuries_and_deaths()
    assert foldable(columns) == ["injuries", "deaths"]
    columns[2].unit = "SAR"
    assert foldable(columns) == []
    columns.append(column("cost", "measure", aggregate="sum", unit="SAR"))
    assert foldable(columns) == ["deaths", "cost"]
    columns.append(column("avg_cost", "measure", aggregate="avg", unit="SAR"))
    assert foldable(columns) == ["deaths", "cost"]
