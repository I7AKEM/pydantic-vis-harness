"""Explicit unit aliases must not guess a measurement's scale."""

import pytest

from vis_agent.units import canonical_unit, display_unit, indicator_unit


@pytest.mark.parametrize("unit", ["%", "percentage", " percent ", "PERCENTAGE", "per  cent", "pct",
                                 "٪", "％", "نسبة مئوية", "النسبة المئوية", "بالمئة", "بالمائة",
                                 "في المئة", "في المائة"])
def test_explicit_percent_aliases_have_one_display_symbol(unit):
    assert canonical_unit(unit) == display_unit(unit) == "%"
    assert indicator_unit(unit, 108.86, "ar") == "%"


@pytest.mark.parametrize("unit", [None, "fraction", "ratio", "percentage points", "percent points",
                                 "pp", "basis points", "نقطة مئوية", "percent/year", "percentage_change",
                                 "SAR", " percent unknown "])
def test_other_scales_and_compound_units_are_not_relabelled_as_percent(unit):
    assert canonical_unit(unit) == display_unit(unit) == indicator_unit(unit, .34, "ar") == unit
