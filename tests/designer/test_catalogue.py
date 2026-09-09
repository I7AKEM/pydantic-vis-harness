from vis_agent.designer.catalogue import CATALOGUE, load_catalogue
from vis_agent.designer.models import ChartType
from typing import get_args


def test_every_chart_type_has_one_entry_in_order():
    names = [entry.name for entry in CATALOGUE.entries]
    assert names == list(get_args(ChartType))


def test_entries_are_complete():
    for entry in CATALOGUE.entries:
        assert entry.purposes, entry.name
        if entry.name == "table":
            assert entry.roles == {}, entry.name
            assert entry.fields == {}, entry.name
        else:
            assert entry.roles, entry.name
            assert any(role.required for role in entry.roles.values()), entry.name
        assert entry.draw.type, entry.name
        for role in entry.roles.values():
            assert role.kinds, (entry.name, role)
        for role in entry.fields:
            assert role in entry.roles, (entry.name, role)


def test_aliases_are_unique_and_resolve():
    seen = {}
    for entry in CATALOGUE.entries:
        for alias in [entry.name, *entry.aliases]:
            assert alias not in seen, (alias, seen.get(alias), entry.name)
            seen[alias] = entry.name
    assert CATALOGUE.find("doughnut").name == "donut"
    assert CATALOGUE.find("horizontal bar").name == "bar"
    assert CATALOGUE.find("nothing") is None


def test_ratings_and_whole_charts():
    assert CATALOGUE.get("pie").rating == "caution"
    assert CATALOGUE.get("table").rating == "fallback"
    assert CATALOGUE.get("pie").additive_value and CATALOGUE.get("stacked_column").additive_value
    assert not CATALOGUE.get("column").additive_value
    assert CATALOGUE.get("histogram").raw_values and CATALOGUE.get("boxplot").raw_values


def test_keys_per_entry():
    assert "innerRadius" in CATALOGUE.get("donut").keys and "innerRadius" not in CATALOGUE.get("pie").keys
    assert "percent" in CATALOGUE.get("stacked_bar").keys and "percent" not in CATALOGUE.get("grouped_bar").keys
    assert "axisYMin" in CATALOGUE.get("line").keys and "axisYMin" not in CATALOGUE.get("column").keys
    assert "axisYScale" in CATALOGUE.get("scatter").keys and "axisXMin" in CATALOGUE.get("scatter").keys
    assert "binNumber" in CATALOGUE.get("histogram").keys


def test_fold_keys_and_time_categories_are_explicit():
    fold_charts = {"grouped_column", "stacked_column", "grouped_bar", "stacked_bar", "multi_line", "stacked_area"}
    assert {entry.name for entry in CATALOGUE.entries if "fold" in entry.keys} == fold_charts
    assert "time" in CATALOGUE.get("grouped_column").roles["category"].kinds
    assert "time" in CATALOGUE.get("stacked_column").roles["category"].kinds
    assert "time" not in CATALOGUE.get("grouped_bar").roles["category"].kinds


def test_prompt_text_lists_every_entry():
    text = CATALOGUE.describe()
    for entry in CATALOGUE.entries:
        assert entry.name in text
