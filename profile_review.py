"""Code checks of an interpretation against the measurements and the brief."""

from profile_models import DataBrief, DeterministicProfile, ProfileCheck, SemanticProfile

TIME_TYPES = ("DATE", "TIMESTAMP", "TIME")
IDENTIFIER_UNIQUENESS = 0.95
CATEGORY_MAX_SHARE = 0.5
CATEGORY_MIN_ROWS = 50


def _check(column: str | None, check: str, severity: str, passed: bool, message: str) -> ProfileCheck:
    return ProfileCheck(column=column, check=check, severity=severity, passed=passed,
                        message=message if not passed else "ok")


def run_checks(statistics: DeterministicProfile, semantic: SemanticProfile,
               brief: DataBrief | None = None) -> list[ProfileCheck]:
    checks: list[ProfileCheck] = []
    stats_by_name = {column.name: column for column in statistics.columns}

    for column in semantic.columns:
        stats = stats_by_name.get(column.name)
        if stats is None:
            checks.append(_check(column.name, "column_exists", "error", False,
                                 f"{column.name}: not a column of this dataset."))
            continue
        non_null = statistics.row_count - stats.null_count
        if column.role == "time":
            checks.append(_check(
                column.name, "time_role_has_time_statistics", "error",
                stats.physical_type.startswith(TIME_TYPES) or stats.ordinal_pattern is not None,
                f"{column.name}: role is time but the column is {stats.physical_type} with no date statistics.",
            ))
        if column.role == "identifier":
            checks.append(_check(
                column.name, "identifier_is_near_unique", "error",
                non_null == 0 or stats.distinct_count >= IDENTIFIER_UNIQUENESS * non_null,
                f"{column.name}: role is identifier but only {stats.distinct_count} of {non_null} values are distinct.",
            ))
        if column.role == "measure":
            checks.append(_check(
                column.name, "measure_is_numeric", "error", stats.numeric is not None or stats.values_omitted,
                f"{column.name}: role is measure but the column has no numeric statistics.",
            ))
        if column.unit is not None and column.role != "measure":
            checks.append(_check(
                column.name, "unit_only_on_measures", "error", False,
                f"{column.name}: has unit {column.unit!r} but role is {column.role}.",
            ))
        if column.role == "boolean":
            checks.append(_check(
                column.name, "boolean_role_has_vocabulary", "error",
                stats.physical_type == "BOOLEAN" or stats.boolean_vocabulary is not None,
                f"{column.name}: role is boolean but the values are not a yes/no vocabulary.",
            ))
        if column.role == "geography":
            checks.append(_check(
                column.name, "geography_role_has_geographic_evidence", "warning",
                stats.geographic_role is not None,
                f"{column.name}: role is geography but no coordinates, WKT, or place-name column was detected.",
            ))
        if "ordinal" in stats.measurement_levels and column.role in ("category", "text", "measure"):
            checks.append(_check(
                column.name, "ordinal_evidence_used", "error", False,
                f"{column.name}: the values form an ordered scale ({stats.ordinal_pattern}); use the ordinal role.",
            ))
        if (column.role == "category" and non_null > CATEGORY_MIN_ROWS
                and stats.distinct_count > CATEGORY_MAX_SHARE * non_null):
            checks.append(_check(
                column.name, "category_cardinality", "warning", False,
                f"{column.name}: role is category but {stats.distinct_count} distinct values in {non_null} rows "
                "looks like an identifier or free text.",
            ))
        if column.code_meanings and stats.codes is not None:
            unknown = sorted(set(column.code_meanings) - set(stats.codes))
            checks.append(_check(
                column.name, "code_meanings_match_data", "error", not unknown,
                f"{column.name}: code meanings mention codes not in the data: {', '.join(unknown)}.",
            ))

    if brief is not None:
        names = set(stats_by_name)
        for section, mapping in (("column_descriptions", brief.column_descriptions),
                                 ("units", brief.units), ("code_meanings", brief.code_meanings)):
            for missing in sorted(set(mapping) - names):
                checks.append(_check(
                    missing, f"brief_{section}_column_exists", "warning", False,
                    f"The brief describes column {missing!r} in {section}, but the dataset has no such column.",
                ))
        for name, codes in brief.code_meanings.items():
            stats = stats_by_name.get(name)
            if stats is not None and stats.codes is not None:
                unknown = sorted(set(codes) - set(stats.codes))
                checks.append(_check(
                    name, "brief_codes_present_in_data", "warning", not unknown,
                    f"{name}: the brief gives meanings for codes not present in the data: {', '.join(unknown)}.",
                ))
        for name, unit in brief.units.items():
            stats = stats_by_name.get(name)
            if stats is not None:
                checks.append(_check(
                    name, "brief_unit_fits_numeric_column", "warning", stats.numeric is not None,
                    f"{name}: the brief gives unit {unit!r} but the column is {stats.physical_type}, not numeric.",
                ))
    return checks


def failed_checks(checks: list[ProfileCheck], severity: str | None = None) -> list[ProfileCheck]:
    return [c for c in checks if not c.passed and (severity is None or c.severity == severity)]
