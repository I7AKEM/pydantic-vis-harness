"""Bind and transform a checked spec's result into GPT-Vis renderer options."""

from copy import deepcopy
from dataclasses import dataclass

from vis_agent.analyst.models import QueryResult, ResultColumn

from .catalogue import CATALOGUE
from .models import Compromise, NumberFormat, Spec
from .rules import ACCENT, ADDITIVE, BARS, COLUMNS
from .syntax import parse_format

LANGUAGE_DEFAULTS = {
    "ar": {"other": "أخرى", "unknown": "غير معروف", "direction": "rtl", "count": "العدد"},
    "en": {"other": "Other", "unknown": "Unknown", "direction": "ltr", "count": "Count"},
}
TRENDS = {"line", "multi_line", "area", "stacked_area"}
MEASURES = {"value", "value2", "x", "y"}
WITHOUT_AXES = {"pie", "donut", "treemap", "radar", "word_cloud", "table"}


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


class ResolveError(Exception):
    """Result cells cannot be faithfully resolved into chart records."""


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


def _sort(records: list[dict], order: str, axis: str | None, grouped: bool) -> list[dict]:
    if order == "none":
        return records
    field, direction = order.split()
    if field == "category":
        return sorted(records, key=lambda r: str(r[axis]), reverse=direction == "desc")
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


def resolve(spec: Spec, columns: list[ResultColumn], result: QueryResult) -> Resolved:
    """Resolve a checked spec, retaining row counts and render-time compromises."""
    entry = CATALOGUE.get(spec.type)
    defaults = LANGUAGE_DEFAULTS[spec.language]
    number = parse_format(spec.format) if spec.format is not None else NumberFormat()
    number.digits = spec.digits
    height = spec.height if spec.height is not None else 450
    if spec.type == "table":
        width = spec.width if spec.width is not None else 800
        config = {
            "type": entry.draw.type,
            "data": [dict(zip(result.columns, row)) for row in result.rows],
            "columns": list(result.columns), "width": width, "height": height,
        }
        compromises = [Compromise(key=key, message="tables are drawn as the package draws them")
                       for key in ("labels", "legend") if getattr(spec, key) == "on"]
        return Resolved(config, {}, number, compromises, len(result.rows), 0, 0, width, height)

    by_name = {column.name: column for column in columns}
    binding = {role: by_name[name] for role, name in spec.bind.items()}
    axis = "time" if "time" in binding else "category" if "category" in binding else None
    records, dropped = _bind(spec, result, spec.unknown if spec.unknown is not None else defaults["unknown"])
    compromises = []
    if dropped:
        compromises.append(Compromise(key="bind", message=f"Dropped {dropped} rows with null measures."))

    ordered = axis is not None and binding[axis].kind in {"time", "ordinal"}
    order = spec.sort or ("none" if ordered or axis is None else "value desc")
    if order != "none" and order.split()[0] not in binding:
        raise ResolveError("The sort target must be a bound role; remove the sort.")
    records = _sort(records, order, axis, "group" in binding)
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
    for key, value in (("title", spec.title), ("innerRadius", spec.inner_radius),
                       ("binNumber", spec.bin_number)):
        if value is not None:
            config[key] = value
    if spec.type not in WITHOUT_AXES:
        x_column = binding.get("category") or binding.get("time") or binding.get("x")
        y_column = binding.get("value") or binding.get("y")
        for key, title, column in (("axisXTitle", spec.axis_x_title, x_column),
                                   ("axisYTitle", spec.axis_y_title, y_column)):
            if title is not None or column is not None:
                config[key] = title if title is not None else column.name
        if spec.type == "histogram":
            config["axisXTitle"] = spec.axis_x_title if spec.axis_x_title is not None else binding["value"].name
            config["axisYTitle"] = spec.axis_y_title if spec.axis_y_title is not None else defaults["count"]
        if spec.percent and spec.axis_y_title is None:
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
        style["palette"] = [ACCENT if str(label) in spec.emphasis else muted for label in labels]
    if spec.type in BARS | COLUMNS:
        if spec.zero is not None:
            style["startAtZero"] = True
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
        if spec.type in BARS | COLUMNS and axis is not None and binding[axis].kind != "time":
            scale["x"] = {"domain": categories[::-1]}
        title["align"] = "right"
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
            field = {"scatter": "y", "histogram": "count"}.get(spec.type, "value")
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

    if spec.format is not None and number.unit == "%" and not spec.percent and any(
        column.kind != "share" for role, column in binding.items() if role in MEASURES
    ):
        compromises.append(Compromise(key="format", message="a percent sign on a value that is not a share"))
    value = binding.get("value") or binding.get("y")
    if number.unit is None:
        number.unit = "%" if spec.percent else value.unit if value is not None else None

    number2 = None
    if spec.type == "histogram":
        number.unit = None  # The formatted y axis counts records, not the bound measure.
        config["data"] = [r["value"] for r in records]
    elif spec.type == "dual_axes":
        number2 = number.model_copy(update={"unit": binding["value2"].unit})
        config["categories"] = [r["category"] for r in records]
        config["series"] = [
            {"type": chart, "data": [r[role] for r in records], "axisYTitle": binding[role].name}
            for role, chart in (("value", "column"), ("value2", "line"))
        ]
    else:
        config["data"] = [{entry.fields[role]: cell for role, cell in record.items()} for record in records]
    return Resolved(config, overrides, number, compromises, len(records), folded, dropped, width, height, number2)
