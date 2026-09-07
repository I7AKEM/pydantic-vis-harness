import pytest

from vis_agent.designer.shape import describe

from .conftest import column, gender_code_and_label, gender_share, grouped, own_share_by_region, table


def test_alias_pair_is_symmetric_and_not_an_independent_group():
    shape = describe(*gender_code_and_label())
    assert shape.aliases == {frozenset(("gender", "gender_label"))}
    assert shape.is_alias("gender", "gender_label")
    assert shape.is_alias("gender_label", "gender")
    assert not shape.is_alias("gender", "gender")
    assert not shape.is_alias("gender", "missing")
    assert not describe(*grouped()).is_alias("city", "gender")


@pytest.mark.parametrize("kinds", [("category", "ordinal"), ("ordinal", "geography"), ("geography", "category")])
def test_aliases_cover_all_label_kinds_and_repeated_pairs(kinds):
    columns = [column("a", kinds[0]), column("b", kinds[1])]
    shape = describe(columns, table(columns, [[1, "First"], [2, "Second"], [1, "First"]]))
    assert shape.is_alias("a", "b")


@pytest.mark.parametrize("rows", [
    [["F", "Female"], ["M", "Female"]],
    [["F", "Female"], ["F", "Woman"]],
    [["F", "Female"], ["M", "Male"], ["F", "Male"]],
    [[1, "First"], ["1", "Second"], [1, "Second"]],
    [["F", "Female"], [None, None]],
    [[None, None]], [],
])
def test_aliases_need_nonempty_one_to_one_pairs(rows):
    columns = [column("code", "category"), column("label", "category")]
    assert not describe(columns, table(columns, rows)).is_alias("code", "label")


def test_time_and_identifier_columns_are_not_alias_labels():
    columns = [column("label", "category"), column("time", "time"), column("id", "identifier")]
    shape = describe(columns, table(columns, [["A", "2025", "a"], ["B", "2026", "b"]]))
    assert shape.aliases == set()


def test_aliases_preserve_numeric_and_text_codes():
    columns = [column("code", "category"), column("label", "category")]
    shape = describe(columns, table(columns, [[1, "Number"], ["1", "Text"]]))
    assert shape.is_alias("code", "label")


def test_share_whole_facts_and_raw_facts_survive_a_limit():
    shape = describe(*gender_share())
    assert shape.column("share").sums_to_whole is True
    assert all(c.sums_to_whole is None for c in shape.columns if c.kind != "share")
    assert shape.limited("label", 1).is_alias("gender", "label")
    regions = describe(*own_share_by_region())
    assert regions.column("share_under_15").sums_to_whole is False
    assert regions.limited("region", 5).column("share_under_15").sums_to_whole is False


@pytest.mark.parametrize("values,whole", [
    ([60, 40], True), ([60, 39], True), ([60, 41], True),
    ([60, 38.999], False), ([60, 41.001], False),
    ([0.6, 0.4], True), ([0.99], True), ([1.01], True),
    ([0.98999], False), ([1.01001], False),
    ([60, 40, None], True), ([None], False), ([], False),
    (["100"], False), ([True], False), ([100, "bad"], False),
])
def test_share_sum_tolerances_and_non_numeric_values(values, whole):
    columns = [column("share", "share", denominator="all")]
    shape = describe(columns, table(columns, [[value] for value in values]))
    assert shape.column("share").sums_to_whole is whole
