"""Bind and transform a checked spec's result into GPT-Vis renderer options."""

import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import duckdb

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.labels import value_key
from vis_agent.units import canonical_unit, display_unit

from .catalogue import CATALOGUE
from .fold import fold
from .indicator_text import resolve_cards
from .models import Compromise, NumberFormat, Spec
from .rules import ACCENT, ADDITIVE, BARS, COLUMNS
from .syntax import parse_format

LANGUAGE_DEFAULTS = {
    "ar": {"other": "أخرى", "unknown": "غير معروف", "direction": "rtl", "count": "العدد"},
    "en": {"other": "Other", "unknown": "Unknown", "direction": "ltr", "count": "Count"},
}
TRENDS = {"line", "multi_line", "area", "stacked_area"}
MEASURES = {"value", "value2", "x", "y"}
WITHOUT_AXES = {"pie", "donut", "treemap", "radar", "word_cloud", "table", "indicator"}
SINGLE_SERIES = {"column", "bar", "line", "area", "scatter", "histogram", "boxplot"}
# Pinned S2 TableSheet: 30px header/rows, 2px header border and 6px
# scrollbar reservation. Its SSR autoFit crops blank space; it cannot expand
# the viewport to include hidden rows. Static PNGs must not need scrolling.
TABLE_ROW_HEIGHT = 30
TABLE_HEADER_AND_FRAME_HEIGHT = 38
MAX_TABLE_HEIGHT = 2400
ISO_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?", re.ASCII)
GREGORIAN_ISO = re.compile(
    r"(?:1[6-9]|2\d)\d{2}(?:-\d{2}(?:-\d{2})?)?(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?", re.ASCII,
)


@dataclass
class Resolved:
    config: dict
    overrides: dict
    number: NumberFormat
    compromises: list[Compromise]
    drawn_rows: int
    folded_rows: int
    dropped_rows: int
    width: int
    height: int
    number2: NumberFormat | None = None
    table_formats: dict[str, dict] = field(default_factory=dict)
    display: dict = field(default_factory=dict)


class ResolveError(Exception):
    """Result cells cannot be faithfully resolved into chart records."""


def _shorten_time(records: list[dict], role: str) -> dict[str, str]:
    """Use one precision for the entire axis, preserving each timestamp's local time."""
    values = [record[role] for record in records]
    if not values or not all(isinstance(value, str) and ISO_DATE_TIME.fullmatch(value) for value in values):
        return {}
    # Hijri-looking years and non-ASCII/month-name text keep the whole axis verbatim.
    if any(int(value[:4]) < 1600 for value in values):
        return {}
    try:
        dates = [datetime.fromisoformat(value) for value in values]
    except ValueError:
        return {}
    patterns = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"]
    if all((date.hour, date.minute, date.second, date.microsecond) == (0, 0, 0, 0) for date in dates):
        patterns.insert(0, "%Y-%m-%d")
        if all(date.day == 1 for date in dates):
            patterns.insert(0, "%Y-%m")
            if all(date.month == 1 for date in dates):
                patterns.insert(0, "%Y")
    distinct = len(set(values))
    for pattern in patterns:
        labels = [date.strftime(pattern) for date in dates]
        if len(set(labels)) == distinct:
            return dict(zip(values, labels))
    # Zones or source precision beyond microseconds may require the original text.
    return {}


def _column_unit(column: ResultColumn | None) -> str | None:
    unit = column.unit if column is not None else None
    return display_unit(unit)


def _bind(spec: Spec, result: QueryResult, unknown: str) -> tuple[list[dict], int]:
    indices = {role: result.columns.index(name) for role, name in spec.bind.items()}
    records = []
    dropped = 0
    for i, row in enumerate(result.rows):
        record = {}
        missing_value = False
        for role, index in indices.items():
            cell = row[index]
            if role in MEASURES:
                if cell is None:
                    missing_value = True
                elif isinstance(cell, str):
                    raise ResolveError(
                        f"column {spec.bind[role]!r} holds text in row {i}; a measure must be numeric"
                    )
                elif isinstance(cell, bool) or not isinstance(cell, (int, float)):
                    raise ResolveError(
                        f"column {spec.bind[role]!r} holds a nonnumeric value in row {i}; a measure must be numeric"
                    )
            elif cell is None:
                cell = unknown
            record[role] = cell
        if missing_value:
            dropped += 1
        else:
            records.append(record)
    return records, dropped


def _totals(records: list[dict], axis: str) -> dict:
    totals = {}
    for record in records:
        label = record[axis]
        totals[label] = totals.get(label, 0) + record["value"]
    return totals


def _chronological(records: list[dict], axis: str) -> list[dict]:
    """Gregorian time text goes in time order whatever order the analyst returned; other time text keeps it."""
    if records and all(GREGORIAN_ISO.fullmatch(value_key(record[axis])) for record in records):
        return sorted(records, key=lambda record: value_key(record[axis]))
    return records


def _sort(records: list[dict], order: str, axis: str | None, grouped: bool) -> list[dict]:
    if order == "none":
        return records
    field, direction = order.split()
    if field == "category":
        return sorted(records, key=lambda r: value_key(r[axis]), reverse=direction == "desc")
    if grouped and axis is not None:
        totals = _totals(records, axis)
        categories = sorted(totals, key=totals.get, reverse=direction == "desc")
        positions = {label: i for i, label in enumerate(categories)}
        return sorted(records, key=lambda r: positions[r[axis]])
    return sorted(records, key=lambda r: r["value"], reverse=direction == "desc")


def _fold(records: list[dict], axis: str, limit: int, other: str) -> tuple[list[dict], int]:
    categories = list(dict.fromkeys(r[axis] for r in records))
    kept = set(categories[:limit])
    head = []
    tail = {}
    folded = 0
    for record in records:
        if record[axis] in kept:
            head.append(record)
            continue
        folded += 1
        group = record.get("group")
        if group not in tail:
            tail[group] = {axis: other, **({"group": group} if "group" in record else {})}
        # Dual axes may bind two additive measures; keep both series aligned.
        for role in ("value", "value2"):
            if role in record:
                tail[group][role] = tail[group].get(role, 0) + record[role]
    return head + list(tail.values()), folded


def _histogram(records: list[dict], bins: int, digits: str) -> list[dict]:
    """Measure bounds and counts in DuckDB; write unitless range labels in Python."""
    if bins < 1:
        raise ResolveError("binNumber must be positive.")
    with duckdb.connect(config={"threads": 1}) as connection:
        measured = connection.execute("""
            WITH cells AS (SELECT unnest(?::DOUBLE[]) AS value),
            bounds AS (SELECT min(value) AS minimum, max(value) AS maximum FROM cells),
            bins AS (
                SELECT i,
                       minimum + (maximum - minimum) * i / ? AS low,
                       CASE WHEN i = ? - 1 THEN maximum
                            ELSE minimum + (maximum - minimum) * (i + 1) / ? END AS high,
                       maximum
                FROM bounds, range(CASE WHEN minimum = maximum THEN 1 ELSE ? END) AS slots(i)
                WHERE minimum IS NOT NULL
            )
            SELECT low, high, count(value),
                   (SELECT (maximum - minimum) / ? FROM bounds) AS width
            FROM bins LEFT JOIN cells
              ON value >= low AND (value < high OR (high = maximum AND value = maximum))
            GROUP BY i, low, high ORDER BY i
        """, [[r["value"] for r in records], bins, bins, bins, bins, bins]).fetchall()

    if not measured:
        return []
    if len({(low, high) for low, high, _, _ in measured}) != len(measured):
        raise ResolveError("Bin boundaries coincide at numeric precision; reduce binNumber.")
    width = measured[0][3]
    decimals = max(2, 1 - Decimal(str(width)).adjusted()) if width > 0 else 2
    # Keep shared grouping, rounding, digit shapes, and trimming with finer precision as needed.
    number = NumberFormat(digits=digits)

    def label(value):
        # JS toFixed rounds exact half ties away from zero, unlike Python's format.
        if value.is_integer():
            text = f"{int(value):,}"
        else:
            rounded = Decimal(value).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
            text = f"{rounded:,f}".rstrip("0").rstrip(".")
        if number.digits == "arabic":
            text = text.translate(str.maketrans("0123456789,.", "٠١٢٣٤٥٦٧٨٩٬٫"))
        return text

    while True:
        labelled = [{"category": f"{label(low)}–{label(high)}", "value": count}
                    for low, high, count, _ in measured]
        if len({row["category"] for row in labelled}) == len(labelled):
            return labelled
        decimals += 1


def _names(title: str | None, column: ResultColumn | None) -> bool:
    """True when the title carries the column's name or meaning."""
    if not title or column is None:
        return False
    text = title.casefold()
    meaning = column.meaning.strip().casefold()
    return column.name.casefold() in text or (bool(meaning) and meaning in text)


def resolve(spec: Spec, columns: list[ResultColumn], result: QueryResult) -> Resolved:
    """Resolve a checked spec, retaining row counts and render-time compromises."""
    entry = CATALOGUE.get(spec.type)
    if spec.type == "indicator" and spec.fold:
        raise ResolveError("An indicator does not accept fold; bind its complete single row with cards.")
    folded_labels = {}
    if spec.fold:
        folded_labels = {column.name: spec.column_labels.get(column.name, column.meaning.strip() or column.name)
                         for column in columns if column.name in spec.fold}
        folded = fold(columns, result, spec.fold, spec.language)
        columns, result = folded.columns, folded.result
        spec = spec.model_copy(update={"bind": {**spec.bind, "group": folded.series, "value": folded.value}})
    defaults = LANGUAGE_DEFAULTS[spec.language]
    number = parse_format(spec.format) if spec.format is not None else NumberFormat()
    number.digits = spec.digits
    height = spec.height if spec.height is not None else 450
    by_name = {column.name: column for column in columns}
    if spec.type == "indicator":
        try:
            cards = resolve_cards(spec, columns, result)
        except ValueError as error:
            raise ResolveError(str(error)) from error
        width = spec.width if spec.width is not None else (460 if len(cards) == 1 else 800)
        config = {"type": "indicator", "cards": cards, "width": width,
                  "height": spec.height, "theme": spec.theme,
                  "language": spec.language, "direction": spec.direction or defaults["direction"],
                  "title": spec.title, "subtitle": spec.subtitle, "description": spec.description,
                  "background": spec.background_color, "accent": spec.palette[0] if spec.palette else None}
        return Resolved(config, {}, number, [], 1, 0, 0, width, height)
    if spec.type == "table":
        required_height = TABLE_HEADER_AND_FRAME_HEIGHT + TABLE_ROW_HEIGHT * len(result.rows)
        if required_height > MAX_TABLE_HEIGHT:
            raise ResolveError(
                f"The complete {len(result.rows)}-row table needs {required_height}px height, exceeding the "
                f"{MAX_TABLE_HEIGHT}px static-table limit. No rows were sampled or omitted. "
                "Deliver the complete source table without a PNG, or explicitly request a smaller table."
            )
        if spec.height is None:
            height = max(height, required_height)
        elif height < required_height or height > MAX_TABLE_HEIGHT:
            raise ResolveError(
                f"height {height} cannot faithfully render the complete {len(result.rows)}-row static table. "
                f"Omit height for automatic sizing, or use height {required_height}–{MAX_TABLE_HEIGHT}; "
                "a PNG cannot scroll to hidden rows."
            )
        table_columns = [by_name[name] for name in result.columns]
        headers = [spec.column_labels.get(column.name, column.meaning.strip() or column.name)
                   for column in table_columns]
        # Sixteen pixels a character, sixty characters at most: a long Arabic header widens the table instead of
        # being cut by the package; two short headers stay at the old 800.
        width = spec.width if spec.width is not None else max(
            800, 40 + sum(max(140, 16 * min(len(header), 60)) for header in headers))
        table_formats = {column.name: NumberFormat(unit=_column_unit(column), digits=spec.digits).model_dump()
                         for column in table_columns if column.kind in {"measure", "share"}}
        config = {
            "type": entry.draw.type,
            "data": [dict(zip(result.columns, row)) for row in result.rows],
            "columns": result.columns, "width": width, "height": height,
        }
        compromises = [Compromise(key=key, message="tables are drawn as the package draws them")
                       for key in ("labels", "legend") if getattr(spec, key) == "on"]
        long_headers = [header for header in headers if len(header) > 24]
        if long_headers:
            compromises.append(Compromise(key="headers", message=f"{len(long_headers)} long table headers may be "
                                                                  "shortened by the package: " + "; ".join(long_headers[:3])))
        return Resolved(config, {}, number, compromises, len(result.rows), 0, 0, width, height,
                        table_formats=table_formats,
                        display={"fields": spec.value_labels, "columns": dict(zip(result.columns, headers)),
                                 "timeFields": [column.name for column in table_columns if column.kind == "time"]})

    binding = {role: by_name[name] for role, name in spec.bind.items()}
    axis = "time" if "time" in binding else "category" if "category" in binding else None
    records, dropped = _bind(spec, result, spec.unknown if spec.unknown is not None else defaults["unknown"])
    display = {"fields": {}, "columns": {entry.fields[role]: spec.column_labels.get(column.name, column.name)
                                         for role, column in binding.items()}}
    for role, column in binding.items():
        labels = {}
        if role == "time" or (role in {"category", "group"} and column.kind == "time"):
            labels.update(_shorten_time(records, role))
        if role not in MEASURES:
            labels.update(spec.value_labels.get(column.name, {}))
        if folded_labels and column.name == folded.series:
            # A single-row comparison can also bind the generated series column
            # as category. Its source column labels must localize both surfaces.
            labels.update(folded_labels)
        if role not in MEASURES:
            display["fields"][entry.fields[role]] = labels
    compromises = []
    if dropped:
        compromises.append(Compromise(key="bind", message=f"Dropped {dropped} rows with null measures."))

    ordered = axis is not None and binding[axis].kind in {"time", "ordinal"}
    order = spec.sort or ("none" if ordered or axis is None else "value desc")
    if order != "none" and order.split()[0] not in binding:
        raise ResolveError("The sort target must be a bound role; remove the sort.")
    records = _sort(records, order, axis, "group" in binding)
    if order == "none" and axis is not None and (axis == "time" or binding[axis].kind == "time"):
        records = _chronological(records, axis)
    folded = 0
    if spec.limit is not None:
        values = [binding[role] for role in ("value", "value2") if role in binding]
        if axis is None or not values or any(c.aggregate not in ADDITIVE and c.kind != "share" for c in values):
            raise ResolveError("A limit needs a category and additive values for Other.")
        if spec.limit < 1 or order not in {"value asc", "value desc"}:
            raise ResolveError("A limit must be positive and needs a value sort.")
        records, folded = _fold(records, axis, spec.limit, spec.other if spec.other is not None else defaults["other"])

    if spec.percent:
        totals = _totals(records, axis)
        for record in records:
            total = totals[record[axis]]
            record["value"] = record["value"] / total * 100 if total else 0
        zero_totals = sum(total == 0 for total in totals.values())
        if zero_totals:
            compromises.append(Compromise(
                key="percent", message=f"{zero_totals} stacks have a zero total; their values stay at 0.",
            ))

    categories = list(dict.fromkeys(r[axis] for r in records)) if axis is not None else []
    width = spec.width if spec.width is not None else (1200 if spec.type in TRENDS and len(categories) > 12 else 800)
    config = {"type": entry.draw.type, **deepcopy(entry.draw.options),
              "theme": spec.theme, "width": width, "height": height}
    for key, value in (("title", spec.title), ("innerRadius", spec.inner_radius)):
        if value is not None:
            config[key] = value
    if spec.type not in WITHOUT_AXES:
        x_column = binding.get("category") or binding.get("time") or binding.get("x")
        y_column = binding.get("value") or binding.get("y")
        category_title, value_title = spec.axis_x_title, spec.axis_y_title
        if spec.type in BARS:
            # The spec's axisXTitle names the horizontal axis; on horizontal bars that axis holds the values.
            category_title, value_title = value_title, category_title
        if (_names(category_title, y_column) and not _names(category_title, x_column)
                and _names(value_title, x_column) and not _names(value_title, y_column)):
            # Written for the other axis: a title follows the column it names.
            category_title, value_title = value_title, category_title
        x_title, y_title = category_title, value_title
        for key, title, column in (("axisXTitle", x_title, x_column),
                                   ("axisYTitle", y_title, y_column)):
            if title is not None or column is not None:
                config[key] = title if title is not None else spec.column_labels.get(column.name, column.name)
        if spec.type == "histogram":
            config["axisXTitle"] = spec.axis_x_title if spec.axis_x_title is not None else display["columns"]["value"]
            config["axisYTitle"] = spec.axis_y_title if spec.axis_y_title is not None else defaults["count"]
        if spec.percent and y_title is None:
            config["axisYTitle"] = "%"

    style = {}
    if spec.background_color is not None:
        style["backgroundColor"] = spec.background_color
    if spec.palette:
        style["palette"] = list(spec.palette)
    elif spec.emphasis:
        color_role = "group" if "group" in binding else axis
        labels = list(dict.fromkeys(r[color_role] for r in records)) if color_role else []
        muted = "#4E5969" if spec.theme == "dark" else "#C9CDD4"
        style["palette"] = [ACCENT if value_key(label) in spec.emphasis else muted for label in labels]
    elif spec.type in SINGLE_SERIES and "group" not in binding:
        # One series, one colour: the package would colour each bar by category, which reads as meaning.
        style["palette"] = [ACCENT]
    if spec.type in BARS | COLUMNS:
        if spec.zero is not None:
            style["startAtZero"] = spec.zero
    elif spec.zero is not None or spec.type in TRENDS | {"boxplot", "dual_axes"}:
        style["startAtZero"] = spec.zero if spec.zero is not None else True
    if style:
        config["style"] = style

    overrides = {}
    scale = {}
    y_scale = {}
    for key, value in (("domainMin", spec.axis_y_min), ("domainMax", spec.axis_y_max)):
        if value is not None:
            y_scale[key] = value
            y_scale["nice"] = False
    if spec.axis_y_scale == "log":
        y_scale["type"] = "log"
    if y_scale:
        scale["y"] = y_scale
    if spec.type == "scatter":
        x_scale = {key: value for key, value in (("domainMin", spec.axis_x_min), ("domainMax", spec.axis_x_max))
                   if value is not None}
        if x_scale:
            scale["x"] = x_scale
    title = {}
    if (spec.direction or defaults["direction"]) == "rtl":
        if spec.type in COLUMNS and axis is not None and binding[axis].kind != "time":
            scale["x"] = {"domain": categories[::-1]}
        title["align"] = "right"
        if spec.direction == "rtl":
            compromises.append(Compromise(key="direction", message="the legend stays where the package puts it"))
    if spec.subtitle is not None:
        title["subtitle"] = spec.subtitle
    if title:
        overrides["title"] = title
    if scale:
        overrides["scale"] = scale
    if spec.labels == "off":
        overrides["labels"] = []
    elif spec.labels == "on":
        if spec.type in BARS | COLUMNS | {"pie", "donut", "scatter", "histogram", "boxplot", "treemap", "word_cloud"}:
            field = "y" if spec.type == "scatter" else "value"
            # An enable fallback, not a replacement for the package's placement
            # and collision handling. The adapter retains existing label options.
            overrides["labels"] = [{"text": field}]
        else:
            compromises.append(Compromise(
                key="labels", message=f"labels on cannot reach the marks of {spec.type}; the package's labels are retained.",
            ))
    if spec.legend == "off":
        overrides["legend"] = False
    elif spec.legend == "on":
        if spec.type in {"line", "area", "scatter", "histogram", "radar"} and "group" not in binding:
            compromises.append(Compromise(key="legend", message="no legend: the chart has one series"))
        else:
            overrides["legend"] = True

    number.unit = canonical_unit(number.unit)
    if spec.format is not None and number.unit == "%" and not spec.percent and any(
        column.kind != "share" and canonical_unit(column.unit) != "%" for role, column in binding.items() if role in MEASURES
    ):
        compromises.append(Compromise(key="format", message="a percent sign on a value that is not a share"))
    value = binding.get("value") or binding.get("y")
    if number.unit is None:
        number.unit = "%" if spec.percent else _column_unit(value)
    if number.decimals is None and spec.type != "histogram":
        smallest = min((abs(record[role]) for record in records for role in MEASURES
                        if role in record and record[role]), default=None)
        if smallest is not None and smallest < 0.01:
            # Two significant digits of the smallest value, so 0.0001 prints as 0.00010, never as 0.
            number.decimals = min(6, 1 - Decimal(str(smallest)).adjusted())

    number2 = None
    if spec.type == "histogram":
        number.unit = None  # The formatted y axis counts records, not the bound measure.
        config["data"] = _histogram(records, spec.bin_number if spec.bin_number is not None else 10, spec.digits)
    elif spec.type == "dual_axes":
        number2 = number.model_copy(update={"unit": _column_unit(binding["value2"])})
        config["categories"] = [r["category"] for r in records]
        config["series"] = [
            {"type": chart, "data": [r[role] for r in records], "axisYTitle": binding[role].name}
            for role, chart in (("value", "column"), ("value2", "line"))
        ]
        # GPT-Vis uses axisYTitle as the actual series key. Keep that key raw and
        # let the G2 display layer translate its axis title and legend label.
        display["columns"].update({binding[role].name: spec.column_labels.get(binding[role].name, binding[role].name)
                                   for role in ("value", "value2")})
    else:
        config["data"] = [{entry.fields[role]: cell for role, cell in record.items()} for record in records]
    return Resolved(config, overrides, number, compromises, len(records), folded, dropped, width, height, number2,
                    display=display)
