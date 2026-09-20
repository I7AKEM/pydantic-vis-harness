import pytest
from pydantic import ValidationError

from vis_agent.designer.models import NumberFormat, Spec, SpecError
from vis_agent.designer.syntax import parse, parse_format, to_text

DONUT = """vis donut
title نسبة المواطنين الأثرياء حسب الجنس
description حلقة تُظهر نسبة الأثرياء لكل جنس
language ar
bind
  category الجنس
  value النسبة
sort value desc
"""


def test_parses_the_worked_example():
    spec = parse(DONUT)
    assert spec.type == "donut"
    assert spec.title == "نسبة المواطنين الأثرياء حسب الجنس"
    assert spec.language == "ar"
    assert spec.bind == {"category": "الجنس", "value": "النسبة"}
    assert spec.sort == "value desc"
    assert spec.inner_radius is None and spec.width is None


def test_colon_separator_and_values_with_spaces_and_colons():
    spec = parse("vis column\ntitle: Sales: quarterly report\naxisYTitle Amount (SAR)\n")
    assert spec.title == "Sales: quarterly report"
    assert spec.axis_y_title == "Amount (SAR)"


def test_values_are_typed_by_key_not_by_look():
    spec = parse("vis column\ntitle 2025\nwidth 1200\ninnerRadius 0.6\nlimit 10\nzero false\npercent true\n"
                 "bind\n  category 001\n  value n\n")
    assert spec.title == "2025" and spec.width == 1200 and spec.inner_radius == 0.6
    assert spec.limit == 10 and spec.zero is False and spec.percent is True
    assert spec.bind["category"] == "001"


@pytest.mark.parametrize("ratio", [0, 0.4, 0.6, 1])
def test_inner_radius_is_an_unscaled_renderer_api_ratio(ratio):
    spec = parse(f"vis donut\ninnerRadius {ratio}\n")
    assert spec.inner_radius == ratio
    assert parse(to_text(spec)).inner_radius == ratio


@pytest.mark.parametrize("value", ["60", "65", "-0.1", "1.01", "nan", "inf", "-inf"])
def test_inner_radius_rejects_wrong_units_and_nonfinite_values_at_their_source_line(value):
    with pytest.raises(SpecError) as error:
        parse(f"vis donut\ntitle Counts\ninnerRadius {value}\n")
    assert len(error.value.issues) == 1
    issue = error.value.issues[0]
    assert issue.line == 3
    assert "innerRadius must be a finite ratio from 0 to 1 inclusive" in issue.message
    assert "0.6" in issue.message and "values are not rescaled" in issue.message
    with pytest.raises(ValidationError):
        Spec(type="donut", inner_radius=float(value))


def test_sections_and_lists():
    spec = parse("vis column\nemphasis\n  - جدة\n  - الرياض\npalette\n  - #1783FF\n  - #00C9C9\n"
                 "style\n  backgroundColor #FFFFFF\n")
    assert spec.emphasis == ["جدة", "الرياض"]
    assert spec.background_color == "#FFFFFF"
    # style.palette and the top-level palette are the same key; the last one written wins is NOT allowed:
    # writing both is a duplicate key error, so this test uses a separate parse for the style form.


def test_style_palette_is_the_palette():
    spec = parse("vis column\nstyle\n  palette\n    - #FF0000\n")
    assert spec.palette == ["#FF0000"]
    with pytest.raises(SpecError) as error:
        parse("vis column\npalette\n  - #FF0000\nstyle\n  palette\n    - #00FF00\n")
    assert "duplicate" in str(error.value)


@pytest.mark.parametrize("quoted", ['"#2E5BFF"', "'#2E5BFF'"])
def test_palette_canonicalizes_model_generated_quotes_around_valid_hex(quoted):
    spec = parse(f"vis column\npalette\n  - {quoted}\n")
    assert spec.palette == ["#2E5BFF"]
    assert to_text(spec) == "vis column\npalette\n  - #2E5BFF\n"


def test_palette_preserves_quotes_on_non_hex_data_for_validation():
    assert parse('vis column\npalette\n  - "blue"\n').palette == ['"blue"']


@pytest.mark.parametrize("text, line, fragment", [
    ("title x\n", 1, "vis"),                                  # missing type line
    ("vis funnel\n", 1, "unknown chart type"),
    ("vis column\nbogus 1\n", 2, "unknown key"),
    ("vis column\ntitle a\ntitle b\n", 3, "duplicate"),
    ("vis column\n\ttitle a\n", 2, "tab"),
    ("vis column\nbind\n   category x\n", 3, "two spaces"),
    ("vis column\nwidth wide\n", 2, "integer"),
    ("vis column\ntheme neon\n", 2, "one of"),
    ("vis column\ntitle\n", 2, "missing value"),
    ("vis column\nbind x\n", 2, "section"),
    ("vis column\ntitle a\n  more\n", 3, "indent"),
    ("vis column\nbind\n  slice x\n", 3, "role"),
    ("vis column\nemphasis\n  جدة\n", 3, "- "),
    ("vis column\nformat 0..0\n", 2, "format"),
])
def test_errors_carry_line_numbers(text, line, fragment):
    with pytest.raises(SpecError) as error:
        parse(text)
    assert any(issue.line == line and fragment in issue.message for issue in error.value.issues), error.value.issues


def test_all_errors_are_reported_together():
    with pytest.raises(SpecError) as error:
        parse("vis column\nbogus 1\nwidth wide\n")
    assert [issue.line for issue in error.value.issues] == [2, 3]


def test_round_trip_is_canonical():
    text = to_text(parse(DONUT))
    assert text.startswith("vis donut\ntitle نسبة")
    assert parse(text) == parse(DONUT)
    assert to_text(parse(text)) == text
    assert "\n\n" not in text and not text.endswith("\n\n")


def test_fold_round_trip_follows_bind():
    text = ("vis multi_line\ntitle T\ndescription D\nbind\n  time month\nfold\n"
            "  - injuries\n  - deaths\n")
    spec = parse(text)
    assert spec.fold == ["injuries", "deaths"]
    assert to_text(spec) == text


def test_serializer_writes_every_key_in_fixed_order():
    spec = Spec(type="line", title="t", bind={"time": "month", "value": "n"}, zero=False, axis_y_min=80,
                format="0,0 SAR", labels="off", palette=["#000000"], emphasis=["a"])
    text = to_text(spec)
    assert text.index("title t") < text.index("bind\n") < text.index("emphasis\n") < text.index("palette\n")
    assert text.index("zero false") < text.index("axisYMin 80") < text.index("labels off") < text.index("format 0,0 SAR")
    assert parse(text) == spec


@pytest.mark.parametrize("pattern, expected", [
    ("0", NumberFormat(thousands=False)),
    ("0,0", NumberFormat(thousands=True)),
    ("0.0", NumberFormat(thousands=False, decimals=1)),
    ("0,0.00 SAR", NumberFormat(thousands=True, decimals=2, unit="SAR")),
    ("0.0%", NumberFormat(thousands=False, decimals=1, unit="%")),
    ("0k", NumberFormat(thousands=False, compact=True)),
    ("0,0.0k ريال", NumberFormat(thousands=True, decimals=1, compact=True, unit="ريال")),
])
def test_format_patterns(pattern, expected):
    assert parse_format(pattern) == expected


@pytest.mark.parametrize("pattern", ["", "1,000", "0,", "0.", "%", "k", "0 ", "0,0,0"])
def test_bad_format_patterns(pattern):
    with pytest.raises(ValueError):
        parse_format(pattern)


def test_indicator_round_trip_keeps_card_order_and_unicode_column_names():
    text = ("vis indicator\ntitle Summary\ndescription Reported totals\ncards\n"
            "  - value Gross amount (SAR)\n    context السنة الهجرية\n    context store: name\n"
            "    support invoice count\n    support net-value\n    format 0,0.00 SAR\n"
            "  - value net-value\n    context السنة الهجرية\n")
    spec = parse(text)
    assert spec.bind == {}
    assert [card.value for card in spec.cards] == ["Gross amount (SAR)", "net-value"]
    assert spec.cards[0].context == ["السنة الهجرية", "store: name"]
    assert spec.cards[0].support == ["invoice count", "net-value"]
    assert parse(to_text(spec)) == spec
    assert to_text(parse(to_text(spec))) == to_text(spec)


@pytest.mark.parametrize("body,line,fragment", [
    ("  value total", 3, "starts"),
    ("  - value", 3, "starts"),
    ("  - support total", 3, "starts"),
    ("    support count", 3, "start a card"),
    ("  - value total\n    value other", 4, "duplicate card value"),
    ("  - value total\n    formula sum(x)", 4, "unknown card field"),
    ("  - value total\n    context", 4, "missing value"),
    ("  - value total\n    format 0.0\n    format 0.00", 5, "duplicate card format"),
    ("  - value total\n    format 0..0", 4, "format pattern"),
    ("  - value total\n  support count", 4, "starts"),
    ("  - value total\n      support count", 4, "indentation"),
])
def test_indicator_syntax_errors_keep_source_lines(body, line, fragment):
    with pytest.raises(SpecError) as error:
        parse("vis indicator\ncards\n" + body + "\n")
    assert any(issue.line == line and fragment in issue.message for issue in error.value.issues)


def test_indicator_column_labels_round_trip_preserves_json_strings_and_column_names():
    spec = Spec(type="indicator", column_labels={"Gross amount (SAR)": "الإيراد الإجمالي", 'store "name"': 'اسم "المتجر"'})
    text = to_text(spec)
    assert '\ncolumnLabels\n  - ["Gross amount (SAR)", "الإيراد الإجمالي"]\n' in text
    assert parse(text) == spec
    assert to_text(parse(text)) == text


@pytest.mark.parametrize("record,fragment", [
    ('["total", "الإجمالي"]', "JSON pair"),
    ('- ["total"]', "JSON pair"),
    ('- ["total", "الإجمالي", "extra"]', "JSON pair"),
    ('- {"total": "الإجمالي"}', "JSON pair"),
    ('- ["total", 100]', "JSON pair"),
    ('- ["total", ""]', "JSON pair"),
    ('- ["total", "   "]', "JSON pair"),
    ('- ["total", "الإجمالي"', "JSON pair"),
])
def test_invalid_column_label_records_have_line_numbers(record, fragment):
    with pytest.raises(SpecError) as error:
        parse("vis indicator\ncolumnLabels\n  " + record + "\n")
    assert error.value.issues[0].line == 3
    assert "columnLabels records" in error.value.issues[0].message


def test_duplicate_column_label_is_not_last_value_wins():
    with pytest.raises(SpecError) as error:
        parse('vis indicator\ncolumnLabels\n  - ["total", "Total"]\n  - ["total", "Changed"]\n')
    assert error.value.issues[0].line == 4 and "duplicate column label" in error.value.issues[0].message


def test_value_labels_round_trip_preserves_column_scope_and_original_keys():
    spec = Spec(type="bar", column_labels={"gender": "الجنس", "marital_status": "الحالة الاجتماعية"},
                value_labels={"gender": {"M": "ذكور", "F": "إناث"},
                              "marital_status": {"M": "متزوج"},
                              'store "code"': {"001": 'متجر "أول"', " A ": "الفرع أ"}})
    text = to_text(spec)
    assert 'valueLabels\n  - ["gender", "M", "ذكور"]\n' in text
    assert parse(text) == spec
    assert to_text(parse(text)) == text
    assert parse(text).value_labels['store "code"']["001"] == 'متجر "أول"'
    assert " A " in parse(text).value_labels['store "code"']


@pytest.mark.parametrize("record", [
    '- ["gender", "M"]', '- ["gender", "M", "Male", "extra"]',
    '- ["gender", 1, "Male"]', '- ["gender", null, "Unknown"]',
    '- ["", "M", "Male"]', '- ["gender", "M", " "]',
    '["gender", "M", "Male"]', '- not-json',
])
def test_malformed_value_labels_have_the_source_line(record):
    with pytest.raises(SpecError) as error:
        parse("vis table\nvalueLabels\n  " + record + "\n")
    assert error.value.issues[0].line == 3
    assert "valueLabels records" in error.value.issues[0].message


def test_value_labels_reject_duplicate_column_value_pairs_only():
    text = ('vis table\nvalueLabels\n  - ["gender", "M", "Male"]\n'
            '  - ["status", "M", "Married"]\n')
    assert parse(text).value_labels == {"gender": {"M": "Male"}, "status": {"M": "Married"}}
    with pytest.raises(SpecError) as error:
        parse(text + '  - ["gender", "M", "Different"]\n')
    assert error.value.issues[0].line == 5
    assert "duplicate value label" in error.value.issues[0].message
