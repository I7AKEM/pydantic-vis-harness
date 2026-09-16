"""Resolve indicator text once in Python, preserving the saved result's numbers."""

import math
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Literal, TypedDict

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.labels import display_value
from vis_agent.units import canonical_unit, indicator_unit

from .indicator import indicator_data_violations
from .models import NumberFormat, Spec
from .syntax import parse_format

ARABIC_DIGITS = str.maketrans("0123456789,.", "٠١٢٣٤٥٦٧٨٩٬٫")


class MetricText(TypedDict):
    column: str
    label: str
    unit: str | None
    state: Literal["available", "unavailable"]
    display: str
    exact: str | None
    number: str
    unitLabel: str | None
    exactNumber: str | None


class ContextText(TypedDict):
    column: str
    label: str
    text: str


class CardText(TypedDict):
    value: MetricText
    context: list[ContextText]
    support: list[MetricText]


def number_text(value: int | float, number: NumberFormat) -> tuple[str, str | None]:
    """Return display and, when rounded, the unchanged value as secondary text.

    This never scales percentages. Decimal is only used for display rounding,
    with input taken from QueryResult rather than from model-supplied text.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (
        isinstance(value, float) and not math.isfinite(value)
    ):
        raise ValueError("an indicator metric must be a finite number or NULL")
    if number.decimals is not None and number.decimals > 20:
        raise ValueError("indicator number formats support at most 20 decimal places")
    original = Decimal(str(value))
    scaled, suffix = original, ""
    if number.compact:
        for size, label in ((9, "B"), (6, "M"), (3, "K")):
            if abs(original) >= 10 ** size:
                with localcontext() as ctx:
                    ctx.prec = max(28, len(original.as_tuple().digits) + 2)
                    scaled = original / Decimal(10 ** size)
                suffix = label
                break
    # Scientific notation keeps very small floating-point values legible. Ints
    # always retain their full decimal digits, including those above 2**53.
    scientific = number.decimals is None and scaled != 0 and (
        abs(scaled) < Decimal("0.000001") or (isinstance(value, float) and abs(scaled) >= Decimal("1e21"))
    )
    if scientific:
        text = format(scaled, ".6E")
        mantissa, exponent = text.split("E")
        text = mantissa.rstrip("0").rstrip(".") + "e" + str(int(exponent))
        displayed = Decimal(text)
    else:
        decimals = number.decimals
        if decimals is None:
            decimals = 1 if suffix else max(2, 3 - scaled.adjusted()) if 0 < abs(scaled) < 1 else 2
        with localcontext() as ctx:
            ctx.prec = max(28, len(scaled.as_tuple().digits) + abs(scaled.adjusted()) + decimals + 2)
            displayed = scaled.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
        # Never display a negative zero due to rounding.
        if displayed == 0:
            displayed = abs(displayed)
        text = format(displayed, f",.{decimals}f" if number.thousands else f".{decimals}f")
        if number.decimals is None and "." in text:
            text = text.rstrip("0").rstrip(".")

    def decorate(text: str) -> str:
        if number.unit:
            text += "%" if number.unit == "%" else " " + number.unit
        return text.translate(ARABIC_DIGITS) if number.digits == "arabic" else text

    display = decorate(text + suffix)
    # Preserve the original text for every lossy rounding, not just zeroing.
    scale = {"K": 1000, "M": 1000000, "B": 1000000000}.get(suffix, 1)
    exact = decorate(str(value)) if displayed != scaled or scale != 1 else None
    return display, exact


def resolve_cards(spec: Spec, columns: list[ResultColumn], result: QueryResult) -> list[CardText]:
    if result.row_count != 1 or len(result.rows) != 1:
        raise ValueError("an indicator requires exactly one complete result row")
    if len(result.columns) != len(set(result.columns)) or len(columns) != len({c.name for c in columns}):
        raise ValueError("indicator result column names must be unique")
    if set(result.columns) != {c.name for c in columns} or len(result.rows[0]) != len(result.columns):
        raise ValueError("indicator result cells and column metadata must match")
    if not 1 <= len(spec.cards) <= 6:
        raise ValueError("an indicator requires one to six cards")
    metadata = {c.name: c for c in columns}
    cells = dict(zip(result.columns, result.rows[0]))
    # Keep direct renderer calls subject to the same finite-value/share-range
    # checks as normal checked delivery, while binding metadata by identity.
    if issues := indicator_data_violations([metadata[name] for name in result.columns], result, policy=False):
        raise ValueError("; ".join(issue.message for issue in issues))
    unavailable = "غير متاح" if spec.language == "ar" else "Unavailable"

    def metric(name: str, pattern: str | None = None) -> MetricText:
        column, cell = metadata[name], cells[name]
        if column.kind not in {"measure", "share"}:
            raise ValueError(f"indicator metric {name!r} must be a measure or share")
        unit = column.unit
        number = parse_format(pattern) if pattern is not None else NumberFormat()
        if number.unit is not None and canonical_unit(number.unit) != canonical_unit(unit):
            raise ValueError(f"indicator format must preserve the unit of {name!r}")
        number.unit, number.digits = None, spec.digits
        numeric, exact_numeric = (unavailable, None) if cell is None else number_text(cell, number)
        unit_label = indicator_unit(unit, cell, spec.language)

        def with_unit(text):
            return text + (("" if unit_label == "%" else " ") + unit_label if unit_label else "")

        display = unavailable if cell is None else with_unit(numeric)
        exact = with_unit(exact_numeric) if exact_numeric is not None else None
        return MetricText(column=name, label=spec.column_labels.get(name, column.meaning or name), unit=unit,
                          state="unavailable" if cell is None else "available", display=display, exact=exact,
                          number=numeric, unitLabel=unit_label, exactNumber=exact_numeric)

    cards: list[CardText] = []
    try:
        for card in spec.cards:
            context = []
            for name in card.context:
                column, cell = metadata[name], cells[name]
                if column.kind not in {"category", "ordinal", "time", "geography", "identifier"}:
                    raise ValueError(f"indicator context {name!r} must identify the result scope")
                # In particular, do not shorten, parse or transliterate Hijri text.
                context.append(ContextText(column=name, label=spec.column_labels.get(name, column.meaning or name),
                                           text=unavailable if cell is None else str(display_value(spec, name, cell))))
            cards.append(CardText(value=metric(card.value, card.format), context=context,
                                  support=[metric(name) for name in card.support]))
    except KeyError as error:
        raise ValueError(f"unknown indicator result column {error.args[0]!r}") from error
    return cards
