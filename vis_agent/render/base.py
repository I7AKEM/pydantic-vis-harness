"""Renderer results, failures, and declared support for the spec vocabulary."""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from vis_agent.designer.models import ChartType, Compromise


MAX_RENDER_ERROR_CHARS = 800


def concise_render_error(value: object, *, limit: int = MAX_RENDER_ERROR_CHARS) -> str:
    """Bound Node diagnostics so minified bundles do not enter the agent context."""
    text = str(value).replace("\x00", "").strip()
    if not text:
        return "renderer failed without an error message"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    exception_prefixes = ("Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError")
    diagnostic = next((line for line in lines if line.startswith(exception_prefixes)), lines[0])
    if len(diagnostic) > limit:
        diagnostic = diagnostic[: limit - 1].rstrip() + "…"
    omitted = len(text) - len(diagnostic)
    return diagnostic + (f" [renderer detail omitted: {omitted} chars]" if omitted > 0 else "")


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

    def __init__(self, message: object):
        super().__init__(concise_render_error(message))


RENDERERS: dict[str, Callable[[ChartType], Capability]] = {}


def capability_for(renderer: str, chart_type: ChartType) -> Capability:
    if renderer not in RENDERERS:
        raise KeyError(f"Unknown renderer '{renderer}'; registered: {', '.join(RENDERERS)}")
    return RENDERERS[renderer](chart_type)
