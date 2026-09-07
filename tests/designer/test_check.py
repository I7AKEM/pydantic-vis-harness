from pathlib import Path

import pytest

from vis_agent.designer.check import check_spec
from vis_agent.designer.models import Compromise
from vis_agent.designer.syntax import KEYS, STYLE_KEYS, parse, to_text
from vis_agent.render.base import Capability, RENDERERS, Rendered, capability_for

from .conftest import cities, gender_share, monthly


COLUMN = "vis column\ntitle Cities\ndescription Counts by city\nbind\n  category city\n  value violations\n"
LINE = "vis line\ntitle Visits\ndescription Monthly visits\nbind\n  time month\n  value visits\n"


def test_passing_arabic_donut_is_canonical_with_legend_compromise():
    text = "vis donut\ntitle النسبة\ndescription النسبة حسب الجنس\nlanguage ar\nbind\n  category label\n  value share\n"
    check = check_spec(text, *gender_share())
    assert check.ok
    assert check.violations == []
    assert check.canonical == to_text(parse(text))
    assert any("legend" in c.message for c in check.compromises)


def test_syntax_error_stops_before_semantic_checks():
    text = COLUMN.replace("category city", "category missing") + "unsupported x\ninnerRadius 0.5\n"
    check = check_spec(text, *cities())
    assert not check.ok
    assert check.canonical is None
    assert [(v.rule, v.line) for v in check.violations] == [("syntax", 7)]
    assert check.violations[0].fix


def test_three_semantic_violations_are_reported_together_in_order():
    text = COLUMN.replace("category city", "category missing") + "innerRadius 0.5\n"
    check = check_spec(text, *cities())
    assert not check.ok
    assert check.canonical is None
    assert [v.rule for v in check.violations] == ["C2", "C3", "C10"]
    assert all(v.fix for v in check.violations)


def test_missing_type_is_a_syntax_error_on_line_one():
    check = check_spec("title x\n", *cities())
    assert [(v.rule, v.line) for v in check.violations] == [("syntax", 1)]
    assert not check.ok and check.canonical is None


def test_all_parse_issues_keep_their_line_numbers():
    check = check_spec(COLUMN + "unsupported x\nwidth wide\n", *cities())
    assert [(v.rule, v.line) for v in check.violations] == [("syntax", 7), ("syntax", 8)]


def test_c1_renderer_does_not_draw_type(monkeypatch):
    monkeypatch.setitem(RENDERERS, "fake", lambda _: Capability(
        honoured=set(), degraded={}, rejected={"*": "not drawn"},
    ))
    check = check_spec(COLUMN, *cities(), renderer="fake")
    assert [v.rule for v in check.violations] == ["C1"]
    assert "not drawn" in check.violations[0].message
    assert not check.ok and check.canonical is None


@pytest.mark.parametrize("binding, message", [
    ("  category city\n", "value"),
    ("  category violations\n  value violations\n", "category"),
    ("  category city\n  value absent\n", "absent"),
    ("  category city\n  value violations\n  group city\n", "group"),
])
def test_c2_missing_columns_roles_wrong_kinds_and_unsupported_roles(binding, message):
    check = check_spec(COLUMN.split("bind")[0] + "bind\n" + binding, *cities())
    violations = [v for v in check.violations if v.rule == "C2"]
    assert len(violations) == 1
    assert message in violations[0].message
    assert not check.ok


def test_c3_uses_text_keys_and_checks_false_values():
    check = check_spec(COLUMN + "innerRadius 0.5\nzero false\n", *cities())
    violations = [v for v in check.violations if v.rule == "C3"]
    assert len(violations) == 2
    assert "innerRadius" in violations[0].message
    assert "zero" in violations[1].message


def test_c10_hard_failure_is_reported_once():
    check = check_spec(COLUMN.replace("vis column", "vis pie"), *cities(7))
    assert [v.rule for v in check.violations] == ["C10"]
    assert "H5" in check.violations[0].message


def test_check_rules_run_once_and_other_rules_are_preserved(monkeypatch):
    import vis_agent.designer.check as module

    calls = []
    original = module.check_rules

    def tracked(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(module, "check_rules", tracked)
    check = check_spec(LINE + "sort value desc\n", *monthly())
    assert len(calls) == 1
    assert [v.rule for v in check.violations] == ["C4"]


def test_renderer_rejections_and_degradations_are_both_reported(monkeypatch):
    monkeypatch.setitem(RENDERERS, "fake", lambda _: Capability(
        honoured=set(), rejected={"subtitle": "no second title", "labels": "no labels"},
        degraded={"legend": "legend stays fixed", "width": "fixed width"},
    ))
    check = check_spec(COLUMN + "subtitle Counts\nlegend off\n", *cities(), renderer="fake")
    assert [(v.rule, v.message) for v in check.violations] == [("renderer", "subtitle: no second title")]
    assert check.compromises == [Compromise(key="legend", message="legend stays fixed")]
    assert not check.ok and check.canonical is None


@pytest.mark.parametrize("extra, expected", [
    ("", False), ("language ar\n", True), ("direction rtl\n", True),
    ("direction ltr\n", True), ("language ar\ndirection ltr\n", True),
])
def test_direction_presence_includes_arabic_default(extra, expected):
    check = check_spec(COLUMN + extra, *cities())
    assert check.ok
    assert any(c.key == "direction" for c in check.compromises) is expected


def test_common_and_style_keys_are_accepted_and_mapped_to_capabilities(monkeypatch):
    monkeypatch.setitem(RENDERERS, "fake", lambda _: Capability(
        honoured=set(), rejected={}, degraded={"backgroundColor": "fixed background"},
    ))
    check = check_spec(COLUMN + "style\n  backgroundColor #ffffff\n", *cities(), renderer="fake")
    assert check.ok
    assert check.compromises == [Compromise(key="backgroundColor", message="fixed background")]


def test_present_keys_differ_from_defaults(monkeypatch):
    monkeypatch.setitem(RENDERERS, "fake", lambda _: Capability(
        honoured=set(), degraded={}, rejected={"percent": "no percent", "theme": "no theme"},
    ))
    check = check_spec(COLUMN + "percent false\ntheme default\n", *cities(), renderer="fake")
    assert check.ok


def test_gptvis_capabilities_cover_vocabulary_and_table_degradations():
    capability = capability_for("gptvis", "donut")
    assert capability.honoured == set(KEYS) | set(STYLE_KEYS) | {"bind"}
    assert capability.rejected == {}
    assert "legend" in capability.degraded["direction"]
    table = capability_for("gptvis", "table")
    assert set(table.degraded) == {"subtitle", "labels", "legend", "axisXTitle", "axisYTitle", "direction", "format"}
    assert set(table.degraded.values()) == {"tables are drawn as the package draws them"}


def test_table_needs_no_bindings_and_reports_degraded_keys():
    check = check_spec("vis table\ntitle Cities\ndescription Counts\nsubtitle Details\nlabels off\nformat 0\n", *cities())
    assert check.ok
    assert {c.key for c in check.compromises} == {"subtitle", "labels", "format"}


def test_unknown_renderer_raises_clear_key_error():
    with pytest.raises(KeyError, match="[Uu]nknown renderer.*missing"):
        capability_for("missing", "column")


def test_rendered_contract():
    rendered = Rendered(png="chart.png", html="chart.html", config="config.json",
                        width=2400, height=1350, seconds=0.3, non_background_share=0.2,
                        compromises=[], drawn_rows=5, folded_rows=0, dropped_rows=0)
    assert rendered.png == Path("chart.png")
    assert rendered.drawn_rows == 5


@pytest.mark.parametrize("extra, start", [("zero false\n", "100"), ("axisYMin 90\n", "90")])
def test_c12_valid_crop_records_axis_start(extra, start):
    columns, result = monthly(3)
    result.rows = [[row[0], 100 + i] for i, row in enumerate(result.rows)]
    check = check_spec(LINE + extra, columns, result)
    assert check.ok
    assert any(start in c.message for c in check.compromises)


def test_c12_invalid_crop_has_no_accepted_crop_compromise():
    check = check_spec(LINE + "zero false\n", *monthly())
    assert any(v.rule == "C12" for v in check.violations)
    assert check.compromises == []


def test_c17_percent_unit_on_measure_is_a_compromise():
    check = check_spec(COLUMN + "format 0.0%\n", *cities())
    assert check.ok
    assert any(c.key == "format" and "share" in c.message for c in check.compromises)
    text = COLUMN.replace("city", "label").replace("violations", "share") + "format 0.0%\n"
    assert check_spec(text, *gender_share()).compromises == []
