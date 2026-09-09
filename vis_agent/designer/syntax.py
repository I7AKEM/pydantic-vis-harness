"""Parse and serialize the strict, line-oriented chart spec language."""

import re
from typing import get_args

from . import models
from .models import ROLES, NumberFormat, Spec, SpecError, SpecIssue

# key in the text -> (Spec field, kind). kind: text, int, number, bool, enum:<Literal name>, section:pairs, section:list
KEYS = {
    "title": ("title", "text"), "subtitle": ("subtitle", "text"), "description": ("description", "text"),
    "language": ("language", "enum:Language"), "theme": ("theme", "enum:Theme"),
    "width": ("width", "int"), "height": ("height", "int"),
    "axisXTitle": ("axis_x_title", "text"), "axisYTitle": ("axis_y_title", "text"),
    "innerRadius": ("inner_radius", "number"), "binNumber": ("bin_number", "int"),
    "bind": ("bind", "section:pairs"), "fold": ("fold", "section:list"), "style": ("style", "section:pairs"),
    "sort": ("sort", "enum:SortOrder"), "limit": ("limit", "int"), "other": ("other", "text"), "unknown": ("unknown", "text"),
    "emphasis": ("emphasis", "section:list"), "palette": ("palette", "section:list"),
    "direction": ("direction", "enum:Direction"), "zero": ("zero", "bool"),
    "axisYMin": ("axis_y_min", "number"), "axisYMax": ("axis_y_max", "number"),
    "axisXMin": ("axis_x_min", "number"), "axisXMax": ("axis_x_max", "number"),
    "axisYScale": ("axis_y_scale", "enum:ScaleKind"), "percent": ("percent", "bool"),
    "labels": ("labels", "enum:Switch"), "legend": ("legend", "enum:Switch"),
    "format": ("format", "format"), "digits": ("digits", "enum:Digits"),
}
STYLE_KEYS = {"backgroundColor": ("background_color", "text"), "palette": ("palette", "section:list")}


def parse_format(text: str) -> NumberFormat:
    match = re.fullmatch(r"(0)(,0)?(?:\.(0+))?(k)?(%|\s+\S.*)?", text)
    if match is None or text != text.rstrip():
        raise ValueError("expected a pattern like 0,0.00 SAR, 0.0%, or 0k")
    return NumberFormat(
        thousands=match[2] is not None,
        decimals=len(match[3]) if match[3] is not None else None,
        compact=match[4] is not None,
        unit=match[5].strip() if match[5] is not None else None,
    )


def _split_key(line: str) -> tuple[str, str]:
    match = re.fullmatch(r"(\S+?):(?:\s+(.*))?", line)
    if match is not None:
        return match[1], (match[2] or "").strip()
    parts = line.split(maxsplit=1)
    return parts[0], parts[1].strip() if len(parts) == 2 else ""


def _typed_value(value: str, kind: str) -> str | int | float | bool:
    if kind == "int":
        if re.fullmatch(r"-?\d+", value) is None:
            raise ValueError("expects an integer")
        return int(value)
    if kind == "number":
        try:
            return float(value)
        except ValueError:
            raise ValueError("expects a number") from None
    if kind == "bool":
        if value not in ("true", "false"):
            raise ValueError("expects true or false")
        return value == "true"
    if kind.startswith("enum:"):
        choices = get_args(getattr(models, kind.removeprefix("enum:")))
        if value not in choices:
            raise ValueError(f"expects one of: {', '.join(choices)}")
    if kind == "format":
        try:
            parse_format(value)
        except ValueError as error:
            raise ValueError(f"format pattern is not valid: {error}") from None
    return value


def parse(text: str) -> Spec:
    lines = [(number, line.rstrip()) for number, line in enumerate(text.splitlines(), 1) if line.strip()]
    first_number, first = lines[0] if lines else (1, "")
    match = re.fullmatch(r"vis +([^\s]+)", first)
    if match is None:
        raise SpecError([SpecIssue(line=first_number, message="first line must be `vis <type>`")])
    if match[1] not in get_args(models.ChartType):
        raise SpecError([SpecIssue(line=first_number, message=f"unknown chart type '{match[1]}'")])

    data = {"type": match[1]}
    issues: list[SpecIssue] = []
    seen: set[str] = set()
    seen_roles: set[str] = set()
    parent = "vis"
    style_parent: str | None = None

    def issue(number: int, message: str) -> None:
        issues.append(SpecIssue(line=number, message=message))

    def read_key(number: int, key: str, value: str, table: dict) -> None:
        if key not in table:
            issue(number, f"unknown key '{key}'")
            return
        field, kind = table[key]
        if field in seen:
            issue(number, f"duplicate key '{key}'")
            return
        seen.add(field)
        if kind.startswith("section:"):
            if value:
                issue(number, f"'{key}' is a section; put its lines indented below it")
            if kind == "section:list":
                data[field] = []
            elif key == "bind":
                data[field] = {}
        elif not value:
            issue(number, f"missing value for '{key}'")
        else:
            try:
                data[field] = _typed_value(value, kind)
            except ValueError as error:
                issue(number, str(error))

    def read_item(number: int, content: str, field: str) -> None:
        if content == "-":
            issue(number, "list item may not be empty")
        elif not content.startswith("- "):
            issue(number, "list items start with '- '")
        else:
            data[field].append(content[2:].strip())

    for number, line in lines[1:]:
        leading = line[:len(line) - len(line.lstrip())]
        indent = len(leading)
        if "\t" in leading:
            issue(number, "tabs are not allowed; indent with two spaces")
            continue
        if leading != " " * indent or indent not in (0, 2, 4):
            issue(number, "indentation must be two spaces per level")
            continue
        content = line[indent:]
        key, value = _split_key(content)
        if indent == 0:
            parent = key
            style_parent = None
            read_key(number, key, value, KEYS)
        elif indent == 2 and parent == "bind":
            if key not in ROLES:
                issue(number, f"unknown role '{key}'; roles are {', '.join(ROLES)}")
            elif key in seen_roles:
                issue(number, f"duplicate role '{key}'")
            else:
                seen_roles.add(key)
                if not value:
                    issue(number, f"missing value for '{key}'")
                else:
                    data["bind"][key] = value
        elif indent == 2 and parent == "style":
            style_parent = key
            read_key(number, key, value, STYLE_KEYS)
        elif indent == 2 and parent in ("emphasis", "palette", "fold"):
            read_item(number, content, parent)
        elif indent == 4 and parent == "style" and style_parent == "palette":
            read_item(number, content, "palette")
        else:
            context = style_parent if parent == "style" and style_parent else parent
            issue(number, f"unexpected indent under '{context}'")

    if issues:
        raise SpecError(issues)
    return Spec.model_validate(data)


def _text_value(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value).removesuffix(".0")
    return str(value)


def to_text(spec: Spec) -> str:
    lines = [f"vis {spec.type}"]
    keys = [key for key in KEYS if key != "style"]
    keys.insert(keys.index("palette") + 1, "style")
    defaults = {"language", "theme", "axis_y_scale", "percent", "digits"}
    for key in keys:
        if key == "style":
            if spec.background_color is not None:
                lines.extend(["style", f"  backgroundColor {spec.background_color}"])
            continue
        field, kind = KEYS[key]
        value = getattr(spec, field)
        if value is None or value == [] or value == {}:
            continue
        if field in defaults and value == Spec.model_fields[field].default:
            continue
        if key == "bind":
            lines.append("bind")
            lines.extend(f"  {role} {value[role]}" for role in ROLES if role in value)
        elif kind == "section:list":
            lines.append(key)
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key} {_text_value(value)}")
    return "\n".join(lines) + "\n"
