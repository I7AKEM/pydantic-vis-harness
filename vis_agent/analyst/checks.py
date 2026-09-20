# vis_agent/analyst/checks.py
"""Code checks of a result against the raw data. Every fact is a DuckDB query result or a profile field."""

import json
import math
import re

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.profiler.models import DatasetProfile, ProfileCheck
from vis_agent.store import DatasetStore, quote_identifier
from vis_agent.units import COUNT_UNITS, canonical_unit

MAX_LABEL_DISTINCT = 200
OTHER_LABELS = {"other", "others", "أخرى", "اخرى", "غير ذلك"}
SHARE_TOLERANCE = 0.5     # points, when shares sum to 100; scaled down for fractions
TOTAL_TOLERANCE = 0.005   # relative difference that counts as the same total
GROUPING_KINDS = ("category", "ordinal", "time", "geography", "identifier")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_DECREASE = r"decreas(?:e|ed|es)|declin(?:e|ed|es)|drop(?:ped|s)?|fall(?:en|s)?|fell|reduction|reduced"
_INCREASE = r"increas(?:e|ed|es)|rise(?:n|s)?|rose|growth|grew|gain(?:ed|s)?"
_ARABIC_DECREASE = r"انخفض(?:ت)?|انخفاض|بانخفاض|الانخفاض|تراجع(?:ت)?|بتراجع|هبط(?:ت)?|هبوط"
_ARABIC_INCREASE = r"ارتفع(?:ت)?|ارتفاع|بارتفاع|الارتفاع|زاد(?:ت)?|زيادة|بزيادة|نمو"
_CHANGE_BEFORE = re.compile(
    rf"(?<!\w)(?P<down>{_DECREASE})\s+(?:(?:by|of)\s+)?(?:(?:about|approximately|roughly)\s+)?$|"
    rf"(?<!\w)(?P<up>{_INCREASE})\s+(?:(?:by|of)\s+)?(?:(?:about|approximately|roughly)\s+)?$|"
    rf"(?<!\w)(?P<ar_down>{_ARABIC_DECREASE})\s+(?:[^\W\d_]+\s+){{0,4}}(?:بنسبة|بمقدار|بواقع)\s*$|"
    rf"(?<!\w)(?P<ar_up>{_ARABIC_INCREASE})\s+(?:[^\W\d_]+\s+){{0,4}}(?:بنسبة|بمقدار|بواقع)\s*$",
    re.IGNORECASE,
)
_CHANGE_AFTER = re.compile(
    rf"^\s*(?:[%٪]|percent(?:age)?(?:\s+points?)?)?\s*(?:(?P<down>{_DECREASE})|(?P<up>{_INCREASE}))\b",
    re.IGNORECASE,
)
_NEGATED_CHANGE = re.compile(r"\b(?:not|no|never|without|\w+n['’]t|لم|لن|لا|ليس|دون|غير)\b", re.IGNORECASE)


def numeric_mention_direction(text: str, start: int, end: int) -> int | None:
    """Read a local change phrase: -1 decrease, +1 increase, 0 contradictory, None ordinary.

    This recognizes bounded magnitude wording, not arbitrary sentence meaning. In particular,
    'fell to 80' is an ordinary level, while 'fell by 80' asserts a signed change. A caller must
    compare a directional mention with actual signed numeric results, never an absolute-value pool.
    """
    before = re.sub(r"[\u064b-\u065f\u0670ـ]", "", text[:start])
    explicit_plus = before.endswith("+")
    if explicit_plus:
        before = before[:-1]
    prefix = _CHANGE_BEFORE.search(before)
    suffix = _CHANGE_AFTER.match(text[end:])
    found = [match for match in (prefix, suffix) if match]
    if not found:
        return None
    directions = {-1 if match.groupdict().get("down") or match.groupdict().get("ar_down") else 1 for match in found}
    # Reject negation near the predicate; do not turn 'did not decrease' into a decrease.
    predicate_start = prefix.start() if prefix else max(0, len(before) - 80)
    local = before[max(0, predicate_start - 40):]
    if len(directions) != 1 or _NEGATED_CHANGE.search(local) or text[start:end].startswith("-"):
        return 0
    direction = directions.pop()
    return 0 if explicit_plus and direction == -1 else direction

SHARE_UNITS = frozenset({"%", "٪", "percent", "percentage", "pct", "نسبة", "نسبة مئوية", "بالمئة"})
YEAR = re.compile(r"(?<!\d)(1[3-4]\d{2}|19\d{2}|20\d{2})(?!\d)")
ORDER_BY = re.compile(r"\border\s+by\s+(.+?)(?:\s+limit\b|\s*;?\s*$)", re.IGNORECASE | re.DOTALL)
WORD = re.compile(r"\w+")
STOP_WORDS = frozenset("""a an the of in on for by to and or is are was were do does did you mean want which what
how many much please هل تقصد ما ماذا هو هي في من على عن أم أو و ب ل كم تريد المقصود""".split())


def numbers_in(text: str) -> set[str]:
    """Every number written in the text, Western or Arabic-Indic digits, thousands separators removed."""
    return {token.replace(",", "") for token in NUMBER.findall(text.translate(ARABIC_DIGITS))}


def normalise_units(column: ResultColumn) -> ResultColumn:
    """One convention for the checks and the designer: a declared percent alias is %, a generic count marker is no
    unit. A share with no unit stays as written: the analyst must declare its scale (% or fraction), and the
    share_scale_declared check sends it back, because code cannot tell a 0-1 ratio from a 0-100 percentage."""
    unit = column.unit.strip() if column.unit and column.unit.strip() else None
    if unit is not None and column.kind == "share" and unit.casefold() in SHARE_UNITS:
        unit = "%"
    elif unit is not None and unit.casefold() in COUNT_UNITS:
        unit = None
    return column if unit == column.unit else column.model_copy(update={"unit": unit})


def years_named(text: str) -> set[str]:
    """Four-digit years in the text, Gregorian or Hijri, in either digit system."""
    return set(YEAR.findall(text.translate(ARABIC_DIGITS)))


def named_period_check(question: str, sql: str, assumptions: list[str]) -> ProfileCheck:
    """A year the question names must appear in the SQL, or an assumption must say why it does not."""
    missing = sorted(years_named(question) - years_named(sql) - years_named(" ".join(assumptions)))
    if missing:
        return _check(None, "named_period_missing", "warning", False,
                      f"The question names {', '.join(missing)}; the SQL does not filter on it and no assumption "
                      "says why. Filter on the period, or record the assumption.")
    return _check(None, "named_period_missing", "warning", True, "ok")


def restates(clarification: str, question: str) -> bool:
    """True when the clarification adds no word the question did not already hold: it repeats, it does not ask."""
    asked = {word.casefold() for word in WORD.findall(clarification)} - STOP_WORDS
    known = {word.casefold() for word in WORD.findall(question)}
    return bool(asked) and asked <= known


def _orders_descending(sql: str, column: ResultColumn) -> bool:
    """True when the statement's first sort key is this column, descending: a reversed time axis is a choice."""
    match = ORDER_BY.search(sql)
    if not match:
        return False
    parts = match.group(1).split(",")[0].strip().split()
    if len(parts) < 2 or parts[-1].casefold() != "desc":
        return False
    key = " ".join(parts[:-1]).strip('"').split(".")[-1].strip('"').casefold()
    return key in {column.name.casefold(), (column.source or "").casefold()}


def _check(column, check, severity, passed, message) -> ProfileCheck:
    return ProfileCheck(column=column, check=check, severity=severity, passed=passed, message=message if not passed else "ok")


def _text(value) -> str | None:
    return None if value is None else str(value).strip()


def _numbers(values) -> list[float] | None:
    numbers = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        numbers.append(float(value))
    return numbers


def _share_partition_check(connection, column: ResultColumn, columns: list[ResultColumn],
                           result: QueryResult) -> ProfileCheck | None:
    """Only test an explicitly declared complete partition, using its declared scale and groups."""
    if column.partition_by is None:
        return None
    by_name = {c.name: c for c in columns}
    invalid = [name for name in column.partition_by
               if name not in by_name or by_name[name].kind not in GROUPING_KINDS]
    if invalid:
        return _check(column.name, "share_partition_columns", "error", False,
                      f"{column.name}: partition_by must name result grouping columns; invalid: {invalid}.")
    if result.row_count != len(result.rows):
        return _check(column.name, "share_partition_incomplete", "warning", False,
                      f"{column.name}: the result is truncated; its complete partition cannot be checked.")
    unit = (canonical_unit(column.unit) or "").strip().casefold()
    target = 100 if unit == "%" else 1 if unit == "fraction" else None
    if target is None:
        return _check(column.name, "share_partition_scale", "warning", False,
                      f"{column.name}: a complete partition needs unit % or explicit unit fraction; its scale is unknown.")
    index = result.columns.index(column.name)
    if _numbers([row[index] for row in result.rows]) is None:
        return _check(column.name, "share_partition_values", "warning", False,
                      f"{column.name}: the declared partition includes missing or nonfinite numeric values.")
    # The saved, bounded result is the object being checked, not a fresh execution of the analyst's SQL.
    # Column indices come from validated metadata; cell values are supplied as a JSON parameter.
    groups = [f"json_extract(value, '$[{result.columns.index(name)}]')" for name in column.partition_by]
    measure = f"CAST(json_extract(value, '$[{index}]') AS DOUBLE)"
    selected = ", ".join([*groups, f"sum({measure})"])
    grouped = " GROUP BY " + ", ".join(str(i + 1) for i in range(len(groups))) if groups else ""
    totals = connection.execute(f"SELECT {selected} FROM json_each(?)" + grouped,
                                [json.dumps(result.rows, ensure_ascii=False, allow_nan=False)]).fetchall()
    for *keys, total in totals:
        if total is None or abs(total - target) > SHARE_TOLERANCE * target / 100:
            scope = f" for {dict(zip(column.partition_by, keys))}" if keys else ""
            return _check(column.name, "shares_add_up", "warning", False,
                          f"{column.name}: the declared complete partition sums to {total:g}{scope}, not {target}. "
                          "Include every part or Other, or use partition_by null if this is a partial selection or row rate.")
    return None


def check_result(store: DatasetStore, profile: DatasetProfile, columns: list[ResultColumn],
                 result: QueryResult, *, table_name: str | None = None) -> list[ProfileCheck]:
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
    table = quote_identifier(table_name or store.table_name(profile.source.dataset_id))

    with store.connect() as connection:
        for column in columns:
            values = values_of[column.name]
            source = stats.get(column.source) if column.source else None
            if column.source and source is None:
                checks.append(_check(column.name, "source_column_exists", "error", False,
                                     f"{column.name}: source {column.source!r} is not a column of this dataset. "
                                     "Use one exact source column name, or source null when computed from several columns; "
                                     "never join names with commas or write an expression in source."))
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
            if column.kind == "share":
                unit = canonical_unit(column.unit)
                upper = 100 if unit == "%" else 1 if unit == "fraction" else None
                if upper is not None and numbers:
                    low, high = connection.execute(
                        "SELECT min(value), max(value) FROM unnest(?::DOUBLE[]) AS shares(value)",
                        [numbers]).fetchone()
                    if low < -upper * 1e-9 or high > upper + upper * 1e-9:
                        checks.append(_check(column.name, "share_in_bounds", "error", False,
                                             f"{column.name}: a part-of-whole share must be between 0 and {upper}; "
                                             f"the result ranges from {low:g} to {high:g}. Correct the calculation, "
                                             "or use kind measure with unit % if this is a percentage change, not a share."))
                partition_check = _share_partition_check(connection, column, columns, result)
                if partition_check is not None:
                    checks.append(partition_check)

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
                        if re.search(r"\bwhere\b", result.sql, re.IGNORECASE):
                            # A filter the query states is not a leak: say what the number covers.
                            message = (f"{column.name}: the result covers {total:g} of the column's total {raw_total:g}, "
                                       f"because the query keeps only the rows its WHERE clause names; expected when the "
                                       f"question asks for a subset.")
                        else:
                            message = (f"{column.name}: the result sums to {total:g}; the column's total is {raw_total:g}. "
                                       f"The query dropped rows without a filter the question named.")
                        checks.append(_check(column.name, "total_explained", "warning", False, message))

            if (source is not None and source.ordinal_pattern and column.aggregate == "none"
                    and column.kind in GROUPING_KINDS and column.kind != "time"):
                # The profiler measured the scale ("under 15 < 15-30 < ... < over 60"); the result must follow it,
                # not the text order, which puts digits before letters. Check the sequence inside the grouping
                # columns that precede this ordinal column. A derived one-row-per-group label (for example the
                # dominant education for each city and wealth band) has no ordinal sequence to validate.
                levels = source.ordinal_pattern.split(" < ")
                ordinal_index = index[column.name]
                partition_indices = [
                    index[other.name] for other in columns[:ordinal_index]
                    if other.kind in GROUPING_KINDS
                ]
                partitions: dict[tuple, list[str]] = {}
                for row in result.rows:
                    value = row[ordinal_index]
                    if value is None:
                        continue
                    key = tuple(row[i] for i in partition_indices)
                    seen = partitions.setdefault(key, [])
                    if str(value) not in seen:
                        seen.append(str(value))
                out_of_order = False
                for seen in partitions.values():
                    if len(seen) > 1 and all(value in levels for value in seen):
                        positions = [levels.index(value) for value in seen]
                        if positions != sorted(positions):
                            out_of_order = True
                            break
                if out_of_order:
                    when = " ".join(f"WHEN {level!r} THEN {i + 1}" for i, level in enumerate(levels))
                    checks.append(_check(column.name, "ordinal_in_order", "error", False,
                                         f"{column.name}: the rows do not follow the column's scale "
                                         f"{source.ordinal_pattern}. Order by the scale within each preceding group, "
                                         f"not by text: ORDER BY CASE {quote_identifier(source.name)} {when} END."))

            if column.kind == "time":
                present = [v for v in values if v is not None]
                # Fixed-width YYYY and YYYY-MM text sorts chronologically, including Hijri 13xx/14xx.
                # Keep these buckets as text instead of interpreting them as Gregorian dates.
                if present != sorted(present, key=lambda v: (isinstance(v, str), v)):
                    reversed_on_purpose = _orders_descending(result.sql, column)
                    checks.append(_check(column.name, "time_in_order", "error" if reversed_on_purpose else "warning", False,
                                         f"{column.name}: time is not in chronological order."
                                         + (f" Order it ascending: ORDER BY {quote_identifier(column.name)} ASC."
                                            if reversed_on_purpose else "")))
    return checks


def summary_numbers_exist(summary: str, result: QueryResult, context: str = "") -> ProfileCheck:
    """Every number written in the summary, in Western or Arabic-Indic digits, must exist in the result.

    Numbers that also appear in the context (the question and the result's column names) are wording, not
    claims: "under 15", "December 2025", "drivers over 25".
    """
    candidates: set[float] = {float(result.row_count)}
    signed_results: set[float] = set()
    for token in NUMBER.findall(context.translate(ARABIC_DIGITS)):
        candidates.add(float(token.replace(",", "")))
    for row in result.rows:
        for value in row:
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, float)):
                candidates.add(float(value))
                signed_results.add(float(value))
                if 0 <= value <= 1:
                    candidates.add(float(value) * 100)
            else:
                for token in NUMBER.findall(str(value).translate(ARABIC_DIGITS)):
                    candidates.add(float(token.replace(",", "")))
    normalized = summary.translate(ARABIC_DIGITS)
    for mention in NUMBER.finditer(normalized):
        token = mention.group()
        decimals = len(token.split(".")[1]) if "." in token else 0
        number = float(token.replace(",", ""))
        direction = numeric_mention_direction(normalized, mention.start(), mention.end())
        pool = candidates if direction is None else signed_results
        if direction:
            number *= direction
        if direction == 0 or not any(abs(round(candidate, decimals) - number) < 1e-9 for candidate in pool):
            return _check(None, "summary_numbers_exist", "error", False,
                          f"The summary mentions {token}, which is not in the result. Use only numbers from the result.")
    return _check(None, "summary_numbers_exist", "error", True, "ok")
