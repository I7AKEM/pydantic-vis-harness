"""What the lead's tools receive at run time."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vis_agent.store import DatasetStore

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from vis_agent.analyst.agent import AnalystDeps
    from vis_agent.analyst.models import Analysis, Clarification
    from vis_agent.profiler.agent import ProfilerInput
    from vis_agent.profiler.models import SemanticProfile


@dataclass
class AppDeps:
    store: DatasetStore
    profiler: Agent[ProfilerInput, SemanticProfile]
    analyst: Agent[AnalystDeps, Analysis | Clarification]
