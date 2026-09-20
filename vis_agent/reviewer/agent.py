# vis_agent/reviewer/agent.py
"""The reviewer: one look at the picture and the record, findings tied to rules, a verdict derived by code."""

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, replace
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
from vis_agent.labels import project_display_labels
from vis_agent.profiler.measurements import GEOMETRY_NAME, MAX_MODEL_VALUE_BYTES, WKT_SQL_PATTERN
from vis_agent.reviewer.models import Review, ReviewColumn, ReviewerPrompt, ReviewReport, VisualFinding
from vis_agent.reviewer.rubric import rubric_text

log = logging.getLogger("reviewer")
# A seat other than the designer's, able to read a picture; the agreement test (evals/reviewer) picks the final one.
DEFAULT_REVIEWER_MODEL = "openrouter:google/gemma-4-31b-it"
REVIEWER_RULEBOOK = Path(__file__).with_name("rulebook.md").read_text(encoding="utf-8")
REVIEW_TIMEOUT_SECONDS = 30
MAX_REQUESTS = 3
ROWS_FOR_REVIEW = 30
CELL_CHARACTERS = 40
WKT_VALUE = re.compile(WKT_SQL_PATTERN, re.IGNORECASE)


@dataclass
class ReviewerDeps:
    prompt: ReviewerPrompt


def _validate_reference(finding: VisualFinding, prompt: ReviewerPrompt) -> None:
    """Check source addresses and coverage only. This cannot validate what a vision model saw."""
    ref = finding.reference
    if ref.kind == "cell":
        row_ids = prompt.row_ids or list(range(1, len(prompt.rows) + 1))
        if ref.row not in row_ids:
            raise ModelRetry("The cited source row is outside the supplied reference. Do not infer an error from unseen rows.")
        row = prompt.rows[row_ids.index(ref.row)]
        if ref.column not in row or ref.column in prompt.truncated_cells.get(ref.row, []):
            raise ModelRetry("The cited cell is omitted or abbreviated; its full value cannot support this finding.")
        value = row[ref.column]
        expected = str(value) if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if ref.quote != expected:
            raise ModelRetry("Quote the exact cited cell value, preserving its value and unit. Do not substitute a plausible value.")
    elif ref.kind == "column":
        column = next((c for c in prompt.columns if c.name == ref.column), None)
        if column is None or not ref.quote or ref.quote not in column.model_dump_json():
            raise ModelRetry("The column reference must name a supplied column and quote its metadata exactly.")
    elif ref.kind in {"spec", "request"}:
        text = prompt.spec if ref.kind == "spec" else "\n".join([
            prompt.question, prompt.original_question or "", *prompt.caveats,
            *(f"{c.question}\n{c.answer}" for c in prompt.clarifications),
        ])
        if not ref.quote or ref.quote not in text:
            raise ModelRetry("The finding must quote an actual supplied spec or request constraint, not an inferred preference.")
    elif ref.kind == "source" and (prompt.rows_are_partial or prompt.truncated_cells or prompt.omitted_columns):
        raise ModelRetry("The source reference is incomplete. Its excerpt cannot establish absence from the full source; "
                         "cite a visible contradiction with a supplied cell or report uncertainty.")


def deliver_review(ctx: RunContext[ReviewerDeps], findings: list[VisualFinding], summary: str,
                   uncertainties: list[str] = ()) -> Review:
    """Report visible defects with observed/expected evidence, plus any material limits on inspection.
    Any error means a material defect, not an automatic repair handoff: the lead decides what to do.
    Code checks reference addresses, not visual truth; uncertainty is not a defect."""
    if not summary.strip():
        raise ModelRetry("Write one sentence saying what you saw.")
    for finding in findings:
        if finding.level == "error" and finding.observed.strip() == finding.expected.strip():
            raise ModelRetry("Identical observed and expected evidence does not establish a defect. Correct the finding "
                             "or report the material uncertainty; do not invent a difference.")
        _validate_reference(finding, ctx.deps.prompt)
    if any(not note.strip() for note in uncertainties):
        raise ModelRetry("Each uncertainty must name what could not be inspected; omit empty entries.")
    verdict = "revise" if any(finding.level == "error" for finding in findings) else "uncertain" if uncertainties else "pass"
    converted = [Finding(rule=f.rule, level=f.level, owner=f.owner,
                         message=f"{f.location}: {f.observed} — {f.expected} "
                                 f"[reference: {f.reference.model_dump_json(exclude_none=True)}]") for f in findings]
    return Review(verdict=verdict, summary=summary.strip(), findings=converted, evidence=findings,
                  uncertainties=[note.strip() for note in uncertainties], image_id=ctx.deps.prompt.image_id)


def create_reviewer(model: str | Model) -> Agent[ReviewerDeps, Review]:
    return Agent(
        model,
        name="reviewer",
        deps_type=ReviewerDeps,
        output_type=ToolOutput(deliver_review, name="deliver_review"),
        retries={"output": 2},
        instructions=REVIEWER_RULEBOOK + "\n\n" + rubric_text(),
        model_settings={"thinking": False, "temperature": 0.0},
    )


def _cut(cell: Cell) -> Cell:
    return cell[:CELL_CHARACTERS - 1] + "…" if isinstance(cell, str) and len(cell) > CELL_CHARACTERS else cell


def build_prompt(report: AnalysisReport, design: Design, brief: DataBrief | None, compromises, warnings,
                 round_: int, clarifications=()) -> ReviewerPrompt:
    rows = report.result.rows
    # The source reader normally removes these columns. Defend this boundary too for saved/legacy reports.
    omitted = {
        name for index, name in enumerate(report.result.columns)
        if GEOMETRY_NAME.search(name) or any(
            isinstance(row[index], str) and (
                len(row[index].encode("utf-8")) > MAX_MODEL_VALUE_BYTES or WKT_VALUE.match(row[index])
            ) for row in rows
        )
    }
    named_rows = []
    truncated = {}
    for row_id, row in enumerate(rows[:ROWS_FOR_REVIEW], start=1):
        named = {name: value for name, value in zip(report.result.columns, row, strict=True) if name not in omitted}
        cut = [name for name, value in named.items() if isinstance(value, str) and len(value) > CELL_CHARACTERS]
        if cut:
            truncated[row_id] = cut
        named_rows.append({name: _cut(value) for name, value in named.items()})
    meanings, labels = project_display_labels(brief, report.analysis.columns, report.language)
    return ReviewerPrompt(
        question=report.question, original_question=brief.raw_question if brief else None,
        caveats=list(brief.caveats) if brief else [],
        language=report.language, clarifications=list(clarifications),
        chart=design.chart, spec=design.spec,
        columns=[ReviewColumn(name=c.name, meaning=c.meaning, kind=c.kind, unit=c.unit)
                 for c in report.analysis.columns if c.name not in omitted],
        rows=named_rows, row_ids=list(range(1, len(named_rows) + 1)), row_count=report.result.row_count,
        rows_are_partial=report.result.row_count > len(named_rows), truncated_cells=truncated,
        omitted_columns=[name for name in report.result.columns if name in omitted],
        compromises=[c.message for c in (compromises or design.compromises)], warnings=list(warnings), round=round_,
        code_meanings={name: mapping for name, mapping in meanings.items() if name not in omitted},
        display_labels=labels.model_copy(update={
            "column_labels": {name: label for name, label in labels.column_labels.items() if name not in omitted},
            "value_labels": {name: mapping for name, mapping in labels.value_labels.items() if name not in omitted},
        }),
    )


async def review_chart(
    report: AnalysisReport, design: Design, png: Path, reviewer: Agent[ReviewerDeps, Review], *,
    brief: DataBrief | None = None, compromises: list[Compromise] | tuple = (), warnings: list[str] | tuple = (),
    round_: int = 1, usage: RunUsage | None = None, usage_limits: UsageLimits | None = None, clarifications: list[QuestionAnswer] | tuple = (),
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
        prompt.image_id = hashlib.sha256(picture.data).hexdigest()
        async with asyncio.timeout(REVIEW_TIMEOUT_SECONDS):
            result = await reviewer.run([prompt.model_dump_json(), picture], deps=deps, usage=run_usage,
                                        usage_limits=replace(usage_limits or UsageLimits(), request_limit=min(
                                            starting + MAX_REQUESTS, usage_limits.request_limit
                                            if usage_limits and usage_limits.request_limit is not None else starting + MAX_REQUESTS)))
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
