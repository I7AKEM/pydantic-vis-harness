"""Independent metric golds, separate from recommendation/rule agreement.

Neither image existence nor a passing SpecCheck establishes metric fidelity. These checks
compare the chosen bindings and the actual canvas text to frozen source values.
"""

from decimal import Decimal, InvalidOperation
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from vis_agent.units import COUNT_NOUNS, canonical_unit, display_unit


class CardExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    context: list[str] = Field(default_factory=list)
    support: list[str] = Field(default_factory=list)
    unit: str | None = None
    state: Literal["value", "unavailable"] = "value"
    exact_value: int | float | None = None
    unit_text: str | None = None

    @model_validator(mode="after")
    def state_matches(self):
        if (self.state == "unavailable") != (self.exact_value is None):
            raise ValueError("Unavailable expectations require NULL; available expectations require a numeric value")
        return self


class IndicatorExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["required", "allowed", "forbidden", "incomplete", "unavailable"]
    cards: list[CardExpectation] = Field(default_factory=list)
    shared_heading: str | None = None

    @model_validator(mode="after")
    def complete_gold(self):
        if self.mode in {"required", "allowed", "unavailable"} and not self.cards:
            raise ValueError("An eligible indicator case needs explicit card expectations")
        if len({card.value for card in self.cards}) != len(self.cards):
            raise ValueError("Expected primary cards must be unique")
        return self


def presentation_fit(gold: IndicatorExpectation, chart: str | None, clarified: bool = False) -> bool:
    if gold.mode == "incomplete":
        return clarified
    if gold.mode == "forbidden":
        return chart is not None and chart != "indicator"
    if gold.mode == "allowed":
        return chart in {"indicator", "table"}
    return chart == "indicator"


def metric_fidelity(gold: IndicatorExpectation, spec, report) -> bool:
    """Card count, primary columns, scope, support, units, and saved numeric states."""
    if spec is None:
        return False
    if spec.type != "indicator":
        return gold.mode in {"allowed", "forbidden"}
    if gold.mode in {"forbidden", "incomplete"} or report.analysis is None or report.result is None:
        return False
    if report.result.row_count != 1 or len(report.result.rows) != 1 or len(spec.cards) != len(gold.cards):
        return False
    actual = {card.value: card for card in spec.cards}
    if set(actual) != {card.value for card in gold.cards}:
        return False
    metadata = {column.name: column for column in report.analysis.columns}
    row = dict(zip(report.result.columns, report.result.rows[0]))
    for wanted in gold.cards:
        bound = actual[wanted.value]
        if (set(bound.context) != set(wanted.context) or set(bound.support) != set(wanted.support)
                or wanted.value not in row or wanted.value not in metadata):
            return False
        value = row[wanted.value]
        if isinstance(value, bool) or value != wanted.exact_value or metadata[wanted.value].unit != wanted.unit:
            return False
        if (value is None) != (wanted.state == "unavailable"):
            return False
    return True


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬−", "01234567890123456789.,-")
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def numeric_text_matches(text: str, expected: int | float | None) -> bool:
    """Independent rounding-aware comparison, with no guessed percentage scaling."""
    if expected is None:
        return text.strip() in {"Unavailable", "غير متاح", "غير متوفر"}
    normalized = text.translate(_DIGITS).replace(",", "")
    found = _NUMBER.search(normalized)
    if found is None:
        return False
    try:
        value = Decimal(found[0])
        wanted = Decimal(str(expected))
    except InvalidOperation:
        return False
    # Compact suffixes are explicit presentation multipliers, never a percent multiplier.
    suffix = normalized[found.end():].strip()
    multiplier = next((Decimal(scale) for prefix, scale in (("K", "1000"), ("M", "1000000"),
                      ("B", "1000000000"), ("T", "1000000000000")) if suffix.startswith(prefix)), Decimal(1))
    value *= multiplier
    if value == 0 and wanted != 0:
        return False
    tolerance = Decimal(1).scaleb(Decimal(found[0]).as_tuple().exponent) * multiplier / 2
    return abs(value - wanted) <= tolerance


def _drawn_metric(metric: dict, role: str, card: int, texts: list, bounds: list) -> str | None:
    """Verify either historical whole-value text or separate number/unit canvas runs."""
    display, exact = metric.get("display", ""), metric.get("exact")
    if "number" not in metric:
        if display not in texts or not any(b.get("text") == display and b.get("column") == metric["column"] for b in bounds):
            return None
        if exact and exact not in texts:
            return None
        return exact or display
    unit = metric.get("unitLabel") if metric.get("state") == "available" else None

    def group(number, logical, number_role, unit_role):
        if not isinstance(number, str) or not isinstance(logical, str):
            return False
        compact = lambda text: "".join(text.split())
        if compact(logical) != compact(number + (unit or "")):
            return False
        runs = [b for b in bounds if b.get("column") == metric["column"] and b.get("card") == card]
        numeric = next((b for b in runs if b.get("role") == number_role and b.get("text") == number), None)
        if numeric is None or number not in texts:
            return False
        if unit:
            suffix = next((b for b in runs if b.get("role") == unit_role and b.get("text") == unit), None)
            if suffix is None or unit not in texts:
                return False
            overlap = min(numeric["y"] + numeric["height"], suffix["y"] + suffix["height"]) - max(numeric["y"], suffix["y"])
            gap = max(numeric["x"] - suffix["x"] - suffix["width"], suffix["x"] - numeric["x"] - numeric["width"], 0)
            if overlap <= 0 or gap > max(24, numeric["height"]):
                return False
        return True

    if not group(metric["number"], display, role, "unit" if role == "value" else "support_unit"):
        return None
    if exact is not None and not group(metric.get("exactNumber"), exact, "exact", "exact_unit"):
        return None
    return metric.get("exactNumber") or metric["number"]


def _visible_unit_valid(source: str | None, actual: str | None) -> bool:
    if display_unit(source) is None:
        return not actual
    if canonical_unit(source) == "%":
        return actual == "%"
    for aliases, english, arabic in COUNT_NOUNS.values():
        if source.strip().casefold() in aliases:
            return actual in (*english, *arabic)
    return actual == source


def rendered_fidelity(gold: IndicatorExpectation, rendered, report) -> bool:
    """Verify saved bindings against text that canvas actually drew, with measured bounds."""
    if not rendered.png.is_file() or not rendered.config.is_file():
        return False
    try:
        payload = json.loads(rendered.config.read_text(encoding="utf-8"))
        cards = payload["gptvis"]["cards"]
    except (ValueError, KeyError, OSError, TypeError):
        return False
    texts = rendered.texts or payload.get("texts") or []
    bounds = getattr(rendered, "text_bounds", None) or payload.get("textBounds") or []
    if not texts or not bounds or len(cards) != len(gold.cards):
        return False
    if any(b.get("width", 0) <= 0 or b.get("height", 0) <= 0 or b.get("x", -1) < -0.5
           or b.get("y", -1) < -0.5 or b["x"] + b["width"] > rendered.width + 0.5
           or b["y"] + b["height"] > rendered.height + 0.5 for b in bounds):
        return False
    by_column = {card["value"]["column"]: (index, card) for index, card in enumerate(cards)}
    values = dict(zip(report.result.columns, report.result.rows[0]))
    for expected in gold.cards:
        if expected.value not in by_column:
            return False
        card_index, card = by_column[expected.value]
        primary = card["value"]
        if (primary.get("unit") != expected.unit or primary.get("state") != (
                "unavailable" if expected.state == "unavailable" else "available")):
            return False
        for index, metric in enumerate([primary, *card.get("support", [])]):
            column = next((c for c in report.analysis.columns if c.name == metric["column"]), None)
            if column is None or metric.get("unit") != column.unit:
                return False
            if ("number" in metric and metric.get("state") == "available"
                    and not _visible_unit_valid(column.unit, metric.get("unitLabel"))):
                return False
            drawn = _drawn_metric(metric, "value" if index == 0 else "support", card_index, texts, bounds)
            if drawn is None or not numeric_text_matches(drawn, values.get(metric["column"])):
                return False
        if expected.unit_text is not None:
            metric_text = " ".join(b["text"] for b in bounds if b.get("column") == expected.value
                                   and b.get("role") in {"value", "unit"})
            if expected.unit_text not in metric_text:
                return False
        if {item["column"] for item in card.get("support", [])} != set(expected.support):
            return False
        if {item["column"] for item in card.get("context", [])} != set(expected.context):
            return False
        for context in card.get("context", []):
            # Wrapped context is reconstructed only from actual draw calls for this column.
            drawn = " ".join(b["text"] for b in bounds if b.get("column") == context["column"] and b.get("role") == "context")
            if str(context["text"]) not in drawn:
                return False
    if gold.shared_heading is not None:
        if (len(cards) != 1 or payload["gptvis"].get("title") != gold.shared_heading
                or cards[0]["value"]["label"] != gold.shared_heading or texts.count(gold.shared_heading) != 1):
            return False
        if not any(b.get("text") == gold.shared_heading and b.get("role") == "label"
                   and b.get("card") == 0 for b in bounds):
            return False
    return True
