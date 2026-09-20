"""Structural fidelity checks for single-row metric cards, independent of chart axes."""

import math

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.units import canonical_unit

from .models import Spec, Violation
from .rules import _contrast, _HEX
from .syntax import parse_format

NUMERIC_KINDS = {"measure", "share"}
CONTEXT_KINDS = {"category", "ordinal", "time", "geography", "identifier"}
INDICATOR_KEYS = {
    "cards", "title", "subtitle", "description", "language", "theme", "width", "height",
    "direction", "digits", "style", "backgroundColor", "palette", "columnLabels", "valueLabels",
}


def indicator_data_violations(
    columns: list[ResultColumn], result: QueryResult, *, policy: bool = True,
) -> list[Violation]:
    """Eligibility does not choose a primary metric or claim to answer the question."""
    issues = []

    def fail(message: str) -> None:
        issues.append(Violation(rule="I1", message=message,
                                fix="Use a complete single-row numeric result, or choose a table"))

    if result.row_count != 1 or len(result.rows) != 1:
        fail("An indicator needs exactly one complete result row; it cannot select or aggregate rows.")
    names = [column.name for column in columns]
    if len(set(names)) != len(names) or len(set(result.columns)) != len(result.columns):
        fail("Indicator result and metadata column names must be unique.")
    if names != result.columns:
        fail("Indicator metadata columns must match the result columns in order.")
    if any(len(row) != len(names) for row in result.rows):
        fail("Every result row must have one cell per column.")
    if issues:
        return issues
    if not any(column.kind in NUMERIC_KINDS for column in columns):
        fail("An indicator needs at least one measure or share column.")
    for column, value in zip(columns, result.rows[0]):
        if column.kind not in NUMERIC_KINDS or value is None:
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                (isinstance(value, float) and not math.isfinite(value))):
            fail(f"'{column.name}' must hold a finite numeric value or NULL, not text or a boolean.")
            continue
        unit = (canonical_unit(column.unit) or "").strip().casefold()
        scale = 100 if unit == "%" else 1 if unit == "fraction" else None
        if policy and column.kind == "share" and scale is not None and not -1e-9 * scale <= value <= scale + 1e-9 * scale:
            issues.append(Violation(
                rule="I6", message=f"'{column.name}' is a part-of-whole share in {unit}; its value {value} is outside 0–{scale}.",
                fix="Correct the share's numerator/denominator SQL. If this is percentage change, describe it as kind measure with unit % instead of share.",
            ))
    return issues


def check_indicator(
    spec: Spec, columns: list[ResultColumn], result: QueryResult, *, policy: bool = True,
) -> list[Violation]:
    issues = indicator_data_violations(columns, result, policy=policy)

    def fail(rule: str, message: str, fix: str) -> None:
        issues.append(Violation(rule=rule, message=message, fix=fix))

    if spec.bind:
        fail("I2", "An indicator uses cards, not ordinary role bindings.", "Move the bindings into cards")
    if not 1 <= len(spec.cards) <= 6:
        fail("I2", "An indicator needs one to six cards.", "Bind every requested metric using up to six cards, or choose a table")
    by_name = {column.name: column for column in columns}
    covered, primary = set(), set()
    for number, card in enumerate(spec.cards, 1):
        if card.value in primary:
            fail("I2", f"Card {number} repeats primary column '{card.value}'.", "Use each primary column once")
        primary.add(card.value)
        bound = [card.value, *card.context, *card.support]
        if len(set(bound)) != len(bound):
            fail("I2", f"Card {number} repeats or overlaps value, context, or support bindings.", "Use each column once within a card")
        covered.update(bound)
        for role, names, kinds in (("value", [card.value], NUMERIC_KINDS),
                                   ("context", card.context, CONTEXT_KINDS),
                                   ("support", card.support, NUMERIC_KINDS)):
            for name in names:
                if name not in by_name:
                    fail("I2", f"Card {number} {role} column '{name}' does not exist.", "Bind an exact result column name")
                elif by_name[name].kind not in kinds:
                    fail("I2", f"Card {number} {role} column '{name}' has kind '{by_name[name].kind}'.",
                         f"Use one of these kinds: {', '.join(sorted(kinds))}")
        if card.format is not None:
            try:
                number_format = parse_format(card.format)
            except ValueError as error:
                fail("I3", f"Card {number} format is invalid: {error}", "Use the number-format grammar")
            else:
                if number_format.decimals is not None and number_format.decimals > 20:
                    fail("I3", f"Card {number} format exceeds twenty decimal places.", "Use at most twenty decimal places")
                if (card.value in by_name and number_format.unit is not None and
                        canonical_unit(number_format.unit) != canonical_unit(by_name[card.value].unit)):
                    fail("I3", f"Card {number} format cannot change the unit of '{card.value}'.",
                         "Omit the format unit or use the column's unit (% includes explicit percent aliases); formatting never rescales values")
    missing = [name for name in by_name if name not in covered]
    if missing and policy:
        fail("I2", f"Indicator leaves result columns unbound: {', '.join(missing)}.",
             "Retain every column as a primary, context, or supporting value, or use a table")
    if policy and (not spec.title or not spec.title.strip() or not spec.description or not spec.description.strip()):
        fail("C8", "A title and a description are required.", "Write them")
    if len(spec.palette) > 1 or any(not _HEX.fullmatch(color) for color in spec.palette):
        fail("C6", "An indicator accepts one hex accent color.", "Use one color or omit the palette")
    background = spec.background_color or ("#141b26" if spec.theme == "dark" else "#f3f6fb")
    if not _HEX.fullmatch(background):
        fail("C7", "The background must be a hex color to check contrast.", "Choose a hex background color")
    elif policy:
        # The accent is painted against a card surface, which can differ from the outer background.
        surface = "#202938" if spec.theme == "dark" else "#FFFFFF"
        if any(min(_contrast(color, background), _contrast(color, surface)) < 3
               for color in spec.palette if _HEX.fullmatch(color)):
            fail("C7", "The indicator accent needs at least 3 to 1 contrast with the background and card surface.",
                 "Choose an accent that contrasts with both surfaces")
    for field, minimum in (("width", 240), ("height", 160)):
        value = getattr(spec, field)
        if value is not None and not minimum <= value <= 2400:
            fail("I4", f"Indicator {field} must be between {minimum} and 2400 pixels.", "Use a supported size or omit it")
    return issues
