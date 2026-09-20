from vis_agent.designer.capabilities import chart_capabilities, common_keys
from vis_agent.designer.catalogue import CATALOGUE


def test_common_keys_are_the_real_intersection():
    common = set(common_keys())
    assert {"title", "description", "language", "theme", "width", "height", "palette"} <= common
    assert {"labels", "legend", "bind", "fold", "innerRadius", "axisYMin"}.isdisjoint(common)


def test_capability_uses_internal_alias_and_discloses_renderer_mapping():
    result = chart_capabilities("grouped column", "overlapping labels")
    chart = result["chart"]
    assert chart["chart_type"] == "grouped_column"
    assert chart["renderer"]["target_type"] == "column"
    assert chart["renderer"]["fixed_options"] == {"group": True}
    assert "fold" in chart["additional_config"]
    assert chart["additional_config_schema"]["labels"]["choices"] == ["on", "off"]
    assert chart["additional_config_schema"]["bind"]["roles"] == [
        "category", "value", "group", "time", "x", "y", "value2",
    ]
    assert any("labels off" in repair for repair in chart["repairs"])
    assert any("rotation" in repair for repair in chart["unsupported_repairs"])


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
