import json

from vis_agent.designer.capabilities import chart_capabilities, common_keys
from vis_agent.designer.catalogue import CATALOGUE


def test_common_keys_are_the_real_intersection():
    common = set(common_keys())
    assert {"title", "description", "language", "theme", "width", "height", "palette"} <= common
    assert {"labels", "legend", "bind", "fold", "innerRadius", "axisYMin"}.isdisjoint(common)


def test_capability_uses_internal_alias_and_discloses_renderer_mapping():
    result = chart_capabilities("grouped column")
    chart = result["chart"]
    assert chart["chart_type"] == "grouped_column"
    assert chart["renderer"]["target_type"] == "column"
    assert chart["renderer"]["fixed_options"] == {"group": True}
    assert "fold" in chart["additional_config"]
    assert chart["additional_config_schema"]["labels"]["choices"] == ["on", "off"]
    assert chart["additional_config_schema"]["bind"]["roles"] == [
        "category", "value", "group", "time", "x", "y", "value2",
    ]
    repair = chart_capabilities("grouped column", "overlapping labels")
    assert repair["response_scope"] == "problem_repair"
    assert set(repair["chart"]["repair_config_schema"]) == {"labels", "width", "height", "format"}
    assert any("labels off" in item for item in repair["chart"]["repairs"])
    assert any("rotation" in item for item in repair["chart"]["unsupported_repairs"])


def test_targeted_capability_does_not_repeat_the_global_inventory():
    result = chart_capabilities("bar", "label_overlap")
    assert "installed_native_types" not in result
    assert "common_to_all_schema" not in result
    assert "charts" not in result
    assert len(json.dumps(result)) < 3000


def test_unknown_problem_retains_full_schema_for_agent_inspection():
    result = chart_capabilities("bar", "baseline alignment")
    assert result["response_scope"] == "single_chart"
    assert "additional_config_schema" in result["chart"]
    assert any("No curated repair" in item for item in result["chart"]["repairs"])


def test_donut_capability_documents_pinned_inner_radius_api_units_and_bounds():
    radius = chart_capabilities("donut")["chart"]["additional_config_schema"]["innerRadius"]
    assert radius["minimum"] == 0 and radius["maximum"] == 1
    assert radius["unit"] == "dimensionless ratio"
    assert radius["example"] == 0.6
    assert "not a percentage" in radius["note"]


def test_capability_inventory_is_read_from_the_pinned_installed_renderer():
    result = chart_capabilities()
    package = result["package"]
    assert package["name"] == "@antv/gpt-vis-ssr"
    assert package["pinned_version"] == package["installed_version"] == "0.3.8"
    assert package["installed_matches_pin"] is True
    assert package["embedded_gpt_vis_version"] == "0.4.7"
    assert package["browser_reference_version"] == "1.0.1"
    native = set(result["installed_native_types"])
    targets = {entry.draw.type for entry in CATALOGUE.entries if entry.name != "indicator"}
    assert targets <= native
    assert {"funnel", "sankey", "waterfall"} <= set(result["native_types_not_exposed_by_vis_dsl"])
    assert result["official_skill"]["exists"] is True


def test_capability_reports_invalid_type_without_guessing():
    result = chart_capabilities("magic chart")
    assert result["error"].startswith("Unknown chart type")
    assert result["available_chart_types"] == [entry.name for entry in CATALOGUE.entries]


def test_low_contrast_repair_matches_runtime_hex_contract():
    chart = chart_capabilities("indicator", "contrast")["chart"]
    assert any("3:1" in repair for repair in chart["repairs"])
    assert any("Named CSS colours" in repair for repair in chart["unsupported_repairs"])
