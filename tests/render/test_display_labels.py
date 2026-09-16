"""Translated display text never changes the result or a chart's grouping keys."""

import json
import subprocess

import pytest

from tests.designer.conftest import column, table, two_same_unit_measures
from tests.render.test_gptvis import SPECS
from vis_agent.designer.models import IndicatorCard, Spec
from vis_agent.designer.syntax import parse
from vis_agent.labels import value_key
from vis_agent.render import gptvis

pytestmark = pytest.mark.skipif(gptvis.available() is not None, reason=gptvis.available() or "")


@pytest.mark.parametrize("chart", list(SPECS))
def test_every_chart_applies_display_labels_without_rewriting_results(chart, tmp_path):
    text, builder = SPECS[chart]
    columns, result = builder()
    before = result.model_copy(deep=True)
    spec = parse(text)
    spec.column_labels = {c.name: f"Heading {i}" for i, c in enumerate(columns)}
    spec.value_labels = {
        c.name: {value_key(row[result.columns.index(c.name)]): f"Label {i}-{j}" for j, row in enumerate(result.rows)}
        for i, c in enumerate(columns) if c.kind not in {"measure", "share"}
    }
    rendered = gptvis.render(spec, columns, result, tmp_path, trace=True)
    assert result == before
    labels = {label for mapping in spec.value_labels.values() for label in mapping.values()}
    if labels:
        assert set(rendered.texts) & labels, (chart, rendered.texts)
    else:
        assert set(rendered.texts) & set(spec.column_labels.values())
    config = json.loads(rendered.config.read_text())
    # Our callbacks have portable descriptors; they never force a static-only export.
    assert not any("labelFormatter" in path or "tooltip" in path or "layout.text" in path
                   for path in config["functionPaths"])


@pytest.mark.parametrize("chart", ["bar", "column", "pie", "dual_axes", "grouped_column"])
def test_duplicate_translations_preserve_distinct_keys_and_measurements(chart, tmp_path):
    columns = [column("code", "category"), column("n", "measure"), column("other", "measure"),
               column("group_code", "category")]
    result = table(columns, [["001", 13, 2.5, "A"], ["002", 29, 7.5, "B"]])
    bind = {"category": "code", "value": "n"}
    if chart == "dual_axes":
        bind["value2"] = "other"
    if chart == "grouped_column":
        bind["group"] = "group_code"
    spec = Spec(type=chart, bind=bind, language="ar", sort="none",
                column_labels={"code": "الجنسية", "n": "العدد", "other": "القيمة", "group_code": "المجموعة"},
                value_labels={"code": {"001": "مواطن", "002": "مواطن"},
                              "group_code": {"A": "مجموعة", "B": "مجموعة"}})
    rendered = gptvis.render(spec, columns, result, tmp_path, trace=True)
    config = json.loads(rendered.config.read_text())
    data = config["g2"]["data"]
    assert [row["category"] for row in data] == ["001", "002"]
    measure = "n" if chart == "dual_axes" else "value"
    assert [row[measure] for row in data] == [13, 29]
    if chart == "grouped_column":
        assert [row["group"] for row in data] == ["A", "B"]
        assert "مجموعة" in rendered.texts
    assert "مواطن" in rendered.texts
    assert config["functionPaths"] == []
    assert "const interactive = true" in rendered.html.read_text()
    assert result.rows == [["001", 13, 2.5, "A"], ["002", 29, 7.5, "B"]]


def test_folded_series_uses_raw_measure_keys_with_translated_legend(tmp_path):
    columns, result = two_same_unit_measures()
    spec = Spec(type="multi_line", bind={"time": "month"}, fold=["injuries", "deaths"],
                column_labels={"injuries": "إصابات", "deaths": "وفيات"})
    rendered = gptvis.render(spec, columns, result, tmp_path, trace=True)
    config = json.loads(rendered.config.read_text())
    assert {row["group"] for row in config["gptvis"]["data"]} == {"injuries", "deaths"}
    assert {"إصابات", "وفيات"} <= set(rendered.texts)


@pytest.mark.parametrize("chart", ["table", "indicator"])
def test_table_and_indicator_localize_context_and_keep_hijri_and_source(chart, tmp_path):
    columns = [column("code", "category"), column("period", "time"), column("n", "measure")]
    result = table(columns, [["S", "١٤٤٧-٠٩", 1250]])
    spec = Spec(type=chart, language="ar", column_labels={"code": "الجنسية", "period": "الفترة", "n": "العدد"},
                value_labels={"code": {"S": "مواطن"}},
                cards=[IndicatorCard(value="n", context=["code", "period"])] if chart == "indicator" else [])
    rendered = gptvis.render(spec, columns, result, tmp_path, trace=True)
    assert {"مواطن", "١٤٤٧-٠٩", "الجنسية"} <= {text.strip("\u202d\u202c") for text in rendered.texts}
    assert "مواطن" in rendered.html.read_text()
    assert result.rows == [["S", "١٤٤٧-٠٩", 1250]]
    if chart == "table":
        assert 'bidi-override">١٤٤٧-٠٩</bdi>' in rendered.html.read_text()
        config = json.loads(rendered.config.read_text())["gptvis"]
        assert config["columns"] == ["code", "period", "n"]
        assert config["data"] == [{"code": "S", "period": "١٤٤٧-٠٩", "n": 1250}]


def test_shared_callbacks_revive_tooltip_labels_without_merging_numeric_codes():
    module = gptvis.SCRIPT.with_name("display.js").as_uri()
    script = f"""
import {{ makeDisplay, applyDisplay }} from {json.dumps(module)};
const display = {{fields: {{category: {{1:'Citizen',2:'Resident'}}}}, columns: {{category:'Nationality',value:'Count'}}}};
const callbacks = makeDisplay(display, value => `${{value}} people`);
const options = {{type:'interval',data:[{{category:1,value:7}},{{category:2,value:9}}],encode:{{x:'category',y:'value'}}}};
applyDisplay(options, display, callbacks, 'column');
const desc = callbacks.descriptor(options.tooltip.title);
const revived = makeDisplay(display).callback(JSON.parse(JSON.stringify(desc)));
const reserved = makeDisplay(JSON.parse('{{"fields":{{"code":{{"null":"Literal null","__proto__":"Prototype"}}}},"columns":{{}}}}'));
if (reserved.label('code', null) !== null || reserved.label('code','null') !== 'Literal null'
  || reserved.label('code','constructor') !== 'constructor' || reserved.callback({{kind:'column'}})('constructor') !== 'constructor') throw new Error('Unsafe lookup');
console.log(JSON.stringify({{data:options.data,title:revived(options.data[0]),item:options.tooltip.items[1](options.data[0])}}));
"""
    process = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    assert json.loads(process.stdout) == {"data": [{"category": 1, "value": 7}, {"category": 2, "value": 9}],
                                         "title": "Citizen", "item": {"name": "Count", "value": "7 people"}}


def test_table_duplicate_headings_and_same_code_in_different_columns_stay_separate(tmp_path):
    columns = [column("nationality", "category"), column("status", "category"), column("n", "measure")]
    result = table(columns, [["S", "S", 17]])
    spec = Spec(type="table", column_labels={"nationality": "Type", "status": "Type"},
                value_labels={"nationality": {"S": "Citizen"}, "status": {"S": "Stopped"}})
    rendered = gptvis.render(spec, columns, result, tmp_path, trace=True)
    config = json.loads(rendered.config.read_text())["gptvis"]
    assert config["data"] == [{"nationality": "S", "status": "S", "n": 17}]
    assert {"Citizen", "Stopped", "17"} <= set(rendered.texts)
    assert rendered.html.read_text().count('<th scope="col">Type</th>') == 2


def test_numeric_and_reserved_categorical_codes_have_safe_exact_display_lookups(tmp_path):
    columns = [column("code", "category"), column("n", "measure")]
    result = table(columns, [[1, 13], [2, 29]])
    spec = Spec(type="column", bind={"category": "code", "value": "n"}, sort="none",
                value_labels={"code": {"1": "Citizen", "2": "Resident"}})
    rendered = gptvis.render(spec, columns, result, tmp_path / "numeric", trace=True)
    config = json.loads(rendered.config.read_text())
    assert config["g2"]["data"] == [{"category": 1, "value": 13}, {"category": 2, "value": 29}]
    assert {"Citizen", "Resident"} <= set(rendered.texts)
    result = table(columns, [["constructor", 13], ["__proto__", 29], ["toString", 7]])
    spec.value_labels = {"code": {"__proto__": "Prototype"}}
    rendered = gptvis.render(spec, columns, result, tmp_path / "reserved", trace=True)
    assert {"constructor", "Prototype", "toString"} <= set(rendered.texts)


def test_same_raw_code_has_column_scoped_axis_legend_and_tooltip_labels(tmp_path):
    columns = [column("gender", "category"), column("marital_status", "category"), column("n", "measure")]
    result = table(columns, [["M", "M", 17], ["F", "S", 19]])
    spec = Spec(type="grouped_column", bind={"category": "gender", "group": "marital_status", "value": "n"},
                language="ar", sort="none", column_labels={"gender": "الجنس", "marital_status": "الحالة الاجتماعية", "n": "العدد"},
                value_labels={"gender": {"M": "ذكر", "F": "أنثى"}, "marital_status": {"M": "متزوج", "S": "أعزب"}})
    rendered = gptvis.render(spec, columns, result, tmp_path, trace=True)
    assert {"ذكر", "أنثى", "متزوج", "أعزب"} <= set(rendered.texts)
    config = json.loads(rendered.config.read_text())
    assert config["g2"]["data"][0] == {"category": "M", "group": "M", "value": 17}
    module = gptvis.SCRIPT.with_name("display.js").as_uri()
    script = f"""
import {{makeDisplay}} from {json.dumps(module)};
const config = {json.dumps(config)};
const callbacks = makeDisplay(config.display);
const datum = config.g2.data[0];
console.log(JSON.stringify(config.g2.tooltip.items.map(item => callbacks.callback(item.$display)(datum))));
"""
    process = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    items = json.loads(process.stdout)
    assert {"name": "الجنس", "value": "ذكر"} in items
    assert {"name": "الحالة الاجتماعية", "value": "متزوج"} in items
