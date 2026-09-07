# vis_agent/analyst/checks.py
"""Code checks of a result against the raw data. Every fact is a DuckDB query result or a profile field."""

import re

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.profiler.models import DatasetProfile, ProfileCheck
from vis_agent.store import DatasetStore, quote_identifier

MAX_LABEL_DISTINCT = 200
OTHER_LABELS = {"other", "others", "أخرى", "اخرى", "غير ذلك"}
SHARE_TOLERANCE = 0.5     # points, when shares sum to 100; scaled down for fractions
TOTAL_TOLERANCE = 0.005   # relative difference that counts as the same total
GROUPING_KINDS = ("category", "ordinal", "time", "geography", "identifier")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _check(column, check, severity, passed, message) -> ProfileCheck:
    return ProfileCheck(column=column, check=check, severity=severity, passed=passed, message=message if not passed else "ok")


def _text(value) -> str | None:
    return None if value is None else str(value).strip()


def _numbers(values) -> list[float] | None:
    numbers = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        numbers.append(float(value))
    return numbers


def check_result(store: DatasetStore, profile: DatasetProfile, columns: list[ResultColumn],
                 result: QueryResult) -> list[ProfileCheck]:
    checks: list[ProfileCheck] = []
    if result.row_count == 0:
        checks.append(_check(None, "result_not_empty", "error", False,
                             "The query returned no rows. Reconsider the filters, or ask the caller."))
        return checks
    if [c.name for c in columns] != result.columns:
        checks.append(_check(None, "column_descriptions_match_result", "error", False,
                             f"Describe exactly the result columns, once each and in result order: {result.columns}."))
        return checks

    stats = {c.name: c for c in profile.deterministic.columns}
    semantics = {c.name: c for c in profile.semantic.columns} if profile.semantic else {}
    brief = profile.source.brief
    index = {name: i for i, name in enumerate(result.columns)}
    values_of = {c.name: [row[index[c.name]] for row in result.rows] for c in columns}
    table = quote_identifier(store.table_name(profile.source.dataset_id))
    grouping = [c for c in columns if c.kind in GROUPING_KINDS]

    with store.connect() as connection:
        for column in columns:
            values = values_of[column.name]
            source = stats.get(column.source) if column.source else None
            if column.source and source is None:
                checks.append(_check(column.name, "source_column_exists", "error", False,
                                     f"{column.name}: source {column.source!r} is not a column of this dataset."))
                continue

            if (source is not None and column.aggregate == "none" and column.kind in GROUPING_KINDS
                    and column.kind != "time" and not source.values_omitted and source.distinct_count <= MAX_LABEL_DISTINCT):
                raw = {str(v).strip() for (v,) in connection.execute(
                    f"SELECT DISTINCT CAST({quote_identifier(source.name)} AS VARCHAR) FROM {table} "
                    f"WHERE {quote_identifier(source.name)} IS NOT NULL").fetchall()}
                labels = [_text(v) for v in values]
                unknown = sorted({v for v in labels if v is not None and v not in raw and v.lower() not in OTHER_LABELS})
                if unknown:
                    siblings = [c for c in columns if c is not column and c.source == column.source
                                and all(_text(v) is None or _text(v) in raw for v in values_of[c.name])]
                    if not siblings:
                        checks.append(_check(column.name, "labels_faithful", "error", False,
                                             f"{column.name}: {unknown[:5]} are not values of {column.source}; keep the code "
                                             "column next to the label, or use the data's own labels."))
                        continue
                    known = dict((semantics[column.source].code_meanings or {}) if column.source in semantics else {})
                    if brief is not None:
                        known.update(brief.code_meanings.get(column.source, {}))
                    known = {code.strip().casefold(): meaning.strip().casefold() for code, meaning in known.items()}
                    codes = values_of[siblings[0].name]
                    wrong = sorted({f"{_text(code)!r} is labelled {_text(label)!r} but the profile says "
                                    f"{known.get(_text(code).casefold(), 'nothing')!r}"
                                    for code, label in zip(codes, labels)
                                    if code is not None and label is not None and label not in raw
                                    and known.get(_text(code).casefold()) != label.casefold()})
                    if wrong:
                        checks.append(_check(column.name, "code_labels_match_profile", "error", False,
                                             f"{column.name}: " + "; ".join(wrong[:5]) + "."))
                        continue

            numbers = _numbers(values)
            if column.kind == "share" and numbers is not None:
                groups: dict[object, float] = {}
                key_column = grouping[0].name if len(grouping) > 1 else None
                for row_index, number in enumerate(numbers):
                    key = result.rows[row_index][index[key_column]] if key_column else None
                    groups[key] = groups.get(key, 0.0) + number
                for key, total in groups.items():
                    if abs(total - 100) > SHARE_TOLERANCE and abs(total - 1) > SHARE_TOLERANCE / 100:
                        where = f" for {key!r}" if key_column else ""
                        checks.append(_check(column.name, "shares_add_up", "warning", False,
                                             f"{column.name}: shares sum to {total:.1f}{where}, not 100. Fine when the share "
                                             "is within each row's own group; otherwise include every group or an Other row."))
                        break

            if (column.kind in ("measure", "share") and numbers is not None and source is not None
                    and source.numeric is not None and column.aggregate in ("avg", "min", "max")):
                low, high = source.numeric.minimum, source.numeric.maximum
                if low is not None and high is not None:
                    outside = [n for n in numbers if n < low - 1e-9 or n > high + 1e-9]
                    if outside:
                        checks.append(_check(column.name, "aggregate_in_bounds", "error", False,
                                             f"{column.name}: {column.aggregate} of {column.source} is {outside[0]:g} but the "
                                             f"column ranges {low:g} to {high:g}."))

            if column.kind == "measure" and numbers is not None and column.aggregate in ("sum", "count"):
                if column.aggregate == "sum" and source is not None and source.numeric is not None:
                    name = quote_identifier(source.name)
                    number = f"CAST({name} AS DOUBLE)"
                    if source.physical_type == "VARCHAR":
                        # Arabic-digit text sums after the same normalisation the profiler measured it with.
                        digits = f"translate(CAST({name} AS VARCHAR), '٠١٢٣٤٥٦٧٨٩٫٬', '0123456789.,')"
                        number = f"TRY_CAST(replace({digits}, ',', '') AS DOUBLE)"
                    (raw_total,) = connection.execute(f"SELECT sum({number}) FROM {table}").fetchone()
                elif column.aggregate == "count":
                    raw_total = (profile.deterministic.row_count - source.null_count) if source is not None \
                        else profile.deterministic.row_count
                else:
                    raw_total = None
                if raw_total:
                    total = sum(numbers)
                    if abs(total - raw_total) > TOTAL_TOLERANCE * abs(raw_total):
                        checks.append(_check(column.name, "total_explained", "warning", False,
                                             f"{column.name}: the result sums to {total:g}; the column's total is "
                                             f"{raw_total:g}. The query filtered or excluded rows."))

            if column.kind == "time":
                present = [v for v in values if v is not None]
                # Fixed-width YYYY and YYYY-MM text sorts chronologically, including Hijri 13xx/14xx.
                # Keep these buckets as text instead of interpreting them as Gregorian dates.
                if present != sorted(present, key=lambda v: (isinstance(v, str), v)):
                    checks.append(_check(column.name, "time_in_order", "warning", False,
                                         f"{column.name}: time is not in chronological order."))
    return checks


def summary_numbers_exist(summary: str, result: QueryResult, context: str = "") -> ProfileCheck:
    """Every number written in the summary, in Western or Arabic-Indic digits, must exist in the result.

    Numbers that also appear in the context (the question and the result's column names) are wording, not
    claims: "under 15", "December 2025", "drivers over 25".
    """
    candidates: set[float] = {float(result.row_count)}
    for token in NUMBER.findall(context.translate(ARABIC_DIGITS)):
        candidates.add(float(token.replace(",", "")))
    for row in result.rows:
        for value in row:
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, float)):
                candidates.add(float(value))
                if 0 <= value <= 1:
                    candidates.add(float(value) * 100)
            else:
                for token in NUMBER.findall(str(value).translate(ARABIC_DIGITS)):
                    candidates.add(float(token.replace(",", "")))
    for token in NUMBER.findall(summary.translate(ARABIC_DIGITS)):
        decimals = len(token.split(".")[1]) if "." in token else 0
        number = float(token.replace(",", ""))
        if not any(abs(round(candidate, decimals) - number) < 1e-9 for candidate in candidates):
            return _check(None, "summary_numbers_exist", "error", False,
                          f"The summary mentions {token}, which is not in the result. Use only numbers from the result.")
    return _check(None, "summary_numbers_exist", "error", True, "ok")
