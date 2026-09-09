"""Exercise the installed renderer, including the text actually painted by canvas."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.designer.conftest import (cities, column, gender_share, grouped, monthly,
                                     raw_amounts, scatter_points, table, two_same_unit_measures, two_units)
from vis_agent.designer.catalogue import CATALOGUE
from vis_agent.designer.resolve import resolve
from vis_agent.designer.syntax import parse
from vis_agent.render import gptvis
from vis_agent.render.base import RenderFailed, RendererUnavailable

pytestmark = pytest.mark.skipif(gptvis.available() is not None, reason=gptvis.available() or "")
IMAGES = Path(__file__).with_name("images")


def arabic_cities():
    columns, _ = cities()
    return columns, table(columns, [["الرياض", 1240], ["جدة", 980], ["مكة المكرمة", 610],
                                    ["المدينة المنورة", 455], ["الدمام", 390]])


def grouped_monthly():
    columns, result = monthly(6)
    columns.append(column("group", "category"))
    return columns, table(columns, [[month, value * scale, group]
                                    for month, value in result.rows
                                    for group, scale in [("First", 1), ("Second", 0.7)]])


def distributions():
    columns = [column("city", "category"), column("amount", "measure")]
    return columns, table(columns, [[city, value + offset] for city, offset in [("North", 0), ("South", 30)]
                                    for value in [10, 15, 20, 22, 30, 40, 45, 55]])


def varying_monthly():
    columns, result = monthly()
    for i, row in enumerate(result.rows):
        row[1] = 100 + (i * 73 % 145)
    return columns, result


def scattered():
    columns, _ = scatter_points()
    return columns, table(columns, [[i + 1, (i * 73 % 197) + 1] for i in range(240)])


def radar_groups():
    columns, result = grouped(8)
    for i, row in enumerate(result.rows):
        row[-1] = 10 + (i * 13 % 35)
    return columns, result


def words():
    return cities(40)


SPECS = {
    "column": ("vis column\nlanguage ar\nbind\n  category city\n  value violations", arabic_cities),
    "bar": ("vis bar\nbind\n  category city\n  value violations", cities),
    "grouped_column": ("vis grouped_column\nbind\n  category city\n  group gender\n  value n", grouped),
    "stacked_column": ("vis stacked_column\nbind\n  category city\n  group gender\n  value n", grouped),
    "grouped_bar": ("vis grouped_bar\nbind\n  category city\n  group gender\n  value n", grouped),
    "stacked_bar": ("vis stacked_bar\nbind\n  category city\n  group gender\n  value n", grouped),
    "line": ("vis line\nbind\n  time month\n  value visits", varying_monthly),
    "multi_line": ("vis multi_line\nbind\n  time month\n  group group\n  value visits", grouped_monthly),
    "area": ("vis area\nbind\n  time month\n  value visits", monthly),
    "stacked_area": ("vis stacked_area\nbind\n  time month\n  group group\n  value visits", grouped_monthly),
    "pie": ("vis pie\nbind\n  category label\n  value share", gender_share),
    "donut": ("vis donut\nbind\n  category label\n  value share", gender_share),
    "scatter": ("vis scatter\nbind\n  x age\n  y amount", scattered),
    "histogram": ("vis histogram\nbind\n  value amount", raw_amounts),
    "boxplot": ("vis boxplot\nbind\n  category city\n  value amount", distributions),
    "treemap": ("vis treemap\nbind\n  category city\n  value violations", cities),
    "radar": ("vis radar\nbind\n  category city\n  group gender\n  value n", radar_groups),
    "dual_axes": ("vis dual_axes\nbind\n  category month\n  value visits\n  value2 revenue", two_units),
    "word_cloud": ("vis word_cloud\nbind\n  category city\n  value violations", words),
    "table": ("vis table", gender_share),
}


def keep_image(rendered, name):
    if os.environ.get("VIS_KEEP_IMAGES"):
        shutil.copyfile(rendered.png, IMAGES / f"{name}.png")


@pytest.mark.parametrize("entry", CATALOGUE.entries, ids=lambda e: e.name)
def test_every_catalogue_entry_renders(entry, tmp_path):
    text, builder = SPECS[entry.name]
    spec = parse(text + f"\ntitle Example {entry.name}\nwidth 800\nheight 450")
    rendered = gptvis.render(spec, *builder(), tmp_path)
    assert rendered.png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.width == 3 * spec.width if entry.name != "table" else rendered.width > 0
    assert rendered.height == 3 * spec.height if entry.name != "table" else rendered.height > 0
    assert rendered.non_background_share >= 0.02
    assert rendered.config.exists() and rendered.html.exists()
    assert spec.title in rendered.html.read_text()
    assert rendered.seconds > 0 and rendered.drawn_rows > 0
    config = json.loads(rendered.config.read_text())
    assert bool(config["functionPaths"]) == any(c.key == "page" for c in rendered.compromises)
    if entry.name == "table":
        assert "<table>" in rendered.html.read_text()
        assert "const interactive = false" in rendered.html.read_text()
    keep_image(rendered, entry.name)


def test_folded_monthly_measures_render_as_two_lines(tmp_path):
    spec = parse("vis multi_line\ntitle Injuries and deaths\nbind\n  time month\nfold\n"
                 "  - injuries\n  - deaths\n")
    rendered = gptvis.render(spec, *two_same_unit_measures(), tmp_path)
    assert rendered.non_background_share > 0.02
    config = json.loads(rendered.config.read_text())
    assert {row["group"] for row in config["gptvis"]["data"]} == {"injuries", "deaths"}


def test_arabic_text_and_rtl_overrides(tmp_path):
    spec = parse(SPECS["column"][0] + "\ntitle عدد المخالفات حسب المدينة 2025")
    rendered = gptvis.render(spec, *arabic_cities(), tmp_path, trace=True)
    assert "الرياض" in rendered.texts
    assert "1,240" in rendered.texts
    config = json.loads(rendered.config.read_text())
    assert config["g2"]["title"]["align"] == "right"
    assert config["g2"]["scale"]["x"]["domain"] == ["الدمام", "المدينة المنورة", "مكة المكرمة", "جدة", "الرياض"]
    assert config["g2"]["axis"]["y"]["labelFormatter"] == {"$format": "value"}
    assert "dir=\"rtl\"" in rendered.html.read_text()
    keep_image(rendered, "arabic-column")


@pytest.mark.parametrize("option,expected,name", [
    ("format 0,0 ريال", "1,240 ريال", "format-unit"),
    ("format 0k", "1.2K", "format-compact"),
    ("digits arabic", "١٬٢٤٠", "format-arabic-digits"),
])
def test_formats_are_drawn(option, expected, name, tmp_path):
    rendered = gptvis.render(parse(SPECS["column"][0] + "\n" + option), *arabic_cities(), tmp_path, trace=True)
    assert expected in rendered.texts
    keep_image(rendered, name)


@pytest.mark.parametrize("chart", ["column", "donut"])
def test_percent_is_drawn(chart, tmp_path):
    columns, result = gender_share()
    result.rows[0][-1], result.rows[1][-1] = 61.6, 38.4
    spec = parse(f"vis {chart}\nbind\n  category label\n  value share\nformat 0.0%")
    rendered = gptvis.render(spec, columns, result, tmp_path, trace=True)
    assert ("61.6%" if chart == "column" else "Female: 61.6%") in rendered.texts
    config = json.loads(rendered.config.read_text())
    assert config["functionPaths"] == []
    assert "const interactive = true" in rendered.html.read_text()
    keep_image(rendered, f"format-percent-{chart}")


def test_overrides_include_child_labels_and_preserve_title(tmp_path):
    spec = parse(SPECS["line"][0] + "\ntitle Visits\nsubtitle Monthly\naxisYMin 80\nlabels off\nlegend off")
    rendered = gptvis.render(spec, *monthly(), tmp_path)
    options = json.loads(rendered.config.read_text())["g2"]
    assert options["scale"]["y"]["domainMin"] == 80
    assert options["labels"] == [] and options["legend"] is False
    assert all(child.get("labels", []) == [] for child in options["children"])
    assert options["title"]["title"] == "Visits" and options["title"]["subtitle"] == "Monthly"
    keep_image(rendered, "line-overrides")


@pytest.mark.parametrize("chart", ["treemap", "word_cloud"])
def test_scalar_titles_survive_overrides(chart, tmp_path):
    spec = parse(SPECS[chart][0] + "\ntitle Cities\nsubtitle Counts\ndirection rtl")
    rendered = gptvis.render(spec, *cities(), tmp_path, trace=True)
    options = json.loads(rendered.config.read_text())["g2"]
    assert options["title"] == {"title": "Cities", "subtitle": "Counts", "align": "right"}
    assert "Cities" in rendered.texts and "Counts" in rendered.texts


def test_line_child_labels_receive_formatter(tmp_path):
    spec = parse(SPECS["line"][0] + "\nformat 0.0 ريال")
    rendered = gptvis.render(spec, *monthly(), tmp_path, trace=True)
    assert "245.0 ريال" in rendered.texts
    options = json.loads(rendered.config.read_text())["g2"]
    assert options["children"][0]["labels"][0]["formatter"] == {"$format": "value"}


def test_histogram_count_axis_draws_no_measure_unit(tmp_path):
    spec = parse(SPECS["histogram"][0] + "\ntitle Amount distribution")
    rendered = gptvis.render(spec, *raw_amounts(), tmp_path, trace=True)
    assert rendered.texts
    assert not any(text.endswith("SAR") for text in rendered.texts)
    config = json.loads(rendered.config.read_text())
    assert config["number"]["thousands"] is True
    assert config["number"]["unit"] is None
    labels = ["1–6.9", "6.9–12.8", "12.8–18.7", "18.7–24.6", "24.6–30.5",
              "30.5–36.4", "36.4–42.3", "42.3–48.2", "48.2–54.1", "54.1–60"]
    assert config["gptvis"]["type"] == "column"
    assert config["g2"]["type"] == "interval"
    assert config["g2"]["encode"]["x"] == "category"
    assert config["g2"]["encode"]["y"] == "value"
    assert config["g2"]["data"] == [{"category": label, "value": 6} for label in labels]
    assert labels[0] in rendered.texts
    keep_image(rendered, "fix1-histogram")


def test_histogram_discrete_bins_render_in_numeric_order_with_rtl(tmp_path):
    columns, _ = raw_amounts()
    result = table(columns, [[v] for v in [1100, 300, 1000, 100] * 15])
    spec = parse(SPECS["histogram"][0] + "\ndirection rtl\nlabels on\nformat 0,0 SAR")
    rendered = gptvis.render(spec, columns, result, tmp_path, trace=True)
    config = json.loads(rendered.config.read_text())
    options = config["g2"]
    assert config["gptvis"]["type"] == "column"
    assert options["type"] == "interval"
    assert options["encode"]["x"] == "category"
    assert options["encode"]["y"] == "value"
    assert [row["category"] for row in options["data"]] == [
        "100–200", "200–300", "300–400", "400–500", "500–600",
        "600–700", "700–800", "800–900", "900–1,000", "1,000–1,100",
    ]
    assert [row["value"] for row in options["data"]] == [15, 0, 15, 0, 0, 0, 0, 0, 0, 30]
    assert "domain" not in options["scale"].get("x", {})
    assert options["labels"] == [{"text": "value", "formatter": {"$format": "value"}}]
    assert {"100–200", "15", "30"} <= set(rendered.texts)
    assert not any(text.endswith("SAR") for text in rendered.texts)


@pytest.mark.parametrize("digits,amount,share", [("western", "533.3", "9.91%"), ("arabic", "٥٣٣٫٣", "٩٫٩١%")])
def test_table_formats_numbers_and_meanings_in_png_config_and_page(digits, amount, share, tmp_path):
    columns = [column("average", "measure"), column("share", "share", unit="%", denominator="all"),
               column("n", "measure", unit="count"), column("label", "category")]
    for c, meaning in zip(columns, ["Average amount", "Share of total", "Orders", "Region <name>"]):
        c.meaning = meaning
    result = table(columns, [[533.2985542168675, 9.913666751770636, 1240, "<script>bad()</script>"],
                             [533.3, None, 0, "001"]])
    before = result.model_copy(deep=True)
    spec = parse(f"vis table\ndigits {digits}")
    rendered = gptvis.render(spec, columns, result, tmp_path, trace=True)
    config = json.loads(rendered.config.read_text())
    headers = [c.meaning for c in columns]
    assert config["gptvis"]["columns"] == headers
    rows = config["gptvis"]["data"]
    assert list(rows[0]) == headers
    assert rows[0]["Average amount"] == amount
    assert rows[0]["Share of total"] == share
    assert rows[0]["Orders"] == ("1,240" if digits == "western" else "١٬٢٤٠")
    assert rows[1]["Share of total"] is None
    assert rows[1]["Region <name>"] == "001"
    assert config["tableFormats"]["Orders"]["unit"] is None
    assert amount in rendered.texts and share in rendered.texts
    page = rendered.html.read_text()
    assert f"<td>{amount}</td>" in page and f"<td>{share}</td>" in page
    assert "Region &lt;name&gt;" in page and "&lt;script&gt;bad()&lt;/script&gt;" in page
    assert "<script>bad()</script>" not in page
    assert "533.2985542168675" not in page
    assert result == before


@pytest.mark.parametrize("axis_title", [None, "Attendance"])
def test_dual_axes_draw_separate_units_and_measure_titles(tmp_path, axis_title):
    spec = parse(SPECS["dual_axes"][0] + "\ntitle Monthly visits and revenue")
    spec.axis_y_title = axis_title
    rendered = gptvis.render(spec, *two_units(), tmp_path, trace=True)
    assert "Monthly visits and revenue" in rendered.texts
    assert "1,000 SAR" in rendered.texts
    assert "1,200 visits" not in rendered.texts
    assert "visits" in rendered.texts and "revenue" in rendered.texts
    config = json.loads(rendered.config.read_text())
    children = config["g2"]["children"]
    assert children[0]["axis"]["y"]["labelFormatter"] == {"$format": "value"}
    assert children[1]["axis"]["y"]["labelFormatter"] == {"$format": "value2"}
    assert [child["axis"]["y"]["title"] for child in children] == [axis_title or "visits", "revenue"]
    assert [series["axisYTitle"] for series in config["gptvis"]["series"]] == ["visits", "revenue"]
    assert config["number2"]["unit"] == "SAR"
    assert 'value.$format === \'value2\'' in rendered.html.read_text()
    keep_image(rendered, "fix1-dual-axes-explicit-title" if axis_title else "fix1-dual-axes")


def test_dual_axes_child_labels_use_their_own_format(tmp_path):
    spec = parse(SPECS["dual_axes"][0] + "\ntitle Monthly visits and revenue")
    resolved = resolve(spec, *two_units())
    # The package forwards per-series labels into its G2 child marks.
    for series in resolved.config["series"]:
        series["labels"] = [{"text": series["axisYTitle"]}]
    payload = {"config": resolved.config, "overrides": resolved.overrides,
               "format": resolved.number.model_dump(), "format2": resolved.number2.model_dump(),
               "output": str(tmp_path / "labels.png"), "trace": True}
    process = subprocess.run(["node", str(gptvis.SCRIPT)], input=json.dumps(payload),
                             text=True, capture_output=True, timeout=20)
    assert process.returncode == 0, process.stderr
    metrics = json.loads(process.stdout)
    assert "111 visits" in metrics["texts"] and "1,011 SAR" in metrics["texts"]
    for child, marker in zip(metrics["g2"]["children"], ["value", "value2"]):
        assert child["labels"][0]["formatter"] == {"$format": marker}


def test_page_escapes_content_and_embeds_png(tmp_path):
    spec = parse(SPECS["column"][0])
    spec.title = '</ScRiPt><script>alert("title")</script>{{g2}}'
    spec.description = '<img src=x onerror="alert(1)">'
    rendered = gptvis.render(spec, *arabic_cities(), tmp_path)
    page = rendered.html.read_text()
    assert "&lt;img src=x" in page and "data:image/png;base64," in page
    assert '</ScRiPt>' not in page and '<script>alert(' not in page
    assert "{{g2}}" in page  # Replacement must not reinterpret user text as a template.
    assert "@antv/g2@5.4.8/dist/g2.min.js" in page
    assert "animate: false" in page


def test_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(gptvis, "NODE_TIMEOUT_SECONDS", 0.001)
    with pytest.raises(RenderFailed, match="timed out"):
        gptvis.render(parse(SPECS["column"][0]), *arabic_cities(), tmp_path)


def test_missing_package(tmp_path, monkeypatch):
    monkeypatch.setattr(gptvis, "SCRIPT", tmp_path / "render.mjs")
    assert "npm ci --prefix vis_agent/render/gptvis" in gptvis.available()
    with pytest.raises(RendererUnavailable, match="npm ci"):
        gptvis.render(parse(SPECS["column"][0]), *arabic_cities(), tmp_path)


def test_missing_node(monkeypatch):
    monkeypatch.setattr(gptvis.shutil, "which", lambda _: None)
    assert "Node" in gptvis.available() and "npm ci" in gptvis.available()


def test_script_error_is_json(tmp_path):
    process = subprocess.run(["node", str(gptvis.SCRIPT)], input='{"config":{"type":"invalid"}}',
                             text=True, capture_output=True, timeout=20)
    assert process.returncode == 1
    assert json.loads(process.stderr)["error"]


@pytest.mark.parametrize("command_line_path", [False, True])
def test_script_accepts_output_path_from_stdin_or_command_line(tmp_path, command_line_path):
    output = tmp_path / "direct.png"
    payload = {"config": {"type": "column", "width": 300, "height": 200,
                          "data": [{"category": "North", "value": 10}, {"category": "South", "value": 20}]}}
    command = ["node", str(gptvis.SCRIPT)]
    if command_line_path:
        command.append(str(output))
    else:
        payload["output"] = str(output)
    process = subprocess.run(command, input=json.dumps(payload), text=True,
                             capture_output=True, timeout=20)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["bytes"] == output.stat().st_size


def test_smoke_test():
    assert gptvis.smoke_test() is None


@pytest.mark.parametrize("chart,field", [
    ("column", "value"), ("bar", "value"), ("grouped_column", "value"),
    ("stacked_bar", "value"), ("scatter", "y"), ("histogram", "value"),
    ("boxplot", "value"), ("treemap", "value"), ("word_cloud", "value"),
])
def test_labels_on_reaches_marks_and_formatter(chart, field, tmp_path):
    text, builder = SPECS[chart]
    if chart == "scatter":
        builder = lambda: scatter_points(3)
    rendered = gptvis.render(parse(text + "\nlabels on\nformat 0.0"), *builder(), tmp_path, trace=True)
    options = json.loads(rendered.config.read_text())["g2"]
    assert options["labels"] == [{"text": field, "formatter": {"$format": "value"}}]
    assert any(text.endswith(".0") for text in rendered.texts)


@pytest.mark.parametrize("switch", ["on", "off"])
def test_legend_switch_overrides_package_false(switch, tmp_path):
    spec = parse(SPECS["bar"][0] + f"\nlegend {switch}")
    rendered = gptvis.render(spec, *cities(), tmp_path)
    options = json.loads(rendered.config.read_text())["g2"]
    assert options["encode"]["color"] == "category"
    if switch == "on":
        assert "legend" not in options
    else:
        assert options["legend"] is False


def test_render_merges_compromises_in_order_without_duplicates(tmp_path):
    from vis_agent.designer.models import Compromise

    spec = parse(SPECS["column"][0])
    duplicate = resolve(spec, *arabic_cities()).compromises[0]
    first = Compromise(key="direction", message="A different check-time direction compromise")
    incoming = [first, duplicate, duplicate]
    rendered = gptvis.render(spec, *arabic_cities(), tmp_path, compromises=incoming)
    assert rendered.compromises[:2] == [first, duplicate]
    pairs = [(c.key, c.message) for c in rendered.compromises]
    assert len(pairs) == len(set(pairs))
    assert incoming == [first, duplicate, duplicate]


@pytest.mark.parametrize("digits,tick", [("western", "10.0 SAR"), ("arabic", "١٠٫٠ SAR")])
def test_radar_formats_every_position_axis_and_draws_ticks(digits, tick, tmp_path):
    columns, result = radar_groups()
    columns[-1].unit = "SAR"
    spec = parse(SPECS["radar"][0] + f"\nformat 0.0\ndigits {digits}")
    rendered = gptvis.render(spec, columns, result, tmp_path, trace=True)
    options = json.loads(rendered.config.read_text())["g2"]
    assert len(options["axis"]) == 8
    assert all(axis["labelFormatter"] == {"$format": "value"} for axis in options["axis"].values())
    assert tick in rendered.texts
