"""Validate a written spec and disclose its renderer's compromises."""

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.models import Intent
import vis_agent.render.gptvis  # noqa: F401
from vis_agent.render.base import capability_for
from vis_agent.units import canonical_unit

from .catalogue import CATALOGUE
from .indicator import INDICATOR_KEYS, check_indicator
from .models import Compromise, Spec, SpecCheck, SpecError, Violation
from .rules import LINES, check_rules
from .shape import ColumnShape, describe
from .syntax import KEYS, STYLE_KEYS, parse, parse_format, to_text


# Keys named by an entry are chart-specific; the rest are common vocabulary.
COMMON_KEYS = (set(KEYS) | set(STYLE_KEYS)) - {
    key for entry in CATALOGUE.entries for key in entry.keys
}


def _present_keys(spec: Spec) -> list[str]:
    defaults = Spec(type=spec.type)
    keys = [
        key for key, (field, _) in (KEYS | STYLE_KEYS).items()
        if key != "style" and getattr(spec, field) != getattr(defaults, field)
    ]
    # Style palettes serialize as top-level palettes; backgroundColor keeps style.
    if spec.background_color is not None:
        keys.append("style")
    if spec.language == "ar" and "direction" not in keys:
        keys.append("direction")
    return keys


def _rule_compromises(
    spec: Spec, binding: dict[str, ColumnShape], violations: list[Violation],
) -> list[Compromise]:
    compromises = []
    cropped = spec.zero is False or (spec.axis_y_min is not None and spec.axis_y_min > 0)
    if spec.type in LINES and cropped and not any(v.rule in {"C11", "C12", "C16"} for v in violations):
        value = binding.get("value")
        if value is not None and value.minimum is not None:
            start = spec.axis_y_min if spec.axis_y_min is not None else value.minimum
            compromises.append(Compromise(
                key="axisYMin" if spec.axis_y_min is not None else "zero",
                message=f"The value axis starts at {start:g} instead of zero.",
            ))
    if spec.format is not None and canonical_unit(parse_format(spec.format).unit) == "%":
        values = [binding[role] for role in ("value", "value2", "x", "y") if role in binding]
        if any(value.kind != "share" and canonical_unit(value.unit) != "%" for value in values) and not spec.percent:
            compromises.append(Compromise(
                key="format", message="The percent unit labels a value that is not a share; formatting does not convert it to a share.",
            ))
    return compromises


def check_spec(
    text: str, columns: list[ResultColumn], result: QueryResult, renderer: str = "gptvis",
    *, intent: Intent | None = None,
) -> SpecCheck:
    try:
        spec = parse(text)
    except SpecError as error:
        return SpecCheck(ok=False, violations=[
            Violation(rule="syntax", message=issue.message, line=issue.line,
                      fix="Correct the syntax on this line")
            for issue in error.issues
        ])

    entry = CATALOGUE.get(spec.type)
    capability = capability_for(renderer, spec.type)
    violations = []

    def fail(rule: str, message: str, fix: str) -> None:
        violations.append(Violation(rule=rule, message=message, fix=fix))

    if "*" in capability.rejected:
        fail("C1", f"{renderer} does not draw {spec.type}: {capability.rejected['*']}",
             "Choose a catalogue entry supported by the renderer")

    by_name = {column.name: column for column in columns}
    for role, name in spec.bind.items():
        if name not in by_name:
            fail("C2", f"Bound column '{name}' for role '{role}' does not exist.",
                 f"Bind '{role}' to a column in the result")
        if role not in entry.roles:
            fail("C2", f"{spec.type} does not accept role '{role}'.", f"Remove the '{role}' binding")
        elif name in by_name and by_name[name].kind not in entry.roles[role].kinds:
            fail("C2", f"Role '{role}' does not accept column '{name}' of kind '{by_name[name].kind}'.",
                 f"Bind '{role}' to one of these kinds: {', '.join(entry.roles[role].kinds)}")
    for role, requirement in entry.roles.items():
        if requirement.required and role not in spec.bind:
            fail("C2", f"Required role '{role}' is missing.", f"Bind the '{role}' role")

    present = _present_keys(spec)
    if spec.type == "indicator":
        if intent in {"compare", "trend", "composition", "distribution"}:
            fail("I7", f"An indicator cannot serve the selected {intent} intent.",
                 "Choose a table for a wide result, or a chart that shows the requested groups, periods, or breakdown. Do not turn requested components into supporting KPI values.")
        # Explicit defaults (sort none, percent false) are still inapplicable to cards.
        present = [key for key, (field, _) in (KEYS | STYLE_KEYS).items()
                   if key != "style" and field in spec.model_fields_set]
        for key in present:
            if key not in INDICATOR_KEYS and not (key == "bind" and not spec.bind):
                fail("C3", f"indicator does not accept key '{key}'.", f"Remove '{key}'")
        violations.extend(check_indicator(spec, columns, result))
        compromises = [Compromise(
            key="cards", message=f"The denominator for '{column.name}' is not stated; the value is displayed without rescaling.",
        ) for column in columns if column.kind == "share" and column.denominator in (None, "not stated")]
    else:
        for key in present:
            if key not in COMMON_KEYS and key not in entry.keys:
                fail("C3", f"{spec.type} does not accept key '{key}'.", f"Remove '{key}'")
        for field, key in (("cards", "cards"), ("column_labels", "columnLabels")):
            if field in spec.model_fields_set and key not in present:
                fail("C3", f"{spec.type} does not accept key '{key}'.", f"Remove '{key}'")
        shape = describe(columns, result)
        binding = {role: shape.column(name) for role, name in spec.bind.items() if name in by_name}
        # check_rules owns C10, including all hard-rule failures, so call it only once.
        violations.extend(check_rules(entry, spec, shape, binding))
        compromises = _rule_compromises(spec, binding, violations)
    for key in present:
        if key in capability.rejected:
            fail("renderer", f"{key}: {capability.rejected[key]}", f"Remove '{key}' or choose another renderer")
        elif key in capability.degraded:
            compromises.append(Compromise(key=key, message=capability.degraded[key]))

    return SpecCheck(ok=not violations, violations=violations, compromises=compromises,
                     canonical=to_text(spec) if not violations else None)
