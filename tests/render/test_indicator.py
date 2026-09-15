"""The card renderer paints the exact resolved text and saves a portable page."""

import json
import math
import subprocess

import pytest

from tests.designer.conftest import column, table
from vis_agent.designer.models import IndicatorCard, Spec
from vis_agent.render import gptvis
from vis_agent.render.base import RenderFailed

pytestmark = pytest.mark.skipif(gptvis.available() is not None, reason=gptvis.available() or "")


def card_spec(**kwargs):
    return Spec(type="indicator", title="Key measurements", description="Measurements for the selected scope",
                cards=[IndicatorCard(value="value")], **kwargs)


def assert_drawn_bounds(rendered):
    assert rendered.text_bounds
    for bound in rendered.text_bounds:
        assert bound["text"] in rendered.texts
        assert bound["paintedText"].replace("\u202d", "").replace("\u202c", "") == bound["text"]
        assert bound["width"] > 0 and bound["height"] > 0
        assert 0 <= bound["x"] < bound["x"] + bound["width"] <= rendered.width
        assert 0 <= bound["y"] < bound["y"] + bound["height"] <= rendered.height
    config = json.loads(rendered.config.read_text())
    assert config["textBounds"] == rendered.text_bounds
    for bound in rendered.text_bounds:
        if bound["card"] is not None:
            card = config["cardBounds"][bound["card"]]
            assert card["x"] <= bound["x"] and bound["x"] + bound["width"] <= card["x"] + card["width"]
            assert card["y"] <= bound["y"] and bound["y"] + bound["height"] <= card["y"] + card["height"]


@pytest.mark.parametrize("value,expected", [(0, "0"), (None, "Unavailable"),
                                          (9007199254740993, "9,007,199,254,740,993"),
                                          (1e-100, "1e-100"), (-1e-100, "-1e-100")])
def test_indicator_paints_exact_numeric_state_without_js_number_conversion(value, expected, tmp_path):
    columns = [column("value", "measure")]
    rendered = gptvis.render(card_spec(), columns, table(columns, [[value]]), tmp_path)
    assert expected in rendered.texts  # Indicators keep actual draw evidence even without trace=True.
    value_bounds = [b for b in rendered.text_bounds if b["role"] == "value"]
    assert [b["text"] for b in value_bounds] == [expected]
    assert rendered.drawn_rows == 1 and rendered.dropped_rows == 0
    assert_drawn_bounds(rendered)


def test_indicator_arabic_hijri_scope_primary_and_support_are_drawn(tmp_path):
    columns = [column("rate", "share", unit="%"), column("count", "measure"), column("period", "time")]
    columns[0].meaning, columns[1].meaning, columns[2].meaning = "نسبة المخالفات", "عدد المخالفات", "الفترة"
    result = table(columns, [[0.0005393990555122537, 2, "١٤٤٧-٠٩"]])
    spec = Spec(type="indicator", language="ar", digits="arabic", theme="dark", title="المخالفات المسجلة",
                description="نسبة المخالفات في الفترة المحددة", cards=[IndicatorCard(value="rate", support=["count"], context=["period"])])
    rendered = gptvis.render(spec, columns, result, tmp_path)
    assert {"٠٫٠٠٠٥٣٩٤", "٠٫٠٠٠٥٣٩٣٩٩٠٥٥٥١٢٢٥٣٧", "%", "٢", "الفترة", "١٤٤٧-٠٩"} <= set(rendered.texts)
    assert 'dir="rtl"' in rendered.html.read_text()
    assert '<bdi dir="ltr" style="unicode-bidi: bidi-override">١٤٤٧-٠٩</bdi>' in rendered.html.read_text()
    date = next(b for b in rendered.text_bounds if b["role"] == "context")
    assert date["paintedText"] == "\u202d١٤٤٧-٠٩\u202c"
    assert_drawn_bounds(rendered)


@pytest.mark.parametrize("count", [1, 2, 6])
def test_indicator_grid_retains_all_cards_and_mixed_units(count, tmp_path):
    columns = [column(f"metric {i}", "measure", unit="SAR" if i % 2 else "%") for i in range(count)]
    spec = Spec(type="indicator", title="Measurements", description="Several independent measurements",
                cards=[IndicatorCard(value=c.name) for c in columns])
    rendered = gptvis.render(spec, columns, table(columns, [[None if i == 1 else (i + 1) * 10 for i in range(count)]]), tmp_path)
    values = [bound for bound in rendered.text_bounds if bound["role"] == "value"]
    assert len(values) == count
    assert [v["column"] for v in values] == [c.name for c in columns]
    assert values[0]["text"] == "10"
    assert next(b for b in rendered.text_bounds if b["role"] == "unit")["text"] == "%"
    if count > 1:
        assert values[1]["text"] == "Unavailable"
        assert any(b["role"] == "unit" and b["card"] == 1 and b["text"] == "SAR" for b in rendered.text_bounds)
    assert_drawn_bounds(rendered)


def test_indicator_wraps_labels_and_expands_default_height(tmp_path):
    columns = [column("value", "measure")]
    columns[0].meaning = "A long metric label that identifies the complete measure and its reporting scope " * 4
    spec = card_spec(width=360)
    rendered = gptvis.render(spec, columns, table(columns, [[12]]), tmp_path)
    labels = [bound for bound in rendered.text_bounds if bound["role"] == "label"]
    assert len(labels) > 6 and rendered.height > 340 * 3
    assert_drawn_bounds(rendered)


@pytest.mark.parametrize("kwargs,value", [({"height": 160}, 123), ({"width": 240}, 10 ** 100)])
def test_indicator_fails_instead_of_clipping_a_metric(kwargs, value, tmp_path):
    columns = [column("value", "measure")]
    with pytest.raises(RenderFailed, match="legib|height"):
        gptvis.render(card_spec(**kwargs), columns, table(columns, [[value]]), tmp_path)


def test_indicator_page_escapes_every_field_and_has_no_script_or_remote_dependency(tmp_path):
    columns = [column("value", "measure"), column("context", "category")]
    columns[0].meaning = '<img src=x onerror="alert(1)">'
    spec = Spec(type="indicator", title='<script>alert(1)</script>{{g2}}', description='A < B',
                cards=[IndicatorCard(value="value", context=["context"], format="0.00")])
    rendered = gptvis.render(spec, columns, table(columns, [[0.0005, '<script>bad()</script>']]), tmp_path)
    page = rendered.html.read_text()
    assert '<script' not in page.lower() and '@antv' not in page and 'new G2' not in page
    assert '&lt;script&gt;bad()&lt;/script&gt;' in page and '&lt;img src=x' in page
    assert '<dl>' in page and '<dt>' in page and '<dd class="primary" data-state="available">' in page
    assert '<bdi dir="ltr" style="unicode-bidi: bidi-override">0.00</bdi>' in page
    assert '<small><bdi dir="ltr" style="unicode-bidi: bidi-override">0.0005</bdi>' in page
    assert '{{g2}}' in page and 'data:image/png;base64,' in page
    assert '0.00' in rendered.texts and '0.0005' in rendered.texts
    assert_drawn_bounds(rendered)


def test_rtl_scientific_numbers_paint_a_leading_minus_before_the_numeric_run(tmp_path):
    """Pixel evidence: negation adds a short dash at the numeric run's left.

    Raw RTL Arabic numbers used to put the minus after the value and rearrange
    the exponent. Text-echo and bounding-box checks alone did not catch that.
    """
    columns = [column("value", "measure", unit="%"), column("support", "measure", unit="%")]
    spec = Spec(type="indicator", title="القياسات", description="تغير القياسات", language="ar", digits="arabic",
                cards=[IndicatorCard(value="value", support=["support"])])
    renders = [gptvis.render(spec, columns, table(columns, [[sign * 1.23456789e-9, sign * 42.345]]),
                            tmp_path / str(sign)) for sign in (1, -1)]
    positive, negative = renders
    assert (positive.width, positive.height) == (negative.width, negative.height)
    boxes = []
    for pos, neg in zip([b for b in positive.text_bounds if b["role"] in {"value", "support", "exact"}],
                        [b for b in negative.text_bounds if b["role"] in {"value", "support", "exact"}]):
        assert neg["paintedText"] == "\u202d-" + pos["text"] + "\u202c"
        box = (math.floor(neg["x"]), math.floor(neg["y"]), math.ceil(pos["x"]),
               math.ceil(neg["y"] + neg["height"]))
        # A trailing-minus bug moves a full-height digit into this added left
        # region; a correct leading minus paints only a short horizontal stroke.
        boxes.append(box)
        assert neg["x"] < pos["x"]
    # Read the actual PNG pixels with the installed renderer dependency; this
    # adds no image library just for the test.
    script = """
const { createCanvas, loadImage } = require(process.argv[1]);
const { path, boxes } = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
loadImage(path).then(image => {
  const context = createCanvas(image.width, image.height).getContext('2d');
  context.drawImage(image, 0, 0);
  console.log(JSON.stringify(boxes.map(([left, top, right, bottom]) => {
    const width = right - left, height = bottom - top;
    const { data } = context.getImageData(left, top, width, height);
    let low = height, high = -1;
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      if (data[(y * width + x) * 4] < 140) { low = Math.min(low, y); high = Math.max(high, y); }
    }
    return high >= low && high - low + 1 <= height * .25;
  })));
});
"""
    process = subprocess.run(["node", "-e", script, str(gptvis.SCRIPT.parent / "node_modules" / "canvas")],
                             input=json.dumps({"path": str(negative.png), "boxes": boxes}),
                             text=True, capture_output=True, check=True, timeout=20)
    assert all(json.loads(process.stdout)), process.stdout
    page = negative.html.read_text()
    assert '<bdi dir="ltr" style="unicode-bidi: bidi-override">-١٫٢٣٤٥٦٨e-٩</bdi>' in page
    assert '<bdi dir="auto" class="metric-unit">%</bdi>' in page
    assert_drawn_bounds(negative)


def test_rtl_numeric_override_excludes_arabic_unit_for_all_metric_roles(tmp_path):
    columns = [column("value", "measure", unit="ريال"), column("support", "measure", unit="ساعة")]
    spec = Spec(type="indicator", title="القياسات", description="قيم بوحدات مختلفة", language="ar", digits="arabic",
                cards=[IndicatorCard(value="value", support=["support"])])
    rendered = gptvis.render(spec, columns, table(columns, [[-1.23456789e-9, -42.345]]), tmp_path)
    metrics = [b for b in rendered.text_bounds if b["role"] in {"value", "support", "exact"}]
    assert len(metrics) == 4
    for bound in metrics:
        assert bound["paintedText"] == f"\u202d{bound['text']}\u202c"
    units = [b for b in rendered.text_bounds if b["role"] in {"unit", "support_unit", "exact_unit"}]
    assert len(units) == 4 and {b["text"] for b in units} == {"ريال", "ساعة"}
    assert all(b["paintedText"] == b["text"] for b in units)
    page = rendered.html.read_text()
    assert '<bdi dir="auto" class="metric-unit">ريال</bdi>' in page
    assert '<bdi dir="auto" class="metric-unit">ساعة</bdi>' in page
    assert_drawn_bounds(rendered)


def test_indicator_renders_translated_labels_without_changing_values(tmp_path):
    columns = [column("value", "measure", unit="%"), column("support", "measure"), column("period", "time")]
    result = table(columns, [[25, 10, "1447-09"]])
    spec = Spec(type="indicator", title="المؤشر", description="المؤشر للفترة المحددة", language="ar",
                column_labels={"value": "النسبة", "support": "العدد", "period": "الفترة"},
                cards=[IndicatorCard(value="value", support=["support"], context=["period"])])
    rendered = gptvis.render(spec, columns, result, tmp_path)
    assert {"النسبة", "العدد", "الفترة", "25", "%", "10", "1447-09"} <= set(rendered.texts)
    assert {"النسبة", "العدد", "الفترة"} == {b["text"] for b in rendered.text_bounds if b["role"] == "label"}
    for label in spec.column_labels.values():
        assert f"<dt>{label}</dt>" in rendered.html.read_text()
    assert_drawn_bounds(rendered)


def test_arabic_population_total_keeps_label_and_localized_unit_in_a_compact_card(tmp_path):
    columns = [column("total_citizens", "measure", unit="person", aggregate="sum")]
    columns[0].meaning, columns[0].source = "إجمالي عدد المواطنين", "citizen_count"
    result = table(columns, [[18]])
    old_columns, old_result = [c.model_copy(deep=True) for c in columns], result.model_copy(deep=True)
    spec = Spec(type="indicator", language="ar", title="إجمالي عدد المواطنين",
                description="إجمالي عدد المواطنين في المدن المدرجة في الملف",
                cards=[IndicatorCard(value="total_citizens")])
    rendered = gptvis.render(spec, columns, result, tmp_path)
    assert [b["text"] for b in rendered.text_bounds if b["role"] == "value"] == ["18"]
    assert rendered.texts.count("إجمالي عدد المواطنين") == 1
    label = next(b for b in rendered.text_bounds if b["role"] == "label")
    value = next(b for b in rendered.text_bounds if b["role"] == "value")
    unit = next(b for b in rendered.text_bounds if b["role"] == "unit")
    assert label["text"] == "إجمالي عدد المواطنين" and label["y"] < value["y"]
    assert unit["text"] == "شخصًا" and unit["height"] < value["height"]
    assert unit["x"] + unit["width"] < value["x"]
    assert not any(b["role"] == "title" for b in rendered.text_bounds)
    assert rendered.width == 460 * 3 and 160 * 3 <= rendered.height <= 240 * 3
    assert not any("person" in text for text in rendered.texts)
    assert '<dt>إجمالي عدد المواطنين</dt>' in rendered.html.read_text()
    assert '<h1>' not in rendered.html.read_text()
    assert json.loads(rendered.config.read_text())["gptvis"]["cards"][0]["value"]["unit"] == "person"
    assert columns == old_columns and result == old_result
    assert_drawn_bounds(rendered)


def test_user_percentage_change_renders_symbol_and_preserves_the_original_report(tmp_path):
    columns = [column("percentage_change", "measure", unit="percentage", aggregate="sum")]
    columns[0].meaning, columns[0].source = "نسبة التغير في المقياس المقاس", "percentage_change"
    result = table(columns, [[108.86]])
    before = [c.model_copy(deep=True) for c in columns], result.model_copy(deep=True)
    spec = Spec(type="indicator", language="ar", title="نسبة التغير",
                description="يوضح الرسم البياني نسبة التغير في المقياس المقاس",
                cards=[IndicatorCard(value="percentage_change")],
                column_labels={"percentage_change": "نسبة التغير"})
    rendered = gptvis.render(spec, columns, result, tmp_path)
    assert [b["text"] for b in rendered.text_bounds if b["role"] == "value"] == ["108.86"]
    assert [b["text"] for b in rendered.text_bounds if b["role"] == "unit"] == ["%"]
    value = next(b for b in rendered.text_bounds if b["role"] == "value")
    unit = next(b for b in rendered.text_bounds if b["role"] == "unit")
    assert value["x"] + value["width"] < unit["x"]
    assert rendered.texts.count("نسبة التغير") == 1
    assert not any("percentage" in text for text in rendered.texts)
    card = json.loads(rendered.config.read_text())["gptvis"]["cards"][0]["value"]
    assert (card["unit"], card["unitLabel"], card["display"]) == ("percentage", "%", "108.86%")
    assert '<bdi dir="auto" class="metric-unit">%</bdi>' in rendered.html.read_text()
    assert '<bdi dir="ltr" class="metric-percent">' in rendered.html.read_text()
    assert (columns, result) == before
    assert_drawn_bounds(rendered)


@pytest.mark.parametrize("title,label", [("Total citizens", "ＴＯＴＡＬ  Citizens"), (" إجمالي عدد المواطنين ", "إجمالي  عدد المواطنين")])
def test_single_indicator_duplicate_label_uses_unicode_whitespace_and_case_normalization(title, label, tmp_path):
    columns = [column("value", "measure")]
    columns[0].meaning = label
    spec = Spec(type="indicator", title=title, description="The reported total", cards=[IndicatorCard(value="value")])
    rendered = gptvis.render(spec, columns, table(columns, [[18]]), tmp_path)
    assert any(b["role"] == "label" for b in rendered.text_bounds)
    assert not any(b["role"] == "title" for b in rendered.text_bounds)
    assert '<h1>' not in rendered.html.read_text()
    assert_drawn_bounds(rendered)


def test_distinct_single_card_and_all_multi_card_labels_remain_visible(tmp_path):
    columns = [column("value", "measure"), column("other", "measure")]
    columns[0].meaning, columns[1].meaning = "Population", "Arrivals"
    single = Spec(type="indicator", title="City overview", description="The total", cards=[IndicatorCard(value="value")])
    rendered = gptvis.render(single, columns[:1], table(columns[:1], [[18]]), tmp_path / "single")
    assert [b["text"] for b in rendered.text_bounds if b["role"] == "label"] == ["Population"]
    multi = Spec(type="indicator", title="Population", description="Two totals", cards=[IndicatorCard(value="value"), IndicatorCard(value="other")])
    rendered = gptvis.render(multi, columns, table(columns, [[18, 4]]), tmp_path / "multi")
    assert [b["text"] for b in rendered.text_bounds if b["role"] == "label"] == ["Population", "Arrivals"]
    assert rendered.texts.count("Population") == 2
    assert '<dt class="visually-hidden">' not in rendered.html.read_text()
    assert_drawn_bounds(rendered)


def test_single_statistic_omits_a_description_that_only_repeats_its_heading(tmp_path):
    heading = "إجمالي عدد المواطنين"
    columns = [column("value", "measure", unit="person")]
    columns[0].meaning = heading
    spec = Spec(type="indicator", language="ar", title=heading, description=heading,
                cards=[IndicatorCard(value="value")])
    rendered = gptvis.render(spec, columns, table(columns, [[18]]), tmp_path)
    assert rendered.texts == [heading, "18", "شخصًا"]
    assert [b["role"] for b in rendered.text_bounds] == ["label", "value", "unit"]
    saved = json.loads(rendered.config.read_text())["gptvis"]
    assert saved["description"] == heading  # Semantic metadata is retained.
    assert f'alt="{heading}"' in rendered.html.read_text()
    assert '<p class="footnote">' not in rendered.html.read_text()
    assert_drawn_bounds(rendered)


@pytest.mark.parametrize("description,visible", [("  ANNUAL   ＯＶＥＲＶＩＥＷ ", False), ("Total for all nine cities", True)])
def test_single_statistic_footnote_dedup_keeps_meaningful_scope(description, visible, tmp_path):
    columns = [column("value", "measure")]
    columns[0].meaning = "Population"
    spec = Spec(type="indicator", title="Annual overview", description=description, cards=[IndicatorCard(value="value")])
    rendered = gptvis.render(spec, columns, table(columns, [[18]]), tmp_path)
    assert bool([b for b in rendered.text_bounds if b["role"] == "description"]) is visible
    assert ('<p class="footnote">' in rendered.html.read_text()) is visible
    assert_drawn_bounds(rendered)
