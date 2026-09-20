"""Inspectable chart capabilities for the agents, grounded in the executable renderer path."""

import json
import re
from functools import reduce
from pathlib import Path
from typing import get_args

import vis_agent.render.gptvis  # noqa: F401 - registers the renderer
from vis_agent.render.base import capability_for

from .catalogue import CATALOGUE, CatalogueEntry
from .indicator import INDICATOR_KEYS
from . import models
from .syntax import KEYS, STYLE_KEYS


# Keys named by catalogue entries are chart-specific. The remaining vocabulary is
# accepted across ordinary charts; indicators deliberately use a smaller contract.
CHART_SPECIFIC_KEYS = {key for entry in CATALOGUE.entries for key in entry.keys}
COMMON_KEYS = (set(KEYS) | set(STYLE_KEYS)) - CHART_SPECIFIC_KEYS

OFFICIAL_SKILL = {
    "exists": True,
    "name": "chart-visualization",
    "repository": "https://github.com/antvis/chart-visualization-skills",
    "scope": (
        "Official AntV guidance for chart selection and generation. It is advisory; "
        "this tool reports only options executable through this project's pinned SSR renderer and vis DSL."
    ),
}

KNOWN_PROBLEMS = (
    "label_overlap", "legend_overlap", "clipping", "low_contrast", "too_many_categories",
)

PROBLEM_CONFIG = {
    "label_overlap": {"labels", "width", "height", "format"},
    "clipping": {"labels", "width", "height", "format"},
    "legend_overlap": {"legend", "width", "height"},
    "low_contrast": {"palette", "backgroundColor"},
    "too_many_categories": {"sort", "limit", "other"},
}


def accepted_keys(entry: CatalogueEntry) -> set[str]:
    """Return the keys the runtime validator accepts for this internal chart type."""
    if entry.name == "indicator":
        return set(INDICATOR_KEYS)
    return COMMON_KEYS | set(entry.keys)


def common_keys() -> list[str]:
    """Return the true intersection accepted by every exposed chart type."""
    return sorted(reduce(set.intersection, (accepted_keys(entry) for entry in CATALOGUE.entries)))


def _renderer_package() -> dict:
    package_file = Path(__file__).parents[1] / "render" / "gptvis" / "package.json"
    manifest = json.loads(package_file.read_text(encoding="utf-8"))
    declared = manifest["dependencies"]["@antv/gpt-vis-ssr"]
    installed_file = package_file.parent / "node_modules" / "@antv" / "gpt-vis-ssr" / "package.json"
    installed = None
    embedded = None
    if installed_file.is_file():
        installed = json.loads(installed_file.read_text(encoding="utf-8")).get("version")
        embedded_file = installed_file.parent / "node_modules" / "@antv" / "gpt-vis" / "package.json"
        if embedded_file.is_file():
            embedded = json.loads(embedded_file.read_text(encoding="utf-8")).get("version")
    return {
        "name": "@antv/gpt-vis-ssr",
        "pinned_version": declared,
        "installed_version": installed,
        "installed_matches_pin": installed == declared if installed is not None else False,
        "embedded_gpt_vis_version": embedded,
        "browser_reference_version": manifest.get("devDependencies", {}).get("@antv/gpt-vis"),
        "version_note": (
            "Rendering uses the SSR package and its embedded GPT-Vis dependency; the browser reference "
            "package and current website may expose newer capabilities."
        ),
    }


def _native_types() -> list[tuple[str, str]]:
    """Read the installed package's own VisOptionMap rather than a website's latest list."""
    types_file = (Path(__file__).parents[1] / "render" / "gptvis" / "node_modules" / "@antv"
                  / "gpt-vis-ssr" / "dist" / "esm" / "types.d.ts")
    if not types_file.is_file():
        return []
    text = types_file.read_text(encoding="utf-8")
    match = re.search(r"export type VisOptionMap = \{(.*?)\n\};", text, re.DOTALL)
    if match is None:
        return []
    return re.findall(r"^\s*(?:'([^']+)'|([\w-]+))\s*:", match.group(1), re.MULTILINE)


def _installed_native_types() -> list[str]:
    return sorted(a or b for a, b in _native_types())


def _normalise_problem(problem: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", problem.strip().casefold()).strip("_")
    aliases = {
        "labels_overlap": "label_overlap", "overlapping_labels": "label_overlap",
        "legend_overlaps": "legend_overlap", "cropped": "clipping", "clip": "clipping",
        "contrast": "low_contrast", "colors": "low_contrast", "colours": "low_contrast",
        "many_categories": "too_many_categories", "crowded": "too_many_categories",
    }
    return aliases.get(value, value)


def _repairs(entry: CatalogueEntry, problem: str) -> tuple[list[str], list[str]]:
    accepted = accepted_keys(entry)
    wanted = _normalise_problem(problem)
    selected = set(KNOWN_PROBLEMS) if not wanted else {wanted}
    repairs: list[str] = []
    unsupported: list[str] = []

    if "label_overlap" in selected or "clipping" in selected:
        if "labels" in accepted:
            repairs.append("Use `labels off` to hide overlapping mark-value labels.")
        repairs.append("Increase `width` or `height`; horizontal bars usually need more height per category.")
        if "format" in accepted:
            repairs.append("Use a compact `format` such as `0k` when long numbers cause collisions.")
        if entry.name in {"column", "grouped_column", "stacked_column"}:
            repairs.append("For long category text, redesign as the corresponding horizontal bar chart.")
        unsupported.extend((
            "The vis DSL does not expose label rotation.",
            "The vis DSL does not expose per-label font size or collision transforms.",
        ))
    if "legend_overlap" in selected:
        if "legend" in accepted:
            repairs.append("Use `legend off` when series are already directly understandable.")
        repairs.append("Increase `width` or `height`, or choose a less crowded chart type.")
        unsupported.append("Legend position is not exposed; `direction` does not move the package legend.")
    if "low_contrast" in selected:
        if "palette" in accepted:
            repairs.append(
                "Set `palette` with hex colours; runtime normalizes hex spelling and repairs colours below 3:1 contrast."
            )
        unsupported.append("Named CSS colours are rejected; use 3- or 6-digit hex values.")
    if "too_many_categories" in selected:
        repairs.append("Prefer `bar` for long labels or `table` when every category must remain readable.")
        if entry.additive_value and {"sort", "limit", "other"} <= accepted:
            repairs.append(
                "For additive values, combine `sort value desc`, `limit N`, and `other <label>` to retain the total."
            )
        else:
            unsupported.append("Do not use `limit` unless values are additive and the remainder can truthfully become Other.")
    if wanted and wanted not in KNOWN_PROBLEMS:
        repairs.append("No curated repair matches this problem; inspect the accepted and renderer-degraded keys below.")
    return list(dict.fromkeys(repairs)), list(dict.fromkeys(unsupported))


def _roles(entry: CatalogueEntry) -> dict:
    return {
        name: {"required": role.required, "accepted_column_kinds": list(role.kinds)}
        for name, role in entry.roles.items()
    }


def _config_schema(keys: set[str]) -> dict:
    vocabulary = KEYS | STYLE_KEYS
    result = {}
    for key in sorted(keys):
        _, kind = vocabulary[key]
        item = {"kind": kind}
        if kind.startswith("enum:"):
            item["choices"] = list(get_args(getattr(models, kind.removeprefix("enum:"))))
        elif key == "bind":
            item["roles"] = list(models.ROLES)
        elif key == "format":
            item["example"] = "0,0.00 SAR, 0.0%, or 0k"
        elif key == "innerRadius":
            item.update(minimum=0, maximum=1, unit="dimensionless ratio", example=0.6,
                        note="Pinned SSR pie API uses a 0–1 radius ratio, not a percentage or pixel count. "
                             "The harness rejects out-of-range values instead of letting the library clamp them.")
        elif key in {"palette", "backgroundColor"}:
            item["value"] = "3- or 6-digit hex colour"
        result[key] = item
    return result


def _chart_summary(entry: CatalogueEntry, renderer: str, problem: str = "") -> dict:
    capability = capability_for(renderer, entry.name)
    accepted = accepted_keys(entry)
    rejected = {key: reason for key, reason in capability.rejected.items() if key == "*" or key in accepted}
    degraded = {key: reason for key, reason in capability.degraded.items() if key in accepted}
    repairs, unsupported = _repairs(entry, problem)
    return {
        "chart_type": entry.name,
        "purpose": list(entry.purposes),
        "rating": entry.rating,
        "summary": entry.summary,
        "roles": _roles(entry),
        "common_config": sorted(accepted & set(common_keys())),
        "additional_config": sorted(accepted - set(common_keys())),
        "common_config_schema": _config_schema(accepted & set(common_keys())),
        "additional_config_schema": _config_schema(accepted - set(common_keys())),
        "renderer": {
            "target_type": entry.draw.type,
            "fixed_options": entry.draw.options,
            "status": "rejected" if "*" in rejected else "supported",
            "degraded_config": degraded,
            "rejected_config": rejected,
        },
        "repairs": repairs,
        "unsupported_repairs": unsupported,
    }


def _problem_summary(entry: CatalogueEntry, renderer: str, problem: str) -> dict:
    """Return only the executable facts needed to repair one named visual problem."""
    full = _chart_summary(entry, renderer, problem)
    wanted = _normalise_problem(problem)
    relevant = accepted_keys(entry) & PROBLEM_CONFIG.get(wanted, set())
    return {
        "chart_type": full["chart_type"],
        "renderer": full["renderer"],
        "repair_config_schema": _config_schema(relevant),
        "repairs": full["repairs"],
        "unsupported_repairs": full["unsupported_repairs"],
        "detail_hint": "Call again without `problem` only if the complete configuration schema is needed.",
    }


def _compact_provenance(package: dict) -> dict:
    return {
        "package": package["name"],
        "pinned_version": package["pinned_version"],
        "installed_version": package["installed_version"],
        "official_skill": OFFICIAL_SKILL["repository"],
    }


def chart_capabilities(chart_type: str = "", problem: str = "") -> dict:
    """Inspect executable chart configuration and renderer support.

    Args:
        chart_type: Internal vis chart type or alias. Empty returns a compact matrix for every chart.
        problem: Optional visual problem, such as label_overlap, legend_overlap, clipping,
            low_contrast, or too_many_categories, to return supported repair choices.
    """
    package = _renderer_package()
    native_types = _installed_native_types()
    renderer_targets = {entry.draw.type for entry in CATALOGUE.entries if entry.name != "indicator"}
    inventory = {
        "renderer": "gptvis",
        "package": package,
        "installed_native_types": native_types,
        "native_types_not_exposed_by_vis_dsl": sorted(set(native_types) - renderer_targets),
        "common_to_all_chart_types": common_keys(),
        "common_to_all_schema": _config_schema(set(common_keys())),
        "ordinary_chart_shared_vocabulary": sorted(COMMON_KEYS),
        "shared_vocabulary_note": (
            "Some shared transforms are data-conditional: limit requires additive values and a value sort; "
            "format changes display only; unknown supplies the label for an existing unknown category."
        ),
        "official_skill": OFFICIAL_SKILL,
        "known_problems": list(KNOWN_PROBLEMS),
    }
    if not chart_type.strip():
        inventory["charts"] = [{
            "chart_type": entry.name,
            "renderer_target": entry.draw.type,
            "fixed_options": entry.draw.options,
            "additional_config": sorted(accepted_keys(entry) - set(common_keys())),
            "renderer_status": _chart_summary(entry, "gptvis")["renderer"]["status"],
        } for entry in CATALOGUE.entries]
        return inventory
    entry = CATALOGUE.find(chart_type)
    if entry is None:
        return {
            "renderer": "gptvis",
            "provenance": _compact_provenance(package),
            "error": f"Unknown chart type or alias: {chart_type}",
            "available_chart_types": [item.name for item in CATALOGUE.entries],
        }
    # A targeted lookup should not repeat the renderer inventory, every native type,
    # every shared schema, and the official-skill prose. Those facts are useful for
    # discovery, but expensive noise during a repair loop.
    targeted_problem = _normalise_problem(problem) in KNOWN_PROBLEMS
    chart = (_problem_summary(entry, "gptvis", problem) if targeted_problem
             else _chart_summary(entry, "gptvis", problem))
    return {
        "renderer": "gptvis",
        "provenance": _compact_provenance(package),
        "response_scope": "problem_repair" if targeted_problem else "single_chart",
        "chart": chart,
    }
