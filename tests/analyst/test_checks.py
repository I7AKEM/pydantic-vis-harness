# tests/analyst/test_checks.py
import pytest

from vis_agent.analyst.checks import check_result, summary_numbers_exist
from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.analyst.query import run_sql
from vis_agent.profiler.review import failed_checks


def names(checks):
    return [c.check for c in checks]


def column(name, kind, source=None, aggregate="none", **extra):
    return ResultColumn(name=name, meaning=name, kind=kind, source=source, aggregate=aggregate, **extra)


def run(store, dataset, sql):
    result = run_sql(store, dataset, sql)
    assert result.__class__.__name__ == "QueryResult", result
    return result


def test_faithful_result_passes(store, people):
    dataset, profile = people
    result = run(store, dataset, f'SELECT region, sum(amount) AS total, avg(amount) AS mean FROM "{dataset}" GROUP BY 1 ORDER BY 1')
    columns = [column("region", "geography", "region"), column("total", "measure", "amount", "sum", unit="SAR"),
               column("mean", "measure", "amount", "avg", unit="SAR")]
    assert failed_checks(check_result(store, profile, columns, result)) == []


def test_descriptions_must_match_the_result(store, people):
    dataset, profile = people
    result = run(store, dataset, f'SELECT region, count(*) AS n FROM "{dataset}" GROUP BY 1')
    failed = failed_checks(check_result(store, profile, [column("region", "geography", "region")], result))
    assert names(failed) == ["column_descriptions_match_result"] and failed[0].severity == "error"


def test_descriptions_must_be_in_result_order(store, people):
    dataset, profile = people
    result = run(store, dataset, f'SELECT region, count(*) AS n FROM "{dataset}" GROUP BY 1')
    columns = [column("n", "measure", None, "count"), column("region", "geography", "region")]
    failed = failed_checks(check_result(store, profile, columns, result), "error")
    assert names(failed) == ["column_descriptions_match_result"]
    assert failed[0].message == f"Describe exactly the result columns, once each and in result order: {result.columns}."


def test_relabelled_codes_need_the_code_column_and_the_known_meaning(store, people):
    dataset, profile = people
    swapped = run(store, dataset, f"SELECT gender, CASE gender WHEN 'F' THEN 'Male' ELSE 'Female' END AS label, "
                                  f'count(*) AS n FROM "{dataset}" GROUP BY 1, 2')
    columns = [column("gender", "category", "gender"), column("label", "category", "gender"), column("n", "measure", None, "count")]
    failed = failed_checks(check_result(store, profile, columns, swapped))
    assert names(failed) == ["code_labels_match_profile"] and "Male" in failed[0].message
    faithful = run(store, dataset, f"SELECT gender, CASE gender WHEN 'F' THEN 'Female' ELSE 'Male' END AS label, "
                                   f'count(*) AS n FROM "{dataset}" GROUP BY 1, 2')
    assert failed_checks(check_result(store, profile, columns, faithful)) == []
    orphan = run(store, dataset, f"SELECT CASE gender WHEN 'F' THEN 'Female' ELSE 'Male' END AS label, count(*) AS n "
                                 f'FROM "{dataset}" GROUP BY 1')
    failed = failed_checks(check_result(store, profile, [column("label", "category", "gender"), column("n", "measure", None, "count")], orphan))
    assert names(failed) == ["labels_faithful"] and "code column" in failed[0].message


def test_null_codes_do_not_crash_the_label_check(store, people):
    _dataset, profile = people
    result = QueryResult(sql="x", columns=["gender", "label", "n"], types=["VARCHAR", "VARCHAR", "BIGINT"],
                         rows=[[None, "Unknown", 3], ["F", "Female", 2]], row_count=2, seconds=0)
    columns = [column("gender", "category", "gender"), column("label", "category", "gender"),
               column("n", "measure", None, "count")]
    assert failed_checks(check_result(store, profile, columns, result), "error") == []


def test_other_rows_and_unknown_labels(store, people):
    dataset, profile = people
    result = QueryResult(sql="x", columns=["region", "n"], types=["VARCHAR", "BIGINT"], rows=[["East", 2], ["Other", 3]], row_count=2, seconds=0)
    columns = [column("region", "geography", "region"), column("n", "measure", None, "count")]
    assert failed_checks(check_result(store, profile, columns, result)) == []
    result.rows = [["East", 2], ["North", 3]]
    assert names(failed_checks(check_result(store, profile, columns, result))) == ["labels_faithful"]


def test_shares_must_add_up(store, people):
    dataset, profile = people
    columns = [column("region", "geography", "region"), column("share", "share", "amount", "share", denominator="all amounts")]
    good = QueryResult(sql="x", columns=["region", "share"], types=["VARCHAR", "DOUBLE"], rows=[["East", 38.1], ["West", 61.9]], row_count=2, seconds=0)
    assert failed_checks(check_result(store, profile, columns, good)) == []
    fraction = QueryResult(sql="x", columns=["region", "share"], types=["VARCHAR", "DOUBLE"], rows=[["East", 0.381], ["West", 0.619]], row_count=2, seconds=0)
    assert failed_checks(check_result(store, profile, columns, fraction)) == []
    short = QueryResult(sql="x", columns=["region", "share"], types=["VARCHAR", "DOUBLE"], rows=[["East", 38.1], ["West", 50.0]], row_count=2, seconds=0)
    failed = failed_checks(check_result(store, profile, columns, short))
    assert names(failed) == ["shares_add_up"] and failed[0].severity == "warning" and "88.1" in failed[0].message


def test_aggregates_stay_in_bounds_and_totals_are_explained(store, people):
    dataset, profile = people
    out_of_range = QueryResult(sql="x", columns=["region", "mean"], types=["VARCHAR", "DOUBLE"], rows=[["East", 500.0]], row_count=1, seconds=0)
    columns = [column("region", "geography", "region"), column("mean", "measure", "amount", "avg")]
    failed = failed_checks(check_result(store, profile, columns, out_of_range))
    assert names(failed) == ["aggregate_in_bounds"] and failed[0].severity == "error"
    filtered = run(store, dataset, f"SELECT region, sum(amount) AS total FROM \"{dataset}\" WHERE region = 'East' GROUP BY 1")
    columns = [column("region", "geography", "region"), column("total", "measure", "amount", "sum")]
    failed = failed_checks(check_result(store, profile, columns, filtered))
    assert names(failed) == ["total_explained"] and failed[0].severity == "warning" and "105" in failed[0].message


def test_empty_results_and_time_order(store, people):
    dataset, profile = people
    empty = run(store, dataset, f"SELECT region FROM \"{dataset}\" WHERE region = 'Nowhere'")
    assert names(failed_checks(check_result(store, profile, [column("region", "geography", "region")], empty))) == ["result_not_empty"]
    backwards = run(store, dataset, f'SELECT day, sum(amount) AS total FROM "{dataset}" GROUP BY 1 ORDER BY 1 DESC')
    columns = [column("day", "time", "day"), column("total", "measure", "amount", "sum")]
    failed = failed_checks(check_result(store, profile, columns, backwards))
    assert names(failed) == ["time_in_order"] and failed[0].severity == "warning"


def test_summary_numbers_must_exist_in_the_result():
    result = QueryResult(sql="x", columns=["region", "total", "share", "day"], types=["VARCHAR", "BIGINT", "DOUBLE", "DATE"],
                         rows=[["East", 40, 0.381, "2026-01-01"], ["West", 65, 0.619, "2026-02-01"]], row_count=2, seconds=0)
    assert summary_numbers_exist("West leads with 65 SAR, 61.9% of the total, since 2026.", result).passed
    assert summary_numbers_exist("الغرب يتصدر بمبلغ ٦٥ ريال أي ٦١٫٩٪ من الإجمالي عبر منطقتين.", result).passed
    check = summary_numbers_exist("West leads with 70 SAR.", result)
    assert not check.passed and "70" in check.message and check.severity == "error"
    assert not summary_numbers_exist("Under 15, the West leads with 65 SAR.", result).passed
    assert summary_numbers_exist("Under 15, the West leads with 65 SAR.", result, "What share is under 15?").passed
    assert summary_numbers_exist("In December 2025 the West led with 65 SAR.", result, "violations December 2025").passed


@pytest.mark.parametrize("width", [4, 7], ids=["year", "month"])
@pytest.mark.parametrize("order", ["ASC", "DESC"])
def test_hijri_text_time_order(store, hijri, width, order):
    dataset, profile = hijri
    result = run(store, dataset,
                 f"SELECT substr(translate(day, '٠١٢٣٤٥٦٧٨٩', '0123456789'), 1, {width}) AS bucket, "
                 f'count(*) AS n FROM "{dataset}" GROUP BY 1 ORDER BY 1 {order}')
    columns = [column("bucket", "time", "day", unit=None), column("n", "measure", aggregate="count")]
    assert result.types[0] == "VARCHAR"
    failed = failed_checks(check_result(store, profile, columns, result))
    if order == "ASC":
        assert failed == []
    else:
        assert names(failed) == ["time_in_order"]
        assert failed[0].severity == "warning"
