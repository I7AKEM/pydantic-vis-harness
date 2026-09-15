"""The profiler agent, its review tool, the profile_dataset orchestration, and the lead's profile_csv tool."""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext, ToolFailed, ToolOutput
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from vis_agent.deps import AppDeps
from vis_agent.language import language_of
from vis_agent.store import DatasetNotFound, DatasetStore
from vis_agent.profiler.measurements import compute_statistics
from vis_agent.models import DataBrief
from vis_agent.profiler.models import (
    PROFILE_VERSION,
    DatasetProfile,
    DeterministicProfile,
    ProfileCheck,
    SemanticProfile,
)
from vis_agent.profiler.review import failed_checks, run_checks

log = logging.getLogger("profiler")
SEMANTIC_TIMEOUT_SECONDS = 90
# Concurrent callers without an explicit brief share the dataset task.
_in_flight: dict[str, asyncio.Task[DatasetProfile]] = {}

PROFILER_INSTRUCTIONS = Path(__file__).with_name("rulebook.md").read_text(encoding="utf-8")
"""The profiler's rulebook. Edit the file, not this module; the optimizer in evals/profiler reads and writes it."""


class ProfilerInput(BaseModel):
    statistics: DeterministicProfile
    brief: DataBrief | None = None
    language: str = "English"
    """The language of descriptions and meanings: the brief's question, else the column names; chosen by code."""
    review_attempts: int = 0  # counts send-backs within one run; never part of the prompt

    def prompt_json(self) -> str:
        return self.model_dump_json(exclude={"review_attempts"})


DEFAULT_PROFILER_MODEL = "openrouter:google/gemma-4-31b-it:nitro"
"""Fastest model in the Phase 1 benchmark, routed to the highest-throughput host; see docs/phase-1-lessons.md."""


def review_profile(ctx: RunContext[ProfilerInput], draft: SemanticProfile) -> SemanticProfile:
    """Submit the complete interpretation. Every column must appear exactly once, under its exact name.
    Checks that fail with severity error are sent back to you once, with their messages; fix them and submit again.
    """
    expected = {column.name for column in ctx.deps.statistics.columns}
    actual = [column.name for column in draft.columns]
    if set(actual) != expected or len(actual) != len(expected):
        raise ModelRetry("Return exactly one semantic entry per input column, using its exact name.")
    errors = failed_checks(run_checks(ctx.deps.statistics, draft, ctx.deps.brief, ctx.deps.language), "error")
    if errors and ctx.deps.review_attempts == 0:
        ctx.deps.review_attempts += 1
        raise ModelRetry("Fix these checks before returning: " + " ".join(c.message for c in errors))
    return draft


def create_profiler(model: str | Model) -> Agent[ProfilerInput, SemanticProfile]:
    agent = Agent(
        model,
        name="profiler",
        deps_type=ProfilerInput,
        output_type=ToolOutput(review_profile, name="review_profile"),
        retries={"output": 2},
        instructions=PROFILER_INSTRUCTIONS,
        # Interpretation, not reasoning: thinking only adds latency, and temperature 0 keeps runs repeatable.
        model_settings={"thinking": False, "temperature": 0.0},
    )

    return agent


async def profile_dataset(
    store: DatasetStore,
    profiler: Agent[ProfilerInput, SemanticProfile],
    dataset_id: str,
    brief: DataBrief | None = None,
    usage: RunUsage | None = None,
) -> DatasetProfile:
    """Measure, interpret, review, and save. Concurrent callers for one dataset share a single run.

    Raises DatasetNotFound, ValueError, or duckdb.Error.
    """
    running = _in_flight.get(dataset_id)
    if brief is None and running is not None:
        return await running
    task = asyncio.create_task(_profile_dataset(store, profiler, dataset_id, brief, usage))
    if brief is None:
        _in_flight[dataset_id] = task
    try:
        return await task
    finally:
        if _in_flight.get(dataset_id) is task:
            del _in_flight[dataset_id]


async def _run_with_one_retry(profiler, prompt: ProfilerInput, usage: RunUsage | None, dataset_id: str):
    """A stalled request costs the whole timeout; one retry turns most stalls into a delay, not a partial profile."""
    for attempt in (1, 2):
        try:
            async with asyncio.timeout(SEMANTIC_TIMEOUT_SECONDS):
                return await profiler.run(prompt.prompt_json(), deps=prompt, usage=usage)
        except TimeoutError:
            if attempt == 2:
                raise
            log.warning("Semantic profiling of %s timed out after %s s; retrying once", dataset_id, SEMANTIC_TIMEOUT_SECONDS)
            prompt.review_attempts = 0


async def _profile_dataset(
    store: DatasetStore,
    profiler: Agent[ProfilerInput, SemanticProfile],
    dataset_id: str,
    brief: DataBrief | None = None,
    usage: RunUsage | None = None,
) -> DatasetProfile:
    """Measure, interpret, review, and save. Raises DatasetNotFound, ValueError, or duckdb.Error."""
    source = await asyncio.to_thread(store.get_upload, dataset_id)
    if brief is not None:
        source = await asyncio.to_thread(store.update_brief, dataset_id, brief)
    brief = source.brief
    fingerprint = brief.fingerprint() if brief else None

    cached = await asyncio.to_thread(store.get_profile, dataset_id)
    if cached and cached.schema_version != PROFILE_VERSION:
        cached = None
    if cached and cached.status == "complete" and cached.brief_fingerprint == fingerprint:
        return cached
    source = await asyncio.to_thread(store.import_csv, dataset_id)
    statistics = cached.deterministic if cached else await asyncio.to_thread(compute_statistics, store, source)

    semantic = None
    semantic_model = None
    review: list[ProfileCheck] = []
    warnings: list[str] = []
    language = language_of(brief.raw_question if brief else None,
                           " ".join(column.original_name for column in statistics.columns))
    prompt = ProfilerInput(statistics=statistics, brief=brief, language=language)
    try:
        result = await _run_with_one_retry(profiler, prompt, usage, dataset_id)
        semantic = result.output
        semantic_model = result.response.model_name
        review = run_checks(statistics, semantic, brief, language)
        warnings.extend(check.message for check in failed_checks(review))
    except (ModelAPIError, UnexpectedModelBehavior, TimeoutError) as exc:
        log.warning("Semantic profiling failed for %s: %s", dataset_id, exc, exc_info=exc)
        warnings.append("Semantic profiling failed. The statistics are saved; profile this dataset again to retry.")

    profile = DatasetProfile(
        source=source,
        status="complete" if semantic is not None else "partial",
        deterministic=statistics,
        semantic=semantic,
        semantic_model=semantic_model,
        brief_fingerprint=fingerprint,
        review=review,
        warnings=warnings,
        created_at=datetime.now(timezone.utc),
    )
    await asyncio.to_thread(store.save_profile, profile)
    return profile


async def profile_csv(ctx: RunContext[AppDeps], uploaded_file_id: str) -> DatasetProfile:
    """Import an uploaded CSV and return its full deterministic and semantic profile.

    Args:
        uploaded_file_id: The ds_ ID returned by /datasets/upload.
    """
    try:
        return await profile_dataset(ctx.deps.store, ctx.deps.profiler, uploaded_file_id, usage=ctx.usage)
    except DatasetNotFound as exc:
        raise ToolFailed(str(exc)) from exc
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc
    except duckdb.Error as exc:
        log.warning("DuckDB could not import or profile %s: %s", uploaded_file_id, exc)
        raise ToolFailed("DuckDB could not import or profile this CSV. Check its data and upload it again.") from exc
