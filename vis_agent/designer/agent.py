"""The chart designer: bounded result context, deterministic tools, and checked delivery."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import get_args

import duckdb
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext, ToolFailed, ToolOutput
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits

from vis_agent.analyst.agent import ARABIC, analyze_dataset
from vis_agent.analyst.checks import summary_numbers_exist
from vis_agent.analyst.models import Aggregate, AnalysisReport, Cell, Clarification, ColumnKind
from vis_agent.deps import AppDeps
from vis_agent.models import DataBrief, Intent
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL
from vis_agent.render import gptvis
from vis_agent.render.base import RENDERERS, Rendered, RendererUnavailable, RenderFailed
from vis_agent.store import DatasetNotFound

from . import models
from .catalogue import CATALOGUE
from .check import check_spec as run_check
from .models import Candidate, ChartType, Compromise, Design, DesignReport, Rejection, SpecCheck
from .recommend import recommend_charts as rank_charts
from .shape import describe
from .syntax import KEYS, STYLE_KEYS, parse, to_text

log = logging.getLogger("designer")
DEFAULT_DESIGNER_MODEL = DEFAULT_PROFILER_MODEL
DESIGNER_RULEBOOK = Path(__file__).with_name("rulebook.md").read_text(encoding="utf-8")
DESIGN_TIMEOUT_SECONDS = 90
MAX_RECOMMEND_CALLS = 2
MAX_CHECK_CALLS = 3
MAX_REQUESTS = 8
PREVIEW_ROWS = 12
CELL_CHARACTERS = 40
SHORTLIST = 5
LANGUAGE_CODES = {"Arabic": "ar", "English": "en"}
EMPTY_RESULT = {"Arabic": "النتيجة فارغة، لا يوجد ما يُرسم. هل تريد تعديل السؤال؟",
                "English": "The result has no rows, so there is nothing to draw. Do you want to change the question?"}


class ResultFacts(BaseModel):
    """One result column's description and facts measured on the untruncated result."""

    name: str
    meaning: str
    kind: ColumnKind
    unit: str | None = None
    aggregate: Aggregate = "none"
    denominator: str | None = None
    distinct: int
    longest_label: int
    minimum: float | None = None
    maximum: float | None = None
    has_negative: bool = False
    nulls: int = 0


class DesignerPrompt(BaseModel):
    """What the model reads; SQL and the dataset stay in code."""

    question: str
    language: str
    intent: Intent | None = None
    suggested_chart_type: str | None = None
    brand_colors: list[str] = []
    caveats: list[str] = []
    summary: str | None = None
    assumptions: list[str] = []
    columns: list[ResultFacts]
    row_count: int
    preview: list[list[Cell]]
    preview_is_partial: bool


class Shortlist(BaseModel):
    intent: Intent
    candidates: list[Candidate]
    rejected: list[Rejection]


class Refused(BaseModel):
    message: str


@dataclass
class DesignerDeps:
    report: AnalysisReport
    prompt: DesignerPrompt
    suggested: str | None
    renderer: str = "gptvis"
    recommend_calls: int = 0
    check_calls: int = 0
    intent: Intent | None = None
    considered: list[str] = field(default_factory=list)
    last_check: SpecCheck | None = None
    delivery_attempts: int = 0


def build_prompt(report: AnalysisReport, brief: DataBrief | None) -> DesignerPrompt:
    shape = describe(report.analysis.columns, report.result)
    columns = []
    for column in report.analysis.columns:
        facts = shape.column(column.name)
        columns.append(ResultFacts(
            name=column.name, meaning=column.meaning, kind=column.kind, unit=column.unit,
            aggregate=column.aggregate, denominator=column.denominator,
            distinct=facts.distinct, longest_label=facts.longest_label,
            minimum=facts.minimum, maximum=facts.maximum,
            has_negative=facts.has_negative, nulls=facts.nulls,
        ))

    def cut(cell: Cell) -> Cell:
        if isinstance(cell, str) and len(cell) > CELL_CHARACTERS:
            return cell[:CELL_CHARACTERS - 1] + "…"
        return cell

    rows = report.result.rows
    return DesignerPrompt(
        question=report.question, language=report.language,
        intent=brief.intent if brief else None,
        suggested_chart_type=brief.suggested_chart_type if brief else None,
        brand_colors=brief.brand_colors if brief else [], caveats=brief.caveats if brief else [],
        summary=report.analysis.summary, assumptions=report.analysis.assumptions,
        columns=columns, row_count=report.result.row_count,
        preview=[[cut(cell) for cell in row] for row in rows[:PREVIEW_ROWS]],
        preview_is_partial=len(rows) > PREVIEW_ROWS,
    )


def grammar() -> str:
    lines = ["First line: vis <type>; choose a type from the catalogue."]
    for key, (_, kind) in [*KEYS.items(), *STYLE_KEYS.items()]:
        if kind.startswith("enum:"):
            description = "one of " + ", ".join(get_args(getattr(models, kind.removeprefix("enum:"))))
        elif key == "bind":
            description = ('section; two-space-indented lines "<role> <column name>"; roles '
                           + ", ".join(models.ROLES))
        elif key == "style":
            description = "section; backgroundColor <hex>"
        elif key == "axisXTitle":
            description = "text; the category axis title (vertical on a bar)"
        elif key == "axisYTitle":
            description = "text; the value axis title (horizontal on a bar)"
        elif kind == "section:list":
            description = 'section; lines "- <hex>"' if key == "palette" else 'section; lines "- <value>"'
        else:
            description = {"int": "integer", "bool": "true or false",
                           "format": "pattern like 0,0.00 SAR, 0.0%, 0k"}.get(kind, kind)
        lines.append(f"{key}: {description}")
    lines.extend(["", "Example:", "vis table", "title Result", "description The answer to the question"])
    return "\n".join(lines)


def instructions() -> str:
    return DESIGNER_RULEBOOK + "\n\nGrammar:\n" + grammar() + "\n\nCatalogue:\n" + CATALOGUE.describe()


async def recommend_charts(ctx: RunContext[DesignerDeps], intent: Intent) -> Shortlist | Refused:
    """Rank charts for your reading of the question's intent, with bindings and the rules behind each score."""
    deps = ctx.deps
    if deps.recommend_calls >= MAX_RECOMMEND_CALLS:
        return Refused(message=f"You have used the {MAX_RECOMMEND_CALLS} recommendation calls of this run. "
                               "Choose among the candidates you already have.")
    deps.recommend_calls += 1
    deps.intent = intent
    ranked = rank_charts(deps.report.analysis.columns, deps.report.result, intent=intent, suggested=deps.suggested)
    candidates = ranked.candidates[:SHORTLIST]
    deps.considered = [candidate.name for candidate in candidates]
    return Shortlist(intent=intent, candidates=candidates, rejected=ranked.rejected)


async def check_spec(ctx: RunContext[DesignerDeps], spec: str) -> SpecCheck | Refused:
    """Check a draft chart spec and return violations with fixes, or its canonical text and compromises."""
    deps = ctx.deps
    if deps.check_calls >= MAX_CHECK_CALLS:
        return Refused(message="You have used the three check calls of this run. "
                               "Deliver the spec that passed, or ask the caller a question.")
    deps.check_calls += 1
    check = run_check(spec, deps.report.analysis.columns, deps.report.result, deps.renderer)
    if check.ok:
        deps.last_check = check
    return check


def deliver_design(ctx: RunContext[DesignerDeps], spec: str, explanation: str) -> Design:
    """Deliver a checked spec and a two-sentence explanation in the caller's language using supported numbers."""
    deps = ctx.deps
    report = deps.report
    check = run_check(spec, report.analysis.columns, report.result, deps.renderer)
    failures = []
    if check.ok:
        parsed = parse(check.canonical)
        language = LANGUAGE_CODES[report.language]
        if parsed.language != language:
            parsed.language = language
            spec = to_text(parsed)
            check = run_check(spec, report.analysis.columns, report.result, deps.renderer)
        arabic_title = bool(ARABIC.search(parsed.title or ""))
        if arabic_title != (report.language == "Arabic"):
            failures.append(f"Write the title in {report.language}.")
    failures[:0] = [f"line {v.line or 1}: {v.rule}: {v.message}. {v.fix}" for v in check.violations]
    context = " ".join([report.question, *report.result.columns])
    number_check = summary_numbers_exist(explanation, report.result, context)
    if not number_check.passed:
        failures.append(number_check.message)
    if failures:
        message = "\n".join(failures)
        if deps.delivery_attempts == 0:
            deps.delivery_attempts += 1
            raise ModelRetry(message)
        # The agent's output retry budget also covers malformed output arguments.
        # A second failed delivery must stop here, without another repair turn.
        raise UnexpectedModelBehavior(message)
    deps.last_check = check
    return Design(spec=check.canonical, chart=parsed.type, intent=deps.intent,
                  explanation=explanation, considered=list(deps.considered), compromises=check.compromises)


def ask_clarification(ctx: RunContext[DesignerDeps], question: str, reason: str) -> Clarification:
    """Ask one question in the caller's language when the result or requested colors cannot support the chart."""
    return Clarification(question=question, reason=reason)


def create_designer(model: str) -> Agent[DesignerDeps, Design | Clarification]:
    agent = Agent(
        model,
        name="designer",
        deps_type=DesignerDeps,
        output_type=[ToolOutput(deliver_design, name="deliver_design"),
                     ToolOutput(ask_clarification, name="ask_clarification")],
        retries={"output": 2},
        instructions=instructions(),
        model_settings={"thinking": False, "temperature": 0.0},
    )
    agent.tool(recommend_charts)
    agent.tool(check_spec)
    return agent


async def design_chart(
    report: AnalysisReport,
    designer: Agent[DesignerDeps, Design | Clarification],
    brief: DataBrief | None = None,
    renderer: str = "gptvis",
    usage: RunUsage | None = None,
) -> DesignReport:
    """Design a chart from a saved analysis, returning a checked design, a clarification, or a warning."""
    started = time.perf_counter()
    if report.analysis is None or report.result is None:
        raise ValueError("The report needs an analysis and a result; resolve any clarification with the analyst first.")
    if report.result.row_count == 0 or not report.result.rows:
        return DesignReport(
            dataset_id=report.dataset_id, question=report.question, language=report.language,
            clarification=Clarification(question=EMPTY_RESULT[report.language], reason="The result is empty."),
            seconds=time.perf_counter() - started, created_at=datetime.now(timezone.utc),
        )

    prompt = build_prompt(report, brief)
    deps = DesignerDeps(report=report, prompt=prompt, suggested=prompt.suggested_chart_type, renderer=renderer)
    output: Design | Clarification | None = None
    model_name = None
    warnings: list[str] = []
    run_usage = usage if usage is not None else RunUsage()
    starting_requests = run_usage.requests
    try:
        async with asyncio.timeout(DESIGN_TIMEOUT_SECONDS):
            result = await designer.run(
                prompt.model_dump_json(), deps=deps, usage=run_usage,
                usage_limits=UsageLimits(request_limit=starting_requests + MAX_REQUESTS),
            )
        output = result.output
        model_name = result.response.model_name
    except (ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded, TimeoutError) as exc:
        log.warning("The designer could not finish %r on %s: %s", report.question, report.dataset_id, exc, exc_info=exc)
        detail = str(exc)
        if isinstance(exc, UnexpectedModelBehavior) and exc.__cause__ is not None:
            detail += f": {exc.__cause__}"
        warnings.append(f"The designer could not finish: {detail}")

    design = output if isinstance(output, Design) else None
    return DesignReport(
        dataset_id=report.dataset_id, question=report.question, language=report.language,
        design=design, clarification=output if isinstance(output, Clarification) else None,
        check=deps.last_check if design is not None else None, warnings=warnings, model=model_name,
        requests=run_usage.requests - starting_requests, check_calls=deps.check_calls,
        seconds=time.perf_counter() - started, created_at=datetime.now(timezone.utc),
    )


def render_id(spec: str, report: AnalysisReport) -> str:
    """Identify a render by its spec and serialized analysis report."""
    return sha256((spec + report.model_dump_json()).encode("utf-8")).hexdigest()[:12]


def render_design(
    report: AnalysisReport, design: Design, out_dir: Path, renderer: str = "gptvis",
) -> Rendered:
    """Recheck a delivered design and render it with the current check's compromises."""
    if renderer not in RENDERERS:
        raise ValueError(f"Unknown renderer '{renderer}'; registered: {', '.join(RENDERERS)}")
    if report.analysis is None or report.result is None:
        raise ValueError("The report needs an analysis and a result; resolve any clarification with the analyst first.")
    columns, result = report.analysis.columns, report.result
    check = run_check(design.spec, columns, result, renderer)
    if not check.ok:
        raise ValueError("\n".join(
            f"line {v.line or 1}: {v.rule}: {v.message}. {v.fix}" for v in check.violations
        ))
    return gptvis.render(parse(design.spec), columns, result, out_dir, compromises=check.compromises)


class LeadChart(BaseModel):
    """What the lead sees: a checked design and its rendered URLs, or a clarification."""

    dataset_id: str
    question: str
    chart: ChartType | None = None
    spec: str | None = None
    explanation: str | None = None
    summary: str | None = None
    clarification: Clarification | None = None
    compromises: list[Compromise] = []
    warnings: list[str] = []
    render_id: str | None = None
    png_url: str | None = None
    html_url: str | None = None


async def make_chart(ctx: RunContext[AppDeps], dataset_id: str, question: str) -> LeadChart:
    """Answer a question about a dataset with a chart: the picture's URL, the spec, and a two-sentence explanation, or the question the analyst or the designer needs answered first.

    Args:
        dataset_id: The ds_ ID of an uploaded dataset.
        question: The user's question, as they wrote it.
    """
    store = ctx.deps.store
    try:
        report = await analyze_dataset(store, ctx.deps.profiler, ctx.deps.analyst, dataset_id, question,
                                       usage=ctx.usage)
    except DatasetNotFound as exc:
        raise ToolFailed(str(exc)) from exc
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc
    except duckdb.Error as exc:
        log.warning("DuckDB failed while answering %r on %s: %s", question, dataset_id, exc)
        raise ToolFailed("DuckDB could not run the analysis on this dataset.") from exc

    answer = LeadChart(dataset_id=report.dataset_id, question=report.question,
                       summary=report.analysis.summary if report.analysis else None,
                       clarification=report.clarification, warnings=report.warnings)
    if report.clarification is not None or report.analysis is None or report.result is None:
        return answer

    brief = (await asyncio.to_thread(store.get_upload, dataset_id)).brief
    designed = await design_chart(report, ctx.deps.designer, brief, usage=ctx.usage)
    answer.warnings.extend(designed.warnings)
    answer.clarification = designed.clarification
    if designed.clarification is not None or designed.design is None:
        return answer

    design = designed.design
    answer.chart, answer.spec, answer.explanation = design.chart, design.spec, design.explanation
    answer.compromises = design.compromises
    identifier = render_id(design.spec, report)
    try:
        rendered = await asyncio.to_thread(render_design, report, design, store.directory / "renders" / identifier)
    except (RendererUnavailable, RenderFailed) as exc:
        answer.warnings.append(f"The chart could not be rendered: {exc}")
        return answer
    answer.compromises = rendered.compromises
    answer.render_id = identifier
    answer.png_url = f"/renders/{identifier}/chart.png"
    answer.html_url = f"/renders/{identifier}/chart.html"
    return answer
