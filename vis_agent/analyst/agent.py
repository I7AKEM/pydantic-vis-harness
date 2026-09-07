# vis_agent/analyst/agent.py
"""The analyst agent: one guarded SELECT on the dataset, checked against the data, described, and summarised."""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext, ToolFailed, ToolOutput
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits

from vis_agent.analyst.checks import check_result, summary_numbers_exist
from vis_agent.analyst.models import Analysis, AnalysisReport, Clarification, QueryError, QueryResult, ResultColumn
from vis_agent.analyst.query import run_sql
from vis_agent.deps import AppDeps
from vis_agent.models import DataBrief
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, ProfilerInput, profile_dataset
from vis_agent.profiler.models import DatasetProfile, ProfileCheck, SemanticProfile
from vis_agent.profiler.review import failed_checks
from vis_agent.store import DatasetNotFound, DatasetStore, quote_identifier

log = logging.getLogger("analyst")
DEFAULT_ANALYST_MODEL = DEFAULT_PROFILER_MODEL
"""The profiler's Gemma until the Phase 2 benchmark picks the analyst's default; see the Phase 2 design, section 12."""
ANALYST_INSTRUCTIONS = Path(__file__).with_name("rulebook.md").read_text(encoding="utf-8")
"""The analyst's rulebook. Edit the file, not this module."""
LOCALIZED_INSTRUCTIONS = Path(__file__).with_name("rulebook-localized.md").read_text(encoding="utf-8")
"""Rules for Hijri dates and Arabic-Indic digits, added per run only when a column carries those levels."""
ANALYSIS_TIMEOUT_SECONDS = 90
MAX_QUERY_CALLS = 3
MAX_REQUESTS = 8
PROMPT_DISTINCT_VALUES = 12
ARABIC = re.compile(r"[؀-ۿ]")


class ColumnFacts(BaseModel):
    """One column as the analyst sees it: measured facts and the profiler's interpretation. Never raw rows."""

    name: str
    physical_type: str
    measurement_levels: list[str] = []
    role: str | None = None
    meaning: str | None = None
    unit: str | None = None
    code_meanings: dict[str, str] | None = None
    brief_conflict: str | None = None
    null_percentage: float
    distinct_count: int
    common_values: list[str] = []
    common_values_are_a_sample: bool = False
    minimum: float | None = None
    maximum: float | None = None
    earliest: str | None = None
    latest: str | None = None
    ordinal_pattern: str | None = None
    geographic_role: str | None = None
    values_omitted: bool = False


class AnalystPrompt(BaseModel):
    """What the model reads."""

    table: str
    row_count: int
    columns: list[ColumnFacts]
    question: str
    language: str
    brief: DataBrief | None = None


@dataclass
class PassedQuery:
    sql: str
    columns: list[ResultColumn]
    result: QueryResult


@dataclass
class AnalystDeps:
    store: DatasetStore
    profile: DatasetProfile
    prompt: AnalystPrompt
    query_calls: int = 0
    passed: PassedQuery | None = None
    delivery_attempts: int = 0


def detect_language(question: str, brief: DataBrief | None, column_names: list[str]) -> str:
    """Once, from the question's script; then the brief's raw question; then the column names."""
    for text in (question, brief.raw_question if brief else None, " ".join(column_names)):
        if text and text.strip():
            return "Arabic" if ARABIC.search(text) else "English"
    return "English"


def build_prompt(store: DatasetStore, profile: DatasetProfile, question: str, language: str) -> AnalystPrompt:
    semantics = {c.name: c for c in profile.semantic.columns} if profile.semantic else {}
    table = quote_identifier(store.table_name(profile.source.dataset_id))
    columns = []
    with store.connect() as connection:
        for stats in profile.deterministic.columns:
            semantic = semantics.get(stats.name)
            common = [v.value for v in stats.common_values]
            if (stats.physical_type == "VARCHAR" and not stats.values_omitted
                    and 1 < stats.distinct_count <= PROMPT_DISTINCT_VALUES):
                common = [str(v) for (v,) in connection.execute(
                    f"SELECT DISTINCT {quote_identifier(stats.name)} FROM {table} "
                    f"WHERE {quote_identifier(stats.name)} IS NOT NULL ORDER BY 1").fetchall()]
            columns.append(ColumnFacts(
                name=stats.name, physical_type=stats.physical_type,
                # Only the two localized levels reach the prompt; the generic ones are noise for the analyst.
                measurement_levels=[level for level in stats.measurement_levels if level in ("hijri", "arabic_digits")],
                role=semantic.role if semantic else None, meaning=semantic.meaning if semantic else None,
                unit=semantic.unit if semantic else None, code_meanings=semantic.code_meanings if semantic else None,
                brief_conflict=semantic.brief_conflict if semantic else None,
                null_percentage=round(stats.null_percentage, 1), distinct_count=stats.distinct_count,
                common_values=common,
                common_values_are_a_sample=stats.distinct_count > PROMPT_DISTINCT_VALUES,
                minimum=stats.numeric.minimum if stats.numeric else None,
                maximum=stats.numeric.maximum if stats.numeric else None,
                earliest=stats.earliest, latest=stats.latest, ordinal_pattern=stats.ordinal_pattern,
                geographic_role=stats.geographic_role, values_omitted=stats.values_omitted,
            ))
    return AnalystPrompt(table=table, row_count=profile.deterministic.row_count, columns=columns,
                         question=question, language=language, brief=profile.source.brief)


async def run_query(ctx: RunContext[AnalystDeps], sql: str, columns: list[ResultColumn]) -> QueryResult | QueryError:
    """Run one SELECT on the dataset table and check the result against the data.

    Args:
        sql: One SELECT statement on the dataset table only, in DuckDB SQL.
        columns: One description per result column, in result order, with the exact result names.
    """
    deps = ctx.deps
    if deps.query_calls >= MAX_QUERY_CALLS:
        return QueryError(sql=sql, error=f"You have used the {MAX_QUERY_CALLS} query calls of this run. "
                                          "Deliver the last result that passed its checks, or ask the caller a question.")
    deps.query_calls += 1
    result = await asyncio.to_thread(
        run_sql, deps.store, deps.profile.source.dataset_id, sql,
        omitted={c.name.casefold() for c in deps.profile.deterministic.columns if c.values_omitted},
    )
    if isinstance(result, QueryError):
        return result
    result.checks = await asyncio.to_thread(check_result, deps.store, deps.profile, columns, result)
    if not failed_checks(result.checks, "error"):
        deps.passed = PassedQuery(sql=sql, columns=columns, result=result)
    return result


def _context(deps: AnalystDeps) -> str:
    """The question and the result's column names: numbers written there are wording, not claims."""
    columns = deps.passed.result.columns if deps.passed else []
    return " ".join([deps.prompt.question, *columns])


def deliver_analysis(ctx: RunContext[AnalystDeps], summary: str, assumptions: list[str] | None = None) -> Analysis:
    """Deliver the answer: a two-sentence summary in the caller's language using only numbers from the result,
    and the assumptions you made. The last query that passed its checks is delivered with it.
    """
    deps = ctx.deps
    if deps.passed is None:
        raise ModelRetry("No query has passed its checks yet. Call run_query and fix every check with severity "
                         "error, or call ask_clarification when the columns cannot answer the question.")
    check = summary_numbers_exist(summary, deps.passed.result, _context(deps))
    if not check.passed and deps.delivery_attempts == 0:
        deps.delivery_attempts += 1
        raise ModelRetry(check.message)
    return Analysis(sql=deps.passed.sql, columns=deps.passed.columns, summary=summary, assumptions=assumptions or [])


def ask_clarification(ctx: RunContext[AnalystDeps], question: str, reason: str) -> Clarification:
    """Ask the caller one question, in the caller's language, when the columns cannot answer the question or a
    term in it has no definition. Say in reason what is missing.
    """
    return Clarification(question=question, reason=reason)


def create_analyst(model: str) -> Agent[AnalystDeps, Analysis | Clarification]:
    agent = Agent(
        model,
        name="analyst",
        deps_type=AnalystDeps,
        output_type=[ToolOutput(deliver_analysis, name="deliver_analysis"),
                     ToolOutput(ask_clarification, name="ask_clarification")],
        retries={"output": 2},
        instructions=ANALYST_INSTRUCTIONS,
        # Thinking off and temperature 0 until the Phase 2 benchmark says otherwise.
        model_settings={"thinking": False, "temperature": 0.0},
    )
    agent.tool(run_query)

    @agent.instructions
    def localized_rules(ctx: RunContext[AnalystDeps]) -> str | None:
        # Long SQL recipes in the always-on rulebook cost accuracy on ordinary data (67 of 69 against 64);
        # they reach the model only when a column needs them.
        if any(column.measurement_levels for column in ctx.deps.prompt.columns):
            return LOCALIZED_INSTRUCTIONS
        return None

    return agent


async def analyze_dataset(
    store: DatasetStore,
    profiler: Agent[ProfilerInput, SemanticProfile],
    analyst: Agent[AnalystDeps, Analysis | Clarification],
    dataset_id: str,
    question: str,
    brief: DataBrief | None = None,
    usage: RunUsage | None = None,
) -> AnalysisReport:
    """Profile if needed, then answer one question. Raises DatasetNotFound, ValueError, or duckdb.Error."""
    started = time.perf_counter()
    profile = await profile_dataset(store, profiler, dataset_id, brief=brief, usage=usage)
    language = detect_language(question, profile.source.brief, [c.name for c in profile.deterministic.columns])
    prompt = await asyncio.to_thread(build_prompt, store, profile, question, language)
    deps = AnalystDeps(store=store, profile=profile, prompt=prompt)
    output: Analysis | Clarification | None = None
    model_name = None
    warnings: list[str] = []
    try:
        async with asyncio.timeout(ANALYSIS_TIMEOUT_SECONDS):
            result = await analyst.run(prompt.model_dump_json(), deps=deps, usage=usage,
                                       usage_limits=UsageLimits(request_limit=(usage.requests if usage is not None else 0) + MAX_REQUESTS))
        output = result.output
        model_name = result.response.model_name
    except (ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded, TimeoutError) as exc:
        log.warning("The analyst could not answer %r on %s: %s", question, dataset_id, exc, exc_info=exc)
        warnings.append(f"The analyst could not answer: {exc}")

    analysis = output if isinstance(output, Analysis) else None
    checks: list[ProfileCheck] = []
    table = None
    if analysis is not None and deps.passed is not None:
        table = deps.passed.result
        checks = [*table.checks, summary_numbers_exist(analysis.summary, table, _context(deps))]
        warnings.extend(check.message for check in failed_checks(checks))
    return AnalysisReport(
        dataset_id=dataset_id, question=question, language=language,
        brief_fingerprint=profile.brief_fingerprint, analysis=analysis,
        clarification=output if isinstance(output, Clarification) else None,
        result=table, checks=checks, warnings=warnings, model=model_name,
        seconds=time.perf_counter() - started, created_at=datetime.now(timezone.utc),
    )


LEAD_ROWS = 50


class LeadAnswer(BaseModel):
    """What the lead sees: the answer, bounded to LEAD_ROWS rows."""

    dataset_id: str
    question: str
    summary: str | None = None
    assumptions: list[str] = []
    clarification: Clarification | None = None
    columns: list[ResultColumn] = []
    rows: list[list] = []
    row_count: int = 0
    sql: str | None = None
    warnings: list[str] = []

    @classmethod
    def from_report(cls, report: AnalysisReport) -> "LeadAnswer":
        analysis, table = report.analysis, report.result
        return cls(
            dataset_id=report.dataset_id, question=report.question,
            summary=analysis.summary if analysis else None,
            assumptions=analysis.assumptions if analysis else [],
            clarification=report.clarification,
            columns=analysis.columns if analysis else [],
            rows=table.rows[:LEAD_ROWS] if table else [],
            row_count=table.row_count if table else 0,
            sql=analysis.sql if analysis else None,
            warnings=report.warnings,
        )


async def answer_question(ctx: RunContext["AppDeps"], dataset_id: str, question: str) -> LeadAnswer:
    """Answer a question about an uploaded dataset with a result table and a two-sentence summary, or return the
    question the analyst needs answered first.

    Args:
        dataset_id: The ds_ ID of an uploaded dataset.
        question: The user's question, as they wrote it.
    """
    try:
        report = await analyze_dataset(ctx.deps.store, ctx.deps.profiler, ctx.deps.analyst, dataset_id, question,
                                       usage=ctx.usage)
    except DatasetNotFound as exc:
        raise ToolFailed(str(exc)) from exc
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc
    except duckdb.Error as exc:
        log.warning("DuckDB failed while answering %r on %s: %s", question, dataset_id, exc)
        raise ToolFailed("DuckDB could not run the analysis on this dataset.") from exc
    return LeadAnswer.from_report(report)
