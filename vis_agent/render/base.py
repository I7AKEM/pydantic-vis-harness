"""Renderer results, failures, and declared support for the spec vocabulary."""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from vis_agent.designer.models import ChartType, Compromise


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
    texts: list[str] | None = None
    text_bounds: list[dict] | None = None


class RendererUnavailable(Exception):
    """The renderer's runtime or package is unavailable."""


class RenderFailed(Exception):
    """The renderer could not produce the requested output."""


RENDERERS: dict[str, Callable[[ChartType], Capability]] = {}


def capability_for(renderer: str, chart_type: ChartType) -> Capability:
    if renderer not in RENDERERS:
        raise KeyError(f"Unknown renderer '{renderer}'; registered: {', '.join(RENDERERS)}")
    return RENDERERS[renderer](chart_type)
