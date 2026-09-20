"""Indicator checks enforce fidelity independently of the designer's chart choice."""

from itertools import permutations

import pytest

from vis_agent.designer.check import check_spec
from vis_agent.designer.models import IndicatorCard, Spec
from vis_agent.designer.recommend import recommend_charts
from vis_agent.designer.syntax import to_text

from .conftest import column, single_number, table


def card_spec(*cards, **options):
    return to_text(Spec(type="indicator", title="Summary", description="Reported measurements",
                        cards=[IndicatorCard(**card) for card in cards], **options))


@pytest.mark.parametrize("value", [0, -5, 0.000539399, 2**63 + 1, None])
def test_real_zero_null_small_negative_and_large_values_are_valid(value):
    columns = [column("total", "measure")]
    checked = check_spec(card_spec({"value": "total"}), columns, table(columns, [[value]]))
    assert checked.ok, checked.violations
    assert checked.canonical


@pytest.mark.parametrize("value", [True, False, "10", "NaN", float("inf"), float("-inf"), float("nan")])
def test_invalid_numeric_cells_are_not_promoted_to_indicators(value):
    columns = [column("total", "measure")]
    result = table(columns, [[value]])
    checked = check_spec(card_spec({"value": "total"}), columns, result)
    assert not checked.ok
    assert any(violation.rule == "I1" for violation in checked.violations)
    assert "indicator" not in {c.name for c in recommend_charts(columns, result, intent="summary").candidates}


@pytest.mark.parametrize("count,ok", [(0, False), (1, True), (2, True), (6, True), (7, False)])
def test_number_of_cards_is_bounded_without_truncating(count, ok):
    columns = [column(f"metric {i}", "measure") for i in range(max(1, count))]
    checked = check_spec(card_spec(*[{"value": c.name} for c in columns[:count]]),
                         columns, table(columns, [list(range(len(columns)))]))
    assert checked.ok is ok
    if ok:
        assert checked.canonical.count("  - value ") == count


@pytest.mark.parametrize("rows,declared", [([], 0), ([[1], [2]], 2), ([[1]], 100), ([[1], [2]], 1), ([[1]], 0)])
def test_indicator_requires_actual_and_declared_single_row(rows, declared):
    columns = [column("total", "measure")]
    result = table(columns, rows)
    result.row_count = declared
    checked = check_spec(card_spec({"value": "total"}), columns, result)
    assert not checked.ok
    assert any("one complete result row" in v.message for v in checked.violations)


@pytest.mark.parametrize("mutation", ["missing cell", "extra cell", "duplicate result", "duplicate metadata", "wrong column"])
def test_malformed_result_metadata_is_a_check_violation(mutation):
    columns = [column("total", "measure"), column("city", "category")]
    result = table(columns, [[10, "Riyadh"]])
    if mutation == "missing cell":
        result.rows[0].pop()
    elif mutation == "extra cell":
        result.rows[0].append(3)
    elif mutation == "duplicate result":
        result.columns[1] = "total"
    elif mutation == "duplicate metadata":
        columns[1].name = "total"
    else:
        result.columns[1] = "other"
    checked = check_spec(card_spec({"value": "total", "context": ["city"]}), columns, result)
    assert not checked.ok
    assert any(v.rule == "I1" for v in checked.violations)


def test_all_scope_is_retained_even_when_single_row_labels_look_like_aliases():
    columns = [column("count", "measure"), column("entity", "category"), column("location", "geography"),
               column("period", "time"), column("id", "identifier"), column("level", "ordinal")]
    result = table(columns, [[4, "Al Baik", "Riyadh", "١٤٤٧-٠١", "001", "High"]])
    complete = {"value": "count", "context": [c.name for c in columns[1:]]}
    assert check_spec(card_spec(complete), columns, result).ok
    omitted = {"value": "count", "context": ["entity", "period"]}
    checked = check_spec(card_spec(omitted), columns, result)
    assert any("unbound: location, id, level" in v.message for v in checked.violations)
    recommendation = next(c for c in recommend_charts(columns, result, intent="summary").candidates if c.name == "indicator")
    assert recommendation.cards[0].context == complete["context"]


@pytest.mark.parametrize("cards", [
    [{"value": "total"}, {"value": "total", "context": ["city"]}],
    [{"value": "total", "context": ["city", "city"]}],
    [{"value": "total", "context": ["city"], "support": ["total"]}],
    [{"value": "total", "context": ["city"], "support": ["other", "other"]}],
    [{"value": "total", "context": ["total", "city"]}],
])
def test_duplicate_and_overlapping_card_bindings_are_rejected(cards):
    columns = [column("total", "measure"), column("city", "category"), column("other", "measure")]
    checked = check_spec(card_spec(*cards), columns, table(columns, [[4, "Riyadh", 6]]))
    assert not checked.ok
    assert any(v.rule == "I2" and "repeat" in v.message for v in checked.violations)


def test_context_can_be_shared_and_a_primary_can_support_another_card():
    columns = [column("total", "measure"), column("city", "category"), column("other", "measure")]
    text = card_spec({"value": "total", "context": ["city"], "support": ["other"]},
                     {"value": "other", "context": ["city"]})
    assert check_spec(text, columns, table(columns, [[4, "Riyadh", 6]])).ok


def test_numeric_indicator_context_failure_points_to_support_or_primary_role():
    columns = [column("percentage", "share", unit="%", denominator="all"),
               column("graduate_count", "measure"), column("total_count", "measure")]
    result = table(columns, [[26.79, 80380, 300075]])
    invalid = check_spec(card_spec({"value": "percentage", "context": ["total_count"],
                                    "support": ["graduate_count"]}), columns, result)
    issue = next(item for item in invalid.violations if "context column 'total_count'" in item.message)
    assert "support" in issue.fix and "another card's value" in issue.fix
    valid = card_spec({"value": "percentage", "support": ["graduate_count"], "format": "0.00%"},
                      {"value": "total_count", "format": "0,0"})
    assert check_spec(valid, columns, result).ok


@pytest.mark.parametrize("primary", ["100", "sum(total)", "total * 100", "missing"])
def test_literal_and_formula_primaries_cannot_invent_numbers(primary):
    checked = check_spec(card_spec({"value": primary}), *single_number())
    assert any(v.rule == "I2" and "does not exist" in v.message for v in checked.violations)


@pytest.mark.parametrize("primary,context,support", [("city", [], ["total"]), ("total", [], ["city"]), ("total", ["total", "city"], [])])
def test_card_roles_enforce_metadata_kinds(primary, context, support):
    columns = [column("total", "measure"), column("city", "identifier")]
    checked = check_spec(card_spec({"value": primary, "context": context, "support": support}),
                         columns, table(columns, [[4, "001"]]))
    assert not checked.ok
    assert any("has kind" in v.message for v in checked.violations)


@pytest.mark.parametrize("key", ["axisXTitle Count", "axisYTitle Count", "sort none", "limit 1", "other Other",
                                   "unknown Unknown", "percent false", "legend off", "labels on", "zero true",
                                   "axisYScale linear", "format 0.0", "innerRadius 0.5", "binNumber 2"])
def test_indicator_rejects_axis_and_transform_options_even_explicit_defaults(key):
    checked = check_spec(card_spec({"value": "total"}) + key + "\n", *single_number())
    assert any(v.rule == "C3" and key.split()[0] in v.message for v in checked.violations)


@pytest.mark.parametrize("section", ["fold\n", "fold\n  - total\n  - other\n"])
def test_indicator_rejects_fold_without_reshaping_its_single_result_row(section):
    columns = [column("total", "measure"), column("other", "measure")]
    result = table(columns, [[18, 4]])
    checked = check_spec(card_spec({"value": "total"}, {"value": "other"}) + section, columns, result)
    assert any(v.rule == "C3" and "fold" in v.message for v in checked.violations)
    assert result.rows == [[18, 4]]


def test_ordinary_charts_reject_cards_including_empty_section():
    for cards in ("cards\n", "cards\n  - value total\n"):
        checked = check_spec("vis table\ntitle Total\ndescription Reported total\n" + cards, *single_number())
        assert any(v.rule == "C3" and "cards" in v.message for v in checked.violations)


@pytest.mark.parametrize("section", ['columnLabels\n', 'columnLabels\n  - ["total", "الإجمالي"]\n'])
def test_ordinary_charts_accept_column_labels_including_empty_section(section):
    checked = check_spec("vis table\ntitle Total\ndescription Total\n" + section, *single_number())
    assert checked.ok, checked.violations


def test_label_translations_require_exact_existing_columns():
    columns = [column("total", "measure"), column("city", "category"), column("count", "measure")]
    result = table(columns, [[100, "Riyadh", 5]])
    spec = card_spec({"value": "total", "context": ["city"], "support": ["count"]},
                     column_labels={"total": "الإجمالي", "city": "المدينة", "count": "العدد"})
    assert check_spec(spec, columns, result).ok
    unknown = spec + '  - ["absent", "غير موجود"]\n'
    assert any(v.rule == "label_binding" for v in check_spec(unknown, columns, result).violations)
    unbound = card_spec({"value": "total"}, column_labels={"city": "المدينة"})
    assert not any(v.rule == "label_binding" for v in check_spec(unbound, columns, result).violations)


@pytest.mark.parametrize("unit,pattern,ok", [("%", "0.0%", True), ("%", "0.000", True),
                                          ("SAR", "0,0 SAR", True), ("SAR", "0,0 USD", False),
                                          ("percentage", "0.00%", True), ("percent", "0.00%", True),
                                          ("percentage points", "0.00%", False), ("fraction", "0.00%", False),
                                          (None, "0.0%", False)])
def test_per_card_format_preserves_units_and_does_not_guess_percent_scale(unit, pattern, ok):
    columns = [column("change", "measure", unit=unit)]
    checked = check_spec(card_spec({"value": "change", "format": pattern}), columns, table(columns, [[-150.5]]))
    assert checked.ok is ok
    if ok:
        assert not checked.compromises


def test_explicit_percentage_column_name_allows_percent_display_without_rescaling():
    from vis_agent.designer.indicator_text import resolve_cards
    from vis_agent.designer.syntax import parse

    columns = [column("percentage_saudi", "measure")]
    result = table(columns, [[100.0]])
    checked = check_spec(card_spec({"value": "percentage_saudi", "format": "0.0%"}),
                         columns, result)
    assert checked.ok, checked.violations
    assert "format 0.0%" in checked.canonical
    resolved = resolve_cards(parse(checked.canonical), columns, result)[0]["value"]
    assert resolved["display"] == "100.0%" and resolved["unitLabel"] == "%"


def test_missing_share_basis_is_disclosed_without_rescaling():
    columns = [column("share", "share")]
    checked = check_spec(card_spec({"value": "share"}), columns, table(columns, [[0.34]]))
    assert checked.ok
    assert any("denominator" in compromise.message for compromise in checked.compromises)


@pytest.mark.parametrize("unit,value,ok", [
    ("%", -20, False), ("%", 120, False), ("%", 0, True), ("%", 100, True), ("%", None, True),
    ("%", -1e-8, True), ("%", 100 + 1e-8, True), ("%", 100 + 1e-5, False),
    ("percentage", 108.86, False), ("percentage", 40, True), ("percent", -20, False),
    ("نسبة مئوية", 108.86, False),
    ("fraction", -.2, False), ("fraction", 1.2, False), ("fraction", 0, True), ("fraction", 1, True),
    ("fraction", None, True), ("fraction", 1 + 1e-10, True), ("fraction", 1 + 1e-6, False),
    (None, 120, True), (None, -20, True), ("unknown", 120, True),
])
def test_declared_share_range_is_checked_without_guessing_unknown_scales(unit, value, ok):
    columns = [column("share", "share", unit=unit, denominator="all records")]
    result = table(columns, [[value]])
    checked = check_spec(card_spec({"value": "share"}), columns, result)
    assert checked.ok is ok
    assert any(v.rule == "I6" for v in checked.violations) is not ok
    if not ok:
        issue = next(v for v in checked.violations if v.rule == "I6")
        assert "SQL" in issue.fix and "percentage change" in issue.fix
        assert "indicator" not in {candidate.name for candidate in recommend_charts(columns, result, intent="summary").candidates}


def test_offsetting_out_of_range_parts_cannot_hide_in_supporting_values():
    columns = [column("left", "share", unit="%", denominator="all"),
               column("right", "share", unit="%", denominator="all")]
    result = table(columns, [[-20, 120]])
    checked = check_spec(card_spec({"value": "left", "support": ["right"]}), columns, result)
    assert len([v for v in checked.violations if v.rule == "I6"]) == 2
    for item in columns:
        item.kind = "measure"
    assert check_spec(card_spec({"value": "left"}, {"value": "right"}), columns, result).ok


@pytest.mark.parametrize("options,ok", [({"palette": ["#000000"]}, True), ({"palette": ["#000000", "#FFFFFF"]}, False),
                                      ({"palette": ["red"]}, False), ({"palette": ["#FFFFFF"]}, False),
                                      ({"width": 240}, True), ({"width": 239}, False), ({"height": 159}, False),
                                      ({"height": 2401}, False), ({"background_color": "white"}, False)])
def test_indicator_style_is_explicit_and_bounded(options, ok):
    assert check_spec(card_spec({"value": "total"}, **options), *single_number()).ok is ok


@pytest.mark.parametrize("theme,background,accent", [("default", "#000000", "#FFFFFF"),
                                                      ("academy", "#000000", "#FFFFFF"),
                                                      ("dark", "#FFFFFF", "#202938")])
def test_accent_must_contrast_with_card_surface_as_well_as_outer_background(theme, background, accent):
    checked = check_spec(card_spec({"value": "total"}, theme=theme, background_color=background, palette=[accent]),
                         *single_number())
    assert any(v.rule == "C7" and "card surface" in v.message for v in checked.violations)


def test_summary_intent_prefers_indicator_but_unknown_intent_keeps_table():
    assert recommend_charts(*single_number(), intent="summary").candidates[0].name == "indicator"
    assert recommend_charts(*single_number()).candidates[0].name == "table"
    assert recommend_charts(*single_number(), suggested="table").candidates[0].name == "table"
    assert recommend_charts(*single_number(), intent="trend", suggested="indicator").candidates[0].name != "indicator"


def test_wide_result_does_not_override_requested_breakdown_intent():
    columns = [column("total", "measure", aggregate="sum"), column("hardware", "measure", aggregate="sum"),
               column("software", "measure", aggregate="sum")]
    result = table(columns, [[900, 300, 600]])
    breakdown = recommend_charts(columns, result, intent="composition", suggested="indicator")
    assert breakdown.candidates[0].name == "table"
    headlines = recommend_charts(columns, result, intent="summary")
    assert headlines.candidates[0].name == "indicator"
    assert headlines.candidates[0].cards == []  # The question must still determine primary/support roles.


@pytest.mark.parametrize("intent,ok", [("compare", False), ("trend", False), ("composition", False),
                                       ("distribution", False), ("summary", True), ("share", True),
                                       ("rank", True), (None, True)])
def test_indicator_obeys_existing_selected_intent_without_inventing_one(intent, ok):
    checked = check_spec(card_spec({"value": "total"}), *single_number(), intent=intent)
    assert checked.ok is ok
    assert any(issue.rule == "I7" for issue in checked.violations) is not ok
    assert check_spec("vis table\ntitle Total\ndescription Reported total\n", *single_number(), intent=intent).ok


def test_multiple_metrics_never_receive_first_column_primary_guess():
    definitions = [column("discounted", "measure"), column("total", "measure"),
                   column("share", "share", unit="%", denominator="all violations")]
    values = {"discounted": 480, "total": 1000, "share": 48}
    for columns in permutations(definitions):
        columns = list(columns)
        result = table(columns, [[values[c.name] for c in columns]])
        choice = next(c for c in recommend_charts(columns, result, intent="summary").candidates if c.name == "indicator")
        assert choice.cards == [] and choice.binding == {}
        assert any("question" in score.explanation for score in choice.breakdown)
        assert check_spec(card_spec({"value": "share", "support": ["discounted", "total"]}), columns, result).ok
