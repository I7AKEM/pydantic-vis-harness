from profile_models import ColumnStatistics, ColumnSemantics, DataBrief, DeterministicProfile, NumericStatistics, SemanticProfile
from profile_review import failed_checks, run_checks


def stat(name, physical_type="VARCHAR", distinct=3, nulls=0, **extra):
    return ColumnStatistics(name=name, original_name=name, physical_type=physical_type,
                            null_count=nulls, null_percentage=0, distinct_count=distinct, **extra)


def numeric():
    return NumericStatistics(finite_count=3, non_finite_count=0, minimum=1, maximum=3, mean=2,
                             standard_deviation=0.8, q25=1.5, median=2, q75=2.5)


def statistics(*columns, rows=100):
    return DeterministicProfile(row_count=rows, column_count=len(columns), duplicate_rows=0,
                                columns=list(columns), sample_rows=[], sample_description="")


def semantic(**roles):
    return SemanticProfile(description="d", row_meaning=None, columns=[
        ColumnSemantics(name=name, meaning=None, role=role, unit=unit, confidence="low", evidence="e",
                        code_meanings=codes)
        for name, (role, unit, codes) in roles.items()
    ])


def names(checks):
    return sorted(c.check for c in checks)


def test_time_role_needs_time_statistics_or_ordinal_pattern():
    stats = statistics(stat("day", "DATE", measurement_levels=["time"]), stat("q", ordinal_pattern="Q#"), stat("note"))
    result = run_checks(stats, semantic(day=("time", None, None), q=("time", None, None), note=("time", None, None)))
    assert names(failed_checks(result)) == ["time_role_has_time_statistics"]
    assert failed_checks(result)[0].column == "note"
    assert failed_checks(result)[0].severity == "error"


def test_identifier_must_be_near_unique():
    stats = statistics(stat("id", distinct=100), stat("dup", distinct=40))
    result = run_checks(stats, semantic(id=("identifier", None, None), dup=("identifier", None, None)))
    assert [c.column for c in failed_checks(result)] == ["dup"]


def test_measures_need_numbers_and_units_only_on_measures():
    stats = statistics(stat("amount", "DOUBLE", numeric=numeric()), stat("price"), stat("region"))
    result = run_checks(stats, semantic(amount=("measure", "USD", None), price=("measure", None, None),
                                        region=("category", "USD", None)))
    assert names(failed_checks(result)) == ["measure_is_numeric", "unit_only_on_measures"]


def test_boolean_and_geography_roles_need_evidence():
    stats = statistics(stat("flag", boolean_vocabulary=["no", "yes"]), stat("maybe"),
                       stat("lat", "DOUBLE", numeric=numeric(), geographic_role="latitude"), stat("place"))
    result = run_checks(stats, semantic(flag=("boolean", None, None), maybe=("boolean", None, None),
                                        lat=("geography", None, None), place=("geography", None, None)))
    failed = failed_checks(result)
    assert {(c.column, c.severity) for c in failed} == {("maybe", "error"), ("place", "warning")}


def test_category_with_too_many_distinct_values_is_a_warning():
    stats = statistics(stat("name", distinct=90), rows=100)
    result = run_checks(stats, semantic(name=("category", None, None)))
    assert names(failed_checks(result, "warning")) == ["category_cardinality"]
    assert failed_checks(result, "error") == []


def test_code_meanings_must_match_detected_codes():
    stats = statistics(stat("gender", distinct=2, codes=["F", "M"]))
    result = run_checks(stats, semantic(gender=("category", None, {"F": "female", "X": "other"})))
    assert names(failed_checks(result, "error")) == ["code_meanings_match_data"]
    assert "X" in failed_checks(result)[0].message


def test_brief_conflicts_are_warnings_not_errors():
    stats = statistics(stat("gender", distinct=2, codes=["F", "M"]), stat("price"))
    brief = DataBrief(column_descriptions={"missing": "not here"}, units={"price": "USD"},
                      code_meanings={"gender": {"F": "female", "Z": "unknown"}})
    result = run_checks(stats, semantic(gender=("category", None, None), price=("text", None, None)), brief)
    assert names(failed_checks(result)) == [
        "brief_codes_present_in_data", "brief_column_descriptions_column_exists", "brief_unit_fits_numeric_column",
    ]
    assert all(c.severity == "warning" for c in failed_checks(result))


def test_semantic_column_not_in_dataset_is_an_error():
    result = run_checks(statistics(stat("a")), semantic(b=("text", None, None)))
    assert names(failed_checks(result, "error")) == ["column_exists"]


def test_omitted_measure_is_not_penalized():
    stats = statistics(stat("shape_area", "DOUBLE", values_omitted=True))
    result = run_checks(stats, semantic(shape_area=("measure", None, None)))
    assert failed_checks(result) == []


def test_ordinal_evidence_must_be_used():
    stats = statistics(stat("wealth", measurement_levels=["nominal", "ordinal"], ordinal_pattern="poor < rich"))
    assert "ordinal_evidence_used" in names(failed_checks(run_checks(stats, semantic(wealth=("category", None, {}))), "error"))
    assert "ordinal_evidence_used" not in names(failed_checks(run_checks(stats, semantic(wealth=("ordinal", None, {})))))


def test_numeric_ordinal_evidence_rejects_measure():
    stats = statistics(stat("sequence_number", "BIGINT", numeric=numeric(),
                            measurement_levels=["interval", "discrete", "ordinal"],
                            ordinal_pattern="1 < 2 < 3"))
    result = run_checks(stats, semantic(sequence_number=("measure", None, None)))
    failed = failed_checks(result)
    assert names(failed) == ["ordinal_evidence_used"]
    assert failed[0].severity == "error"
    assert failed_checks(run_checks(stats, semantic(sequence_number=("ordinal", None, None)))) == []
