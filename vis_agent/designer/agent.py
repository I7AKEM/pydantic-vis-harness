"""The chart expert: one-call design from the supplied CSV, with optional syntax repair."""

import asyncio
import logging
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext, ToolOutput
from pydantic_ai.models import Model
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RunUsage, UsageLimits

from vis_agent.analyst.models import (
    Aggregate, AnalysisReport, Cell, ColumnKind, RevisionRound,
)
from vis_agent.labels import LABEL_INSTRUCTIONS, apply_display_labels, project_display_labels
from vis_agent.models import DataBrief, DisplayLabels, Intent, QuestionAnswer
from vis_agent.model_settings import text_specialist_settings
from vis_agent.render import gptvis
from vis_agent.render.base import RENDERERS, Rendered

from . import models
from .catalogue import CATALOGUE
from .capabilities import chart_capabilities, common_keys
from .check import check_render_spec as run_check
from .models import Design, DesignReport, PreviousDesign, ReviewRound, SpecCheck
from .shape import describe
from .syntax import KEYS, STYLE_KEYS, parse, to_text

log = logging.getLogger("designer")
DEFAULT_DESIGNER_MODEL = "openrouter:deepseek/deepseek-v4-pro"
# Keep fallback behavior deterministic unless an operator explicitly configures another model.
DEFAULT_FALLBACK_DESIGNER_MODEL = DEFAULT_DESIGNER_MODEL
DESIGNER_RULEBOOK = Path(__file__).with_name("rulebook.md").read_text(encoding="utf-8")
REVISE_INSTRUCTIONS = Path(__file__).with_name("rulebook-revise.md").read_text(encoding="utf-8")
REVIEW_INSTRUCTIONS = Path(__file__).with_name("rulebook-review.md").read_text(encoding="utf-8")
DESIGN_TIMEOUT_SECONDS = 45
MAX_CHECK_CALLS = 3
MAX_REQUESTS = 8
PREVIEW_ROWS = 12
CELL_CHARACTERS = 40



class ResultFacts(BaseModel):
    """One result column's description and facts measured on the untruncated result."""

    name: str
    meaning: str
    kind: ColumnKind
    unit: str | None = None
    aggregate: Aggregate = "none"
    denominator: str | None = None
    partition_by: list[str] | None = None
    distinct: int
    longest_label: int
    minimum: float | None = None
    maximum: float | None = None
    has_negative: bool = False
    nulls: int = 0


class DesignerPrompt(BaseModel):
    """What the model reads; SQL and the dataset stay in code."""

    question: str
    raw_question: str | None = None
    enriched_question: str | None = None
    language: str
    intent: Intent | None = None
    suggested_chart_type: str | None = None
    brand_colors: list[str] = []
    caveats: list[str] = []
    code_meanings: dict[str, dict[str, str]] = Field(default_factory=dict)
    display_labels: DisplayLabels = Field(default_factory=DisplayLabels)
    summary: str | None = None
    assumptions: list[str] = []
    columns: list[ResultFacts]
    row_count: int
    preview: list[list[Cell]]
    preview_is_partial: bool
    required_columns: list[str] = []
    clarifications: list[QuestionAnswer] = []
    previous: PreviousDesign | None = None
    revision: RevisionRound | None = None
    review: ReviewRound | None = None


@dataclass
class DesignerDeps:
    report: AnalysisReport
    prompt: DesignerPrompt
    suggested: str | None
    required_columns: tuple[str, ...] = ()
    renderer: str = "gptvis"
    check_calls: int = 0
    intent: Intent | None = None
    last_check: SpecCheck | None = None
    last_violations: list[str] = field(default_factory=list)
    delivery_attempts: int = 0


def build_prompt(
    report: AnalysisReport, brief: DataBrief | None,
    clarifications: list[QuestionAnswer] | None = None, previous: PreviousDesign | None = None,
    revision: RevisionRound | None = None,
    review: ReviewRound | None = None,
    required_columns: list[str] | None = None,
) -> DesignerPrompt:
    shape = describe(report.analysis.columns, report.result, relationships=False)
    columns = []
    for column in report.analysis.columns:
        facts = shape.column(column.name)
        columns.append(ResultFacts(
            name=column.name, meaning=column.meaning, kind=column.kind, unit=column.unit,
            aggregate=column.aggregate, denominator=column.denominator, partition_by=column.partition_by,
            distinct=facts.distinct, longest_label=facts.longest_label,
            minimum=facts.minimum, maximum=facts.maximum,
            has_negative=facts.has_negative, nulls=facts.nulls,
        ))

    def cut(cell: Cell) -> Cell:
        if isinstance(cell, str) and len(cell) > CELL_CHARACTERS:
            return cell[:CELL_CHARACTERS - 1] + "…"
        return cell

    rows = report.result.rows
    meanings, labels = project_display_labels(brief, report.analysis.columns, report.language)
    return DesignerPrompt(
        question=report.question, language=report.language,
        raw_question=brief.raw_question if brief else None,
        enriched_question=brief.enriched_question if brief else None,
        intent=brief.intent if brief else None,
        suggested_chart_type=brief.suggested_chart_type if brief else None,
        brand_colors=brief.brand_colors if brief else [], caveats=brief.caveats if brief else [],
        code_meanings=meanings, display_labels=labels,
        summary=report.analysis.summary, assumptions=report.analysis.assumptions,
        columns=columns, row_count=report.result.row_count,
        preview=[[cut(cell) for cell in row] for row in rows[:PREVIEW_ROWS]],
        preview_is_partial=len(rows) > PREVIEW_ROWS or len(rows) < report.result.row_count,
        required_columns=list(required_columns or []),
        clarifications=list(clarifications or []), previous=previous, revision=revision, review=review,
    )


def prompt_json(prompt: DesignerPrompt) -> str:
    """Keep supplied intent verbatim; omit absent context and exact duplicate questions."""
    exclude = {name for name in ("raw_question", "enriched_question", "clarifications", "previous", "revision", "review")
               if not getattr(prompt, name)}
    if prompt.raw_question == prompt.question:
        exclude.add("raw_question")
    if prompt.enriched_question in (prompt.question, prompt.raw_question):
        exclude.add("enriched_question")
    return prompt.model_dump_json(exclude=exclude or None)


def grammar() -> str:
    lines = ["First line: vis <type>; choose a type from the catalogue."]
    for key, (_, kind) in [*KEYS.items(), *STYLE_KEYS.items()]:
        if key == "sort":
            description = ('one of ' + ", ".join(get_args(models.SortOrder))
                           + '; grouped value sorting orders categories by the sum of their series, '
                           'not by one selected series; none preserves source order')
        elif kind.startswith("enum:"):
            description = "one of " + ", ".join(get_args(getattr(models, kind.removeprefix("enum:"))))
        elif key == "bind":
            description = ('section; two-space-indented lines "<role> <column name>"; roles '
                           + ", ".join(models.ROLES))
        elif key == "fold":
            description = ('section; lines "- <column name>"; two or more measure columns of one unit, drawn as one '
                           'series each on a chart with a group role; leave group and value unbound, the code binds them; '
                           'category/time is not automatically bound')
        elif key == "cards":
            description = ('indicator only; one to six records starting with two-space-indented "- value <column name>"; '
                           'value and repeatable support take measure/share columns; repeatable context takes only '
                           'category/ordinal/time/geography/identifier columns; four-space lines '
                           '"context <column name>", "support <column name>", or "format <number pattern>"; '
                           'format controls precision/grouping and should omit the unit inherited from metadata; '
                           'ordinary bind must be empty')
        elif key == "columnLabels":
            description = ('all chart types; optional section with two-space lines '
                           '\'- ["exact column name", "display label"]\'; JSON string pairs; '
                           'label headers, axes, and metric names without changing data or units')
        elif key == "valueLabels":
            description = ('all chart types; optional section with two-space lines '
                           '\'- ["exact column name", "original value", "display label"]\'; JSON string triples; '
                           'map source category labels for display only; never replace numeric measurements')
        elif key == "style":
            description = "section; backgroundColor <hex>"
        elif key == "axisXTitle":
            description = "text; the horizontal axis title"
        elif key == "axisYTitle":
            description = "text; the vertical axis title"
        elif kind == "section:list":
            description = ('section; lines "- <hex>" using bare values such as #1783FF, without quotes; '
                           'indicator accepts one shared accent color, not one color per card'
                           if key == "palette" else 'section; lines "- <value>"')
        else:
            description = {"int": "integer", "bool": "true or false",
                           "format": "pattern like 0,0.00, 0.0%, or 0k; % is a suffix and never rescales"}.get(kind, kind)
        lines.append(f"{key}: {description}")
    lines.extend(["", "Example:", "vis table", "title Result", "description The answer to the question",
                  "", "Indicator label translation example:", "vis indicator", "title إجمالي الزوار",
                  "description إجمالي الزوار خلال الفترة", "language ar", "cards", "  - value visitor_count",
                  "columnLabels", '  - ["visitor_count", "إجمالي الزوار"]',
                  "", "Indicator role example (all bindings are source column names):", "cards",
                  "  - value female_pct", "    support female_count", "    support total_females",
                  "    context period", "  - value male_pct", "    support male_count",
                  "    support total_males", "    context period",
                  "", "Category display label syntax (use only established meanings):", "valueLabels",
                  '  - ["source column", "original category", "approved or established display wording"]'])
    return "\n".join(lines)


def instructions() -> str:
    return (DESIGNER_RULEBOOK + "\n\n" + LABEL_INSTRUCTIONS + "\n\nGrammar:\n" + grammar()
            + "\n\nConfiguration common to every chart type:\n" + ", ".join(common_keys())
            + "\n\nCatalogue:\n" + CATALOGUE.describe()
            + "\n\nCall chart_capabilities only when you need exact renderer support or a supported repair; "
              "routine designs should be delivered directly.")


def _with_display_labels(text: str, deps: DesignerDeps) -> str:
    """Save source-approved wording while preserving the ordinary syntax repair path."""
    try:
        spec = parse(text)
    except models.SpecError:
        return text
    return to_text(apply_display_labels(spec, deps.prompt.display_labels))


def offer_check_spec(ctx: RunContext[DesignerDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    return None if ctx.deps.check_calls >= MAX_CHECK_CALLS else tool_def


async def check_spec(ctx: RunContext[DesignerDeps], spec: str) -> SpecCheck:
    """Check a draft chart spec and return violations with fixes, or its canonical text and compromises."""
    deps = ctx.deps
    if deps.check_calls >= MAX_CHECK_CALLS:
        if deps.last_check is None:
            raise ModelRetry("You have used the three check calls of this run and none passed. Call deliver_design "
                             "with your best spec; a spec that still fails ends the run.")
        raise ModelRetry("You have used the three check calls of this run. Deliver the spec that passed.")
    deps.check_calls += 1
    check = run_check(_with_display_labels(spec, deps), deps.report.analysis.columns, deps.report.result,
                      deps.renderer, intent=deps.intent)
    if check.ok:
        deps.last_check = check
    else:
        deps.last_violations = [f"{v.rule}: {v.message}" for v in check.violations]
    return check


def deliver_design(ctx: RunContext[DesignerDeps], spec: str, explanation: str) -> Design:
    """Deliver your chart immediately. Code checks renderer bindings; the lead judges the design."""
    deps = ctx.deps
    report = deps.report
    labelled = _with_display_labels(spec, deps)
    check = run_check(labelled, report.analysis.columns, report.result,
                      deps.renderer, intent=deps.intent)
    failures = []
    try:
        parsed = parse(check.canonical if check.ok else labelled)
    except models.SpecError:
        parsed = None
    # Report all executable defects together. Otherwise an unsupported optional
    # key hides missing required bindings until the only repair turn is spent.
    if parsed is not None:
        used = set(report.result.columns) if parsed.type == "table" else set(parsed.bind.values()) | set(parsed.fold)
        for card in parsed.cards:
            used.update([card.value, *card.context, *card.support])
        missing = [name for name in deps.required_columns if name not in used]
        if missing:
            failures.append(
                "required_columns: the chart omits required result columns " + ", ".join(missing)
                + ". Bind every required column or choose a chart type that can represent them."
            )
    failures[:0] = [f"line {v.line or 1}: {v.rule}: {v.message}. {v.fix}" for v in check.violations]
    if failures:
        message = "\n".join(failures)
        if deps.last_check is None and deps.check_calls >= MAX_CHECK_CALLS:
            reasons = "; ".join(deps.last_violations or failures)
            raise UnexpectedModelBehavior("No spec passed the three checks; the last failed on: " + reasons)
        if deps.delivery_attempts == 0:
            deps.delivery_attempts += 1
            raise ModelRetry(message)
        # The agent's output retry budget also covers malformed output arguments.
        # A second failed delivery must stop here, without another repair turn.
        raise UnexpectedModelBehavior(message)
    deps.last_check = check
    compromises = list(check.compromises)
    return Design(spec=check.canonical, chart=parsed.type, intent=deps.intent,
                  explanation=explanation, considered=[parsed.type], compromises=compromises)


def create_designer(model: str | Model) -> Agent[DesignerDeps, Design]:
    agent = Agent(
        model,
        name="designer",
        deps_type=DesignerDeps,
        output_type=ToolOutput(deliver_design, name="deliver_design"),
        retries={"output": 2},
        instructions=instructions(),
        model_settings=text_specialist_settings(model),
    )
    agent.tool(check_spec, retries=1, prepare=offer_check_spec)
    agent.tool_plain(chart_capabilities)

    @agent.instructions
    def revise_rules(ctx: RunContext[DesignerDeps]) -> str | None:
        prompt = ctx.deps.prompt
        parts = []
        if (prompt.previous is not None and prompt.previous.spec is not None) or prompt.revision is not None:
            parts.append(REVISE_INSTRUCTIONS)
        if prompt.review is not None:
            parts.append(REVIEW_INSTRUCTIONS)
        return "\n\n".join(parts) or None

    return agent


async def design_chart(
    report: AnalysisReport,
    designer: Agent[DesignerDeps, Design],
    brief: DataBrief | None = None,
    renderer: str = "gptvis",
    usage: RunUsage | None = None,
    clarifications: list[QuestionAnswer] | None = None,
    previous: PreviousDesign | None = None,
    revision: RevisionRound | None = None,
    review: ReviewRound | None = None,
    usage_limits: UsageLimits | None = None,
    required_columns: list[str] | None = None,
) -> DesignReport:
    """Design directly from the supplied table; the lead owns all other consultations."""
    started = time.perf_counter()
    if report.analysis is None or report.result is None:
        raise ValueError("The report needs an analysis and a result table before design.")
    if report.result.row_count == 0 or not report.result.rows:
        return DesignReport(
            dataset_id=report.dataset_id, question=report.question, language=report.language,
            warnings=["The supplied CSV contains no rows to visualize."],
            seconds=time.perf_counter() - started, created_at=datetime.now(timezone.utc),
        )

    prompt = build_prompt(report, brief, clarifications=clarifications, previous=previous, revision=revision,
                          review=review, required_columns=required_columns)
    deps = DesignerDeps(report=report, prompt=prompt, suggested=prompt.suggested_chart_type,
                        required_columns=tuple(required_columns or ()), renderer=renderer, intent=prompt.intent)
    output: Design | None = None
    model_name = None
    warnings: list[str] = []
    run_usage = usage if usage is not None else RunUsage()
    starting_requests = run_usage.requests
    request_limit = min(starting_requests + MAX_REQUESTS, usage_limits.request_limit) \
        if usage_limits is not None and usage_limits.request_limit is not None else starting_requests + MAX_REQUESTS
    limits = replace(usage_limits, request_limit=request_limit) if usage_limits is not None \
        else UsageLimits(request_limit=request_limit)
    try:
        async with asyncio.timeout(DESIGN_TIMEOUT_SECONDS):
            result = await designer.run(
                prompt_json(prompt), deps=deps, usage=run_usage,
                usage_limits=limits,
            )
        output = result.output
        model_name = result.response.model_name
    except (ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded, TimeoutError) as exc:
        log.warning("The designer could not finish %r on %s: %s", report.question, report.dataset_id, exc, exc_info=exc)
        detail = str(exc) or type(exc).__name__
        if isinstance(exc, UnexpectedModelBehavior) and exc.__cause__ is not None:
            # An output function that raised on purpose is wrapped as "Exceeded maximum output retries"; report its reason.
            cause = exc.__cause__
            detail = str(cause) if isinstance(cause, UnexpectedModelBehavior) else f"{detail}: {cause}"
        warnings.append(f"The designer could not finish: {detail}")

    design = output if isinstance(output, Design) else None
    return DesignReport(
        dataset_id=report.dataset_id, question=report.question, language=report.language,
        design=design,
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
        raise ValueError("The report needs an analysis and a result table before rendering.")
    columns, result = report.analysis.columns, report.result
    check = run_check(design.spec, columns, result, renderer, intent=design.intent)
    if not check.ok:
        raise ValueError("\n".join(
            f"line {v.line or 1}: {v.rule}: {v.message}. {v.fix}" for v in check.violations
        ))
    return gptvis.render(parse(design.spec), columns, result, out_dir, compromises=check.compromises)
