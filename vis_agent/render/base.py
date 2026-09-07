"""Renderer results, failures, and declared support for the spec vocabulary."""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from vis_agent.designer.models import ChartType, Compromise
from vis_agent.designer.syntax import KEYS, STYLE_KEYS


class Capability(BaseModel):
    honoured: set[str]
    degraded: dict[str, str]
    rejected: dict[str, str]


class Rendered(BaseModel):
    png: Path
    html: Path
    config: Path
    width: int
    height: int
    seconds: float
    non_background_share: float
    compromises: list[Compromise]
    drawn_rows: int
    folded_rows: int
    dropped_rows: int


class RendererUnavailable(Exception):
    """The renderer's runtime or package is unavailable."""


class RenderFailed(Exception):
    """The renderer could not produce the requested output."""


RENDERERS: dict[str, Callable[[ChartType], Capability]] = {}


def capability_for(renderer: str, chart_type: ChartType) -> Capability:
    if renderer not in RENDERERS:
        raise KeyError(f"Unknown renderer '{renderer}'; registered: {', '.join(RENDERERS)}")
    return RENDERERS[renderer](chart_type)


# Task 6 moves this temporary registration into gptvis.py.
GPTVIS_HONOURED = set(KEYS) | set(STYLE_KEYS) | {"bind"}
GPTVIS_DEGRADED = {
    "direction": "the legend stays where the package puts it; the title and the category order follow the direction",
}


def _gptvis_capability(chart_type: ChartType) -> Capability:
    degraded = GPTVIS_DEGRADED
    if chart_type == "table":
        degraded = dict.fromkeys(
            ("subtitle", "labels", "legend", "axisXTitle", "axisYTitle", "direction", "format"),
            "tables are drawn as the package draws them",
        )
    return Capability(honoured=GPTVIS_HONOURED, degraded=degraded, rejected={})


RENDERERS["gptvis"] = _gptvis_capability
