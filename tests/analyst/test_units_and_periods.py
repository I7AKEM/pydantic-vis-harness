# tests/analyst/test_units_and_periods.py
import asyncio

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from vis_agent.analyst.agent import analyze_dataset, create_analyst
from vis_agent.analyst.checks import check_result, named_period_check, normalise_units, numbers_in, restates
from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.profiler.agent import create_profiler
from tests.requests.conftest import prompt_of, tool_returns


def col(name, kind, unit=None, aggregate="none", source=None):
    return ResultColumn(name=name, meaning=name, kind=kind, unit=unit, aggregate=aggregate, source=source)


def test_percent_aliases_become_percent_and_generic_count_markers_drop():
    assert normalise_units(col("share", "share")).unit is None  # the scale is the analyst's to declare
    assert normalise_units(col("share", "share", unit="percentage")).unit == "%"
    for marker in ("count", "Number", "n", "عدد", "رقم"):
        assert normalise_units(col("n", "measure", unit=marker, aggregate="count")).unit is None
    assert normalise_units(col("fine", "measure", unit="SAR", aggregate="sum")).unit == "SAR"


def test_a_noun_the_data_names_stays_as_the_unit_for_the_kpi_and_the_axis():
    for noun in ("person", "شخص", "نسمة", "رحلة", "students"):
        assert normalise_units(col("n", "measure", unit=noun, aggregate="count")).unit == noun


def test_a_year_the_question_names_must_reach_the_sql_or_the_assumptions():
    assert named_period_check("Violations in 2024 by city", "SELECT city FROM t WHERE year = 2024", []).passed
    assert not named_period_check("Violations in 2024 by city", "SELECT city FROM t", []).passed
    assert named_period_check("المخالفات في ١٤٤٧", "SELECT city FROM t", ["البيانات كلها لسنة 1447"]).passed
    assert named_period_check("Violations by city", "SELECT city FROM t", []).passed


def test_numbers_in_reads_both_digit_systems():
    assert numbers_in("١٢٬٣٤٥ people and 33.3%") == {"12345", "33.3"}


def test_a_clarification_that_repeats_the_question_is_restated():
    assert restates("هل تقصد نسبة الشباب؟", "ما نسبة الشباب بين السكان؟")
    assert not restates("هل تقصد الفئة 15-24 أم 15-29؟", "ما نسبة الشباب بين السكان؟")
    assert not restates("Which amount column: paid or unpaid?", "Total amount by region")


def test_a_trend_ordered_descending_is_an_error(store, people):
    _dataset_id, profile = people
    columns = [col("day", "time", source="day"), col("total", "measure", aggregate="sum", source="amount")]
    rows = [["2026-03-01", 5], ["2026-02-01", 60], ["2026-01-01", 40]]

    def result(sql):
        return QueryResult(sql=sql, columns=["day", "total"], types=["DATE", "BIGINT"], rows=rows, row_count=3, seconds=0)

    def level(sql):
        return {c.severity for c in check_result(store, profile, columns, result(sql)) if c.check == "time_in_order"}

    assert level('SELECT day, sum(amount) AS total FROM t GROUP BY 1 ORDER BY "day" DESC') == {"error"}
    assert level("SELECT day, sum(amount) AS total FROM t GROUP BY 1 ORDER BY total DESC") == {"warning"}


def test_run_query_normalises_units_and_the_period_check_records_a_warning(store, people):
    dataset_id, _profile = people

    def drive(messages, info):
        if not tool_returns(messages):
            prompt = prompt_of(messages)
            return ModelResponse(parts=[ToolCallPart(tool_name="run_query", args={
                "sql": f'SELECT region, count(*) AS n FROM {prompt["table"]} GROUP BY 1 ORDER BY 2 DESC',
                "columns": [{"name": "region", "meaning": "Region", "kind": "category", "source": "region"},
                            {"name": "n", "meaning": "People", "kind": "measure", "aggregate": "count", "unit": "count"}]})])
        return ModelResponse(parts=[ToolCallPart(tool_name="deliver_analysis", args={"summary": "West has 3 people."})])

    analyst = create_analyst("test")
    with analyst.override(model=FunctionModel(drive)):
        report = asyncio.run(analyze_dataset(store, create_profiler("test"), analyst, dataset_id, "People by region in 2026"))
    assert report.analysis is not None and report.analysis.columns[1].unit is None
    assert "named_period_missing" in [c.check for c in report.checks if not c.passed]


def test_a_restated_clarification_is_sent_back_once(store, people):
    dataset_id, _profile = people
    calls = {"n": 0}

    def drive(messages, info):
        calls["n"] += 1
        question = "هل تقصد نسبة الشباب؟" if calls["n"] == 1 else "ما الفئة العمرية التي تعدّها شبابًا: 15-24 أم 15-29؟"
        return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification",
                                                 args={"ask": question, "reason": "undefined term"})])

    analyst = create_analyst("test")
    with analyst.override(model=FunctionModel(drive)):
        report = asyncio.run(analyze_dataset(store, create_profiler("test"), analyst, dataset_id, "ما نسبة الشباب بين السكان؟"))
    assert calls["n"] == 2 and report.clarification is not None and "15-24" in report.clarification.question


def test_a_clarification_restated_every_time_ends_the_run_instead_of_reaching_the_caller(store, people):
    dataset_id, _profile = people
    calls = {"n": 0}

    def drive(messages, info):
        calls["n"] += 1
        return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification",
                                                 args={"ask": "هل تقصد نسبة الشباب؟", "reason": "undefined term"})])

    analyst = create_analyst("test")
    with analyst.override(model=FunctionModel(drive)):
        report = asyncio.run(analyze_dataset(store, create_profiler("test"), analyst, dataset_id, "ما نسبة الشباب بين السكان؟"))
    assert calls["n"] == 3 and report.clarification is None and report.analysis is None
    assert any("repeats the caller" in warning for warning in report.warnings)
