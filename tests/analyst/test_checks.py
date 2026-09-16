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


@pytest.mark.parametrize("unit", ["%", "percentage", "نسبة مئوية"])
def test_shares_must_add_up(store, people, unit):
    dataset, profile = people
    columns = [column("region", "geography", "region"), column("share", "share", "amount", "share",
               denominator="all amounts", unit=unit, partition_by=[])]
    good = QueryResult(sql="x", columns=["region", "share"], types=["VARCHAR", "DOUBLE"], rows=[["East", 38.1], ["West", 61.9]], row_count=2, seconds=0)
    assert failed_checks(check_result(store, profile, columns, good)) == []
    fraction = QueryResult(sql="x", columns=["region", "share"], types=["VARCHAR", "DOUBLE"], rows=[["East", 0.381], ["West", 0.619]], row_count=2, seconds=0)
    fractions = [columns[0], columns[1].model_copy(update={"unit": "fraction"})]
    assert failed_checks(check_result(store, profile, fractions, fraction)) == []
    assert names(failed_checks(check_result(store, profile, columns, fraction))) == ["shares_add_up"]
    short = QueryResult(sql="x", columns=["region", "share"], types=["VARCHAR", "DOUBLE"], rows=[["East", 38.1], ["West", 50.0]], row_count=2, seconds=0)
    failed = failed_checks(check_result(store, profile, columns, short))
    assert names(failed) == ["shares_add_up"] and failed[0].severity == "warning" and "88.1" in failed[0].message


@pytest.mark.parametrize("rows", [[[0.000539399]], [[9.91]], [[20], [30]], [[None]]])
def test_scalar_partial_and_independent_shares_do_not_claim_a_partition(store, people, rows):
    _, profile = people
    result = QueryResult(sql="x", columns=["share"], types=["DOUBLE"], rows=rows, row_count=len(rows), seconds=0)
    columns = [column("share", "share", unit="%", denominator="the requested scope")]
    assert failed_checks(check_result(store, profile, columns, result)) == []


def test_share_groups_follow_declared_columns_not_column_order(store, people):
    _, profile = people
    result = QueryResult(sql="x", columns=["part", "year", "region", "share"],
                         types=["VARCHAR", "VARCHAR", "VARCHAR", "DOUBLE"],
                         rows=[["A", "2025", "East", 40], ["B", "2025", "East", 60],
                               ["A", "2026", "West", 25], ["B", "2026", "West", 75]], row_count=4, seconds=0)
    columns = [column("part", "category"), column("year", "time"), column("region", "category"),
               column("share", "share", unit="%", partition_by=["year", "region"])]
    assert failed_checks(check_result(store, profile, columns, result)) == []
    result.rows[-1][-1] = 70
    failures = failed_checks(check_result(store, profile, columns, result))
    assert names(failures) == ["shares_add_up"]
    assert "2026" in failures[0].message and "95" in failures[0].message


@pytest.mark.parametrize("groups,unit,row_count,expected", [
    (["missing"], "%", 1, "share_partition_columns"),
    (["n"], "%", 1, "share_partition_columns"),
    ([], None, 1, "share_partition_scale"),
    ([], "%", 2, "share_partition_incomplete"),
])
def test_partition_metadata_and_materialization_are_checked(store, people, groups, unit, row_count, expected):
    _, profile = people
    result = QueryResult(sql="x", columns=["n", "share"], types=["BIGINT", "DOUBLE"],
                         rows=[[2, 100]], row_count=row_count, seconds=0)
    columns = [column("n", "measure"), column("share", "share", unit=unit, partition_by=groups)]
    assert names(failed_checks(check_result(store, profile, columns, result))) == [expected]


def test_percentage_change_is_not_a_share_partition(store, people):
    _, profile = people
    result = QueryResult(sql="x", columns=["change"], types=["DOUBLE"], rows=[[-150]], row_count=1, seconds=0)
    assert failed_checks(check_result(store, profile, [column("change", "measure", unit="%")], result)) == []


def test_multi_column_source_feedback_explains_how_to_repair_metadata(store, people):
    dataset, profile = people
    result = run(store, dataset, f'SELECT sum(amount) / count(gender) AS mean FROM "{dataset}"')
    bad = [column("mean", "measure", "amount, gender")]
    checks = failed_checks(check_result(store, profile, bad, result))
    assert names(checks) == ["source_column_exists"]
    assert "source null" in checks[0].message and "commas" in checks[0].message
    assert failed_checks(check_result(store, profile, [column("mean", "measure")], result)) == []


@pytest.mark.parametrize("unit,values,partition", [("%", [-20, 120], []), ("%", [120], None),
                                                    ("percentage", [-20, 120], []), ("percent", [108.86], None),
                                                    ("fraction", [-0.2, 1.2], [])])
def test_part_of_whole_ranges_are_checked_even_when_the_partition_sums_correctly(store, people, unit, values, partition):
    _, profile = people
    result = QueryResult(sql="x", columns=["share"], types=["DOUBLE"], rows=[[v] for v in values],
                         row_count=len(values), seconds=0)
    checks = failed_checks(check_result(store, profile, [column("share", "share", unit=unit, partition_by=partition)], result))
    assert "share_in_bounds" in names(checks)
    assert "percentage change" in next(c.message for c in checks if c.check == "share_in_bounds")


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


@pytest.mark.parametrize("summary", [
    "The total orders decreased by 80% from 2025 to 2026.",
    "Orders dropped by 80%.", "Orders fell by 80%.", "There was a decrease of 80%.",
    "There was an 80% drop.", "Orders declined by approximately 80%.",
    "انخفض إجمالي الطلبات بنسبة ٨٠٪ من ٢٠٢٥ إلى ٢٠٢٦.",
    "تراجعت الطلبات بمقدار ٨٠٪.", "انخفاض بنسبة ٨٠٪.",
])
def test_decrease_magnitude_matches_a_negative_result_without_changing_its_sign(summary):
    result = QueryResult(sql="x", columns=["change"], types=["DOUBLE"], rows=[[-80.0]], row_count=1, seconds=0)
    assert summary_numbers_exist(summary, result, "Change from 2025 to 2026").passed


@pytest.mark.parametrize("summary,value", [
    ("Orders increased by 80%.", -80),
    ("Orders rose by 80%.", -80),
    ("Orders fell by 80%.", 80),
    ("There was an 80% decrease.", 80),
    ("The percentage change was 80%.", -80),
    ("Orders fell to 80%.", -80),
    ("Orders fell from 80%.", -80),
    ("Orders did not decrease by 80%.", -80),
    ("Orders didn't decrease by 80%.", -80),
    ("There was no 80% drop.", -80),
    ("Orders decreased by -80%.", -80),
    ("Orders decreased by +80%.", 80),
    ("Orders increased by -80%.", -80),
    ("Orders decreased by 80%.", -.8),
    ("Orders decreased by 80%.", .8),
    ("ارتفعت الطلبات بنسبة ٨٠٪.", -80),
    ("انخفضت الطلبات بنسبة ٨٠٪.", 80),
    ("لم تنخفض الطلبات بنسبة ٨٠٪.", -80),
    ("لم يحدث انخفاض بنسبة ٨٠٪.", -80),
    ("انخفاض بمقدار -٨٠٪.", -80),
    ("انخفضت الطلبات إلى ٨٠٪.", -80),
])
def test_directional_wording_cannot_use_opposite_sign_or_an_unsigned_magnitude(summary, value):
    result = QueryResult(sql="x", columns=["change"], types=["DOUBLE"], rows=[[value]], row_count=1, seconds=0)
    assert not summary_numbers_exist(summary, result).passed


@pytest.mark.parametrize("summary,value", [("Orders increased by 80%.", 80),
                                           ("Orders rose by 80%.", 80),
                                           ("ارتفعت الطلبات بنسبة ٨٠٪.", 80),
                                           ("Orders fell to 80%.", 80),
                                           ("The change was -80%.", -80),
                                           ("Orders decreased by 15.82%.", -15.8158)])
def test_literal_levels_and_correctly_signed_changes_still_validate(summary, value):
    result = QueryResult(sql="x", columns=["change"], types=["DOUBLE"], rows=[[value]], row_count=1, seconds=0)
    assert summary_numbers_exist(summary, result).passed


def test_directional_magnitude_must_come_from_numeric_results_not_context_or_text_cells():
    result = QueryResult(sql="x", columns=["label"], types=["VARCHAR"], rows=[["-80% change"]], row_count=1, seconds=0)
    assert not summary_numbers_exist("Orders decreased by 80%.", result, "The previous change was -80%.").passed


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


def test_total_check_sums_arabic_digit_text(store, hijri):
    dataset, profile = hijri
    result = run(store, dataset, f"""SELECT sum(CAST(replace(translate(amount, '٠١٢٣٤٥٦٧٨٩٫٬', '0123456789.,'), ',', '')
                                    AS DOUBLE)) AS total FROM "{dataset}\"""")
    assert result.rows == [[1285.0]]
    columns = [column("total", "measure", "amount", "sum")]
    assert failed_checks(check_result(store, profile, columns, result)) == []


def test_an_ordinal_column_must_follow_its_scale(store):
    from datetime import datetime, timezone

    from vis_agent.profiler.measurements import compute_statistics
    from vis_agent.profiler.models import DatasetProfile

    source = store.save_upload("population.csv", (
        "person_type,age_group,population_count\n"
        "Saudi,أقل من 15,863\nSaudi,15-30,556\nSaudi,30-45,492\nSaudi,45-60,461\nSaudi,أكثر من 60,378\n"
        "Alien,أقل من 15,935\nAlien,15-30,586\nAlien,30-45,467\nAlien,45-60,430\nAlien,أكثر من 60,397\n"
    ).encode("utf-8"))
    store.import_csv(source.dataset_id)
    statistics = compute_statistics(store, source)
    assert next(c for c in statistics.columns if c.name == "age_group").ordinal_pattern == "أقل من 15 < 15-30 < 30-45 < 45-60 < أكثر من 60"
    profile = DatasetProfile(source=source, status="complete", deterministic=statistics, created_at=datetime.now(timezone.utc))
    dataset = source.dataset_id
    columns = [column("person_type", "category", "person_type"), column("age_group", "ordinal", "age_group"),
               column("population_count", "measure", "population_count", "sum")]

    by_text = run(store, dataset, f'SELECT person_type, age_group, sum(population_count) AS population_count FROM "{dataset}" '
                                  f"GROUP BY 1, 2 ORDER BY 1, 2")
    failed = failed_checks(check_result(store, profile, columns, by_text))
    assert names(failed) == ["ordinal_in_order"] and failed[0].severity == "error"
    assert "ORDER BY CASE" in failed[0].message and "أقل من 15 < 15-30" in failed[0].message

    by_scale = run(store, dataset, f'SELECT person_type, age_group, sum(population_count) AS population_count FROM "{dataset}" '
                                   f"GROUP BY 1, 2 ORDER BY 1, CASE age_group WHEN 'أقل من 15' THEN 1 WHEN '15-30' THEN 2 "
                                   f"WHEN '30-45' THEN 3 WHEN '45-60' THEN 4 WHEN 'أكثر من 60' THEN 5 END")
    assert failed_checks(check_result(store, profile, columns, by_scale)) == []

    dominant = run(
        store, dataset,
        f'SELECT person_type, arg_max(age_group, population_count) AS dominant_age '
        f'FROM "{dataset}" GROUP BY 1 ORDER BY 1',
    )
    dominant_columns = [
        column("person_type", "category", "person_type"),
        column("dominant_age", "ordinal", "age_group"),
    ]
    assert failed_checks(check_result(store, profile, dominant_columns, dominant), "error") == []
