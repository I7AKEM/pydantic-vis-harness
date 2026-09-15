# vis_agent/reviewer/agent.py
"""The reviewer: one look at the picture and the record, findings tied to rules, a verdict derived by code."""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic_ai import Agent, BinaryContent, ModelRetry, RunContext, ToolOutput
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage, UsageLimits

from vis_agent.analyst.models import AnalysisReport, Cell
from vis_agent.designer.models import Compromise, Design
from vis_agent.findings import Finding
from vis_agent.models import DataBrief, QuestionAnswer
from vis_agent.reviewer.models import Review, ReviewColumn, ReviewerPrompt, ReviewReport
from vis_agent.reviewer.rubric import rubric_text

log = logging.getLogger("reviewer")
# A seat other than the designer's, able to read a picture; the agreement test (evals/reviewer) picks the final one.
DEFAULT_REVIEWER_MODEL = "openrouter:openai/gpt-5.4"
REVIEWER_RULEBOOK = Path(__file__).with_name("rulebook.md").read_text(encoding="utf-8")
REVIEW_TIMEOUT_SECONDS = 60
MAX_REQUESTS = 3
ROWS_FOR_REVIEW = 100
CELL_CHARACTERS = 40
FIXERS = {"analyst", "designer", "renderer"}  # a finding owned by the user or by no one cannot be sent back


@dataclass
class ReviewerDeps:
    prompt: ReviewerPrompt


def deliver_review(ctx: RunContext[ReviewerDeps], findings: list[Finding], summary: str) -> Review:
    """Deliver the review: the findings, each tied to a rule with its level and owner, and a one-sentence summary
    in the caller's language. The verdict is not yours: an error the analyst, the designer, or the renderer can
    fix sends the chart back; a decision only the caller can make stays on the card as an open finding."""
    if not summary.strip():
        raise ModelRetry("Write one sentence saying what you saw.")
    verdict = "revise" if any(finding.level == "error" and finding.owner in FIXERS for finding in findings) else "pass"
    return Review(verdict=verdict, summary=summary.strip(), findings=findings)


def create_reviewer(model: str | Model) -> Agent[ReviewerDeps, Review]:
    return Agent(
        model,
        name="reviewer",
        deps_type=ReviewerDeps,
        output_type=ToolOutput(deliver_review, name="deliver_review"),
        retries={"output": 2},
        instructions=REVIEWER_RULEBOOK + "\n\n" + rubric_text(),
        # Reasoning off, said explicitly: the unified `thinking` setting is dropped for models whose profile does not
        # declare reasoning-off support, and the proxy's Qwen then reasons for two minutes per picture (7 s without).
        model_settings={"openai_reasoning_effort": "none", "thinking": False, "temperature": 0.0},
    )


def _cut(cell: Cell) -> Cell:
    return cell[:CELL_CHARACTERS - 1] + "…" if isinstance(cell, str) and len(cell) > CELL_CHARACTERS else cell


def build_prompt(report: AnalysisReport, design: Design, brief: DataBrief | None, compromises, warnings,
                 round_: int, clarifications=()) -> ReviewerPrompt:
    rows = report.result.rows
    return ReviewerPrompt(
        question=report.question, language=report.language, clarifications=list(clarifications),
        chart=design.chart, spec=design.spec,
        columns=[ReviewColumn(name=c.name, meaning=c.meaning, kind=c.kind, unit=c.unit) for c in report.analysis.columns],
        rows=[[_cut(cell) for cell in row] for row in rows[:ROWS_FOR_REVIEW]], row_count=report.result.row_count,
        rows_are_partial=len(rows) > ROWS_FOR_REVIEW, summary=report.analysis.summary,
        assumptions=list(report.analysis.assumptions),
        compromises=[c.message for c in (compromises or design.compromises)], warnings=list(warnings),
        caveats=list(brief.caveats) if brief else [], round=round_,
    )


async def review_chart(
    report: AnalysisReport, design: Design, png: Path, reviewer: Agent[ReviewerDeps, Review], *,
    brief: DataBrief | None = None, compromises: list[Compromise] | tuple = (), warnings: list[str] | tuple = (),
    round_: int = 1, usage: RunUsage | None = None, clarifications: list[QuestionAnswer] | tuple = (),
) -> ReviewReport:
    """Review one rendered chart. A reviewer that cannot finish, or a picture that cannot be read, is a warning:
    the chart delivers unreviewed and says so."""
    started = time.perf_counter()
    prompt = build_prompt(report, design, brief, compromises, warnings, round_, clarifications)
    deps = ReviewerDeps(prompt=prompt)
    run_usage = usage if usage is not None else RunUsage()
    starting = run_usage.requests
    output: Review | None = None
    model_name = None
    notes: list[str] = []
    try:
        picture = BinaryContent(data=png.read_bytes(), media_type="image/png")
        async with asyncio.timeout(REVIEW_TIMEOUT_SECONDS):
            result = await reviewer.run([prompt.model_dump_json(), picture], deps=deps, usage=run_usage,
                                        usage_limits=UsageLimits(request_limit=starting + MAX_REQUESTS))
        output = result.output
        model_name = result.response.model_name
    except (ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded, TimeoutError, OSError) as exc:
        log.warning("The reviewer could not finish %r on %s: %s", report.question, report.dataset_id, exc, exc_info=exc)
        detail = str(exc) or type(exc).__name__
        if isinstance(exc, UnexpectedModelBehavior) and exc.__cause__ is not None:
            cause = exc.__cause__
            detail = str(cause) if isinstance(cause, UnexpectedModelBehavior) else f"{detail}: {cause}"
        notes.append(f"The reviewer could not finish: {detail}")
    return ReviewReport(review=output, warnings=notes, model=model_name, requests=run_usage.requests - starting,
                        round=round_, seconds=time.perf_counter() - started, created_at=datetime.now(timezone.utc))
