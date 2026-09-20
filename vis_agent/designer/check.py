"""Validate a written spec and disclose its renderer's compromises."""

import re

from vis_agent.analyst.models import QueryResult, ResultColumn
from vis_agent.models import Intent
import vis_agent.render.gptvis  # noqa: F401
from vis_agent.render.base import capability_for
from vis_agent.units import canonical_unit

from .catalogue import CATALOGUE
from .capabilities import COMMON_KEYS
from .fold import FoldError, fold
from .indicator import INDICATOR_KEYS, check_indicator
from .models import Compromise, Spec, SpecCheck, SpecError, Violation
from .rules import LINES, THEME_BACKGROUNDS, _contrast, check_rules, offered
from .shape import ColumnShape, describe
from .syntax import KEYS, STYLE_KEYS, parse, parse_format, to_text


HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")


def _normalise_hex(value: str) -> str:
    """Accept common model spellings while keeping the renderer contract strict."""
    color = value.strip()
    if color.lower().startswith("0x"):
        color = color[2:]
    if not color.startswith("#") and re.fullmatch(r"(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", color):
        color = "#" + color
    return color


def _rgb(color: str) -> tuple[int, int, int]:
    digits = color[1:]
    if len(digits) == 3:
        digits = "".join(value * 2 for value in digits)
    return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))


def _mix(color: str, target: str, fraction: float) -> str:
    source_rgb, target_rgb = _rgb(color), _rgb(target)
    channels = [round(source + (destination - source) * fraction)
                for source, destination in zip(source_rgb, target_rgb)]
    return "#" + "".join(f"{channel:02X}" for channel in channels)


def _accessible_hex(color: str, backgrounds: list[str]) -> str:
    """Return the smallest black/white mix that reaches 3:1 against every painted surface."""
    if min(_contrast(color, background) for background in backgrounds) >= 3:
        return color
    for step in range(1, 101):
        fraction = step / 100
        candidates = [_mix(color, target, fraction) for target in ("#000000", "#FFFFFF")]
        passing = [candidate for candidate in candidates
                   if min(_contrast(candidate, background) for background in backgrounds) >= 3]
        if passing:
            return passing[0]
    return color


def _repair_runtime_colors(spec: Spec) -> tuple[Spec, list[Compromise], list[str]]:
    """Canonicalize valid HEX and repair contrast in code so a model cannot loop on the same colour."""
    background = _normalise_hex(spec.background_color) if spec.background_color else THEME_BACKGROUNDS[spec.theme]
    invalid = []
    if not HEX_COLOR.fullmatch(background):
        invalid.append(f"backgroundColor {spec.background_color!r}")
    palette = [_normalise_hex(color) for color in spec.palette]
    invalid.extend(f"palette color {original!r}" for original, color in zip(spec.palette, palette)
                   if not HEX_COLOR.fullmatch(color))
    if invalid:
        return spec, [], invalid
    surfaces = [background]
    if spec.type == "indicator":
        surfaces.append("#202938" if spec.theme == "dark" else "#FFFFFF")
    repaired = [_accessible_hex(color, surfaces) for color in palette]
    changes = [(old, new) for old, new in zip(palette, repaired) if old != new]
    compromises = [Compromise(
        key="palette",
        message=f"Adjusted {old} to {new} to meet the 3:1 contrast requirement.",
    ) for old, new in changes]
    return spec.model_copy(update={"background_color": background if spec.background_color else None,
                                   "palette": repaired}), compromises, []


def _present_keys(spec: Spec) -> list[str]:
    defaults = Spec(type=spec.type)
    keys = [
        key for key, (field, _) in (KEYS | STYLE_KEYS).items()
        if key != "style" and getattr(spec, field) != getattr(defaults, field)
    ]
    # Style palettes serialize as top-level palettes; backgroundColor keeps style.
    if spec.background_color is not None:
        keys.append("style")
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
    *, intent: Intent | None = None, policy: bool = True, repair_colors: bool = False,
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

    color_compromises = []
    if repair_colors:
        spec, color_compromises, invalid_colors = _repair_runtime_colors(spec)
        if invalid_colors:
            fail("color_hex", "Colors must use three- or six-digit hexadecimal values: "
                 + ", ".join(invalid_colors) + ".", "Use a value such as #1783FF")

    if "*" in capability.rejected:
        fail("C1", f"{renderer} does not draw {spec.type}: {capability.rejected['*']}",
             "Choose a catalogue entry supported by the renderer")

    # Mappings refer to source result columns, before a fold creates its series.
    label_columns = {column.name: column for column in columns}
    for name, label in spec.column_labels.items():
        if name not in label_columns:
            fail("label_binding", f"Column label '{name}' does not identify a result column.",
                 "Use an exact result column name")
        if not label.strip():
            fail("label_binding", f"Column label '{name}' may not be empty.", "Use a nonempty display label")
    for name, labels in spec.value_labels.items():
        if name not in label_columns:
            fail("label_binding", f"Value labels for '{name}' do not identify a result column.",
                 "Use an exact result column name")
        elif label_columns[name].kind in {"measure", "share"}:
            fail("label_binding", f"Value labels cannot replace numeric measurements in '{name}'.",
                 "Map categorical labels only; use number formatting for measurements")
        if any(not label.strip() for label in labels.values()):
            fail("label_binding", f"Value labels for '{name}' may not be empty.", "Use nonempty display labels")

    bind = dict(spec.bind)
    if spec.fold and "fold" in entry.keys:
        for role in ("group", "value"):
            if role in bind:
                fail("C20", f"fold provides the '{role}' role; remove the '{role}' binding.",
                     f"Remove the '{role}' line under bind")
        try:
            folded = fold(columns, result, spec.fold, spec.language)
        except FoldError as error:
            fail("C20", f"fold: {error}", "Fold two or more measure columns of one unit, or drop fold")
        else:
            columns, result = folded.columns, folded.result
            bind.update(group=folded.series, value=folded.value)
    # Indicators validate their exact row/metadata contract before inspecting cells.
    shape = describe(columns, result, relationships=policy) if spec.type != "indicator" else None
    by_name = {column.name: column for column in columns}
    for role, name in bind.items():
        if name not in by_name:
            fail("C2", f"Bound column '{name}' for role '{role}' does not exist.",
                 f"Bind '{role}' to a column in the result")
        if role not in entry.roles:
            fail("C2", f"{spec.type} does not accept role '{role}'.", f"Remove the '{role}' binding")
        elif policy and name in by_name and by_name[name].kind not in entry.roles[role].kinds:
            fail("C2", f"Role '{role}' does not accept column '{name}' of kind '{by_name[name].kind}'.",
                 f"Bind '{role}' to one of these kinds: {', '.join(entry.roles[role].kinds)}")
        elif not policy and shape is not None and name in by_name and role in {"value", "value2", "x", "y"}:
            if not shape.column(name).is_numeric:
                fail("C2", f"Numeric role '{role}' requires numeric cells in '{name}'.",
                     "Bind the role to a numeric CSV column")
    for role, requirement in entry.roles.items():
        if requirement.required and role not in bind:
            fix = (f"Bind the '{role}' role, or use fold for measures of one unit"
                   if "fold" in entry.keys else f"Bind the '{role}' role")
            fail("C2", f"Required role '{role}' is missing; it takes {', '.join(requirement.kinds)}. "
                 f"The result offers {offered(shape)}.", fix)

    present = _present_keys(spec)
    if spec.type == "indicator":
        if policy and intent in {"compare", "trend", "composition", "distribution"}:
            fail("I7", f"An indicator cannot serve the selected {intent} intent.",
                 "Choose a table for a wide result, or a chart that shows the requested groups, periods, or breakdown. Do not turn requested components into supporting KPI values.")
        # Explicit defaults (sort none, percent false) are still inapplicable to cards.
        present = [key for key, (field, _) in (KEYS | STYLE_KEYS).items()
                   if key != "style" and field in spec.model_fields_set]
        for key in present:
            if key not in INDICATOR_KEYS and not (key == "bind" and not spec.bind):
                fail("C3", f"indicator does not accept key '{key}'.", f"Remove '{key}'")
        violations.extend(check_indicator(spec, columns, result, policy=policy))
        compromises = [Compromise(
            key="cards", message=f"The denominator for '{column.name}' is not stated; the value is displayed without rescaling.",
        ) for column in columns if column.kind == "share" and column.denominator in (None, "not stated")]
    else:
        for key in present:
            if key not in COMMON_KEYS and key not in entry.keys:
                fail("C3", f"{spec.type} does not accept key '{key}'.", f"Remove '{key}'")
        for field, key in (("cards", "cards"),):
            if field in spec.model_fields_set and key not in present:
                fail("C3", f"{spec.type} does not accept key '{key}'.", f"Remove '{key}'")
        binding = {role: shape.column(name) for role, name in bind.items() if name in by_name}
        if policy:
            # Historical evaluation only; runtime design uses execution checks.
            violations.extend(check_rules(entry, spec, shape, binding))
        else:
            if spec.sort and spec.sort != "none" and spec.sort.split()[0] not in bind:
                fail("C18", "The sort target must be a bound role.", "Remove the sort or bind its role")
        compromises = _rule_compromises(spec, binding, violations)
    compromises.extend(color_compromises)
    for key in present:
        if key in capability.rejected:
            fail("renderer", f"{key}: {capability.rejected[key]}", f"Remove '{key}' or choose another renderer")
        elif key in capability.degraded:
            compromises.append(Compromise(key=key, message=capability.degraded[key]))

    return SpecCheck(ok=not violations, violations=violations, compromises=compromises,
                     canonical=to_text(spec) if not violations else None)


def check_render_spec(
    text: str, columns: list[ResultColumn], result: QueryResult, renderer: str = "gptvis",
    *, intent: Intent | None = None,
) -> SpecCheck:
    """Validate renderer input and source fidelity; chart taste belongs to experts."""
    return check_spec(text, columns, result, renderer, intent=intent, policy=False, repair_colors=True)
