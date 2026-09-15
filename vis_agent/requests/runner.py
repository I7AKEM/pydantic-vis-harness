"""The request runner: fixed steps, a checkpoint after each, resume from the first step without one."""

import asyncio
import logging
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb
from pydantic_ai.usage import RunUsage

from vis_agent.analyst.agent import analyze_dataset, detect_language
from vis_agent.analyst.models import AnalysisReport, AnalysisRevision, Clarification, PreviousAnalysis, RevisionRound
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import design_chart, render_design, render_id
from vis_agent.designer.models import Compromise, DesignReport, PreviousDesign
from vis_agent.models import QuestionAnswer
from vis_agent.profiler.agent import profile_dataset
from vis_agent.render.base import RenderFailed, RendererUnavailable
from vis_agent.requests.models import (
    DEFAULT_DEADLINE_SECONDS, MAX_QUESTIONS, Artifact, Caller, CallerKind, Exchange, LeadArtifact, Lineage,
    Request, RequestOutcome, RequestType, StepName,
)
from vis_agent.requests.store import RequestStore, now
from vis_agent.store import DatasetNotFound

log = logging.getLogger("requests")
REQUEST_LIMIT = 40
NOT_REVIEWED = {"status": "not_reviewed", "reason": "Phase 5 adds the reviewer."}
DESIGNER_DIR = Path(__file__).resolve().parent.parent / "designer"
_running: set[str] = set()


class Pause(Exception):
    """A step asked a question; the request waits for the answer."""

    def __init__(self, step: StepName, clarification: Clarification):
        super().__init__(clarification.question)
        self.step, self.clarification = step, clarification


class Failure(Exception):
    """A step failed in a way that running it again will not fix."""


def requests_of(deps: AppDeps) -> RequestStore:
    if deps.requests is None:
        raise RuntimeError("AppDeps.requests is not set; wire a RequestStore in app.py.")
    return deps.requests


def create_request(deps: AppDeps, *, type: RequestType, dataset_id: str, question: str, caller: Caller,
                   parent_artifact_id: str | None = None, redo_analysis: bool = False,
                   deadline_seconds: int = DEFAULT_DEADLINE_SECONDS) -> Request:
    return requests_of(deps).new_request(type, dataset_id, question, caller, parent_artifact_id, redo_analysis,
                                         deadline_seconds)


def versions() -> tuple[str, str]:
    """The catalogue and rules versions: a hash of each file's content."""

    def digest(name: str) -> str:
        return sha256((DESIGNER_DIR / name).read_bytes()).hexdigest()[:12]

    return digest("catalogue.json"), digest("rules.py")


async def outcome_for(deps: AppDeps, request: Request, warnings: list[str] | None = None) -> RequestOutcome:
    pending = request.pending()
    artifact = None
    if request.artifact_id:
        artifact = LeadArtifact.from_artifact(await asyncio.to_thread(requests_of(deps).get_artifact, request.artifact_id))
    return RequestOutcome(
        request_id=request.request_id, status=request.status, artifact=artifact,
        clarification=Clarification(question=pending.question, reason=pending.reason) if pending else None,
        overdue=pending.overdue(now()) if pending else False, error=request.error, warnings=list(warnings or []),
    )


def latest_unfinished(deps: AppDeps, conversation_id: str | None) -> Request | None:
    """The newest unfinished request of a conversation; nothing without a conversation, so callers never cross them."""
    if not conversation_id:
        return None
    store = requests_of(deps)
    for summary in store.list_requests(conversation_id=conversation_id, unfinished_only=True, limit=1):
        return store.get_request(summary.request_id)
    return None


async def answer_request(deps: AppDeps, request_id: str, answer: str, answered_by: CallerKind,
                         usage: RunUsage | None = None) -> RequestOutcome:
    """Record the answer to the pending question, then continue the request."""
    store = requests_of(deps)
    request = await asyncio.to_thread(store.get_request, request_id)
    pending = request.pending()
    if pending is None:
        raise ValueError("This request is not waiting for an answer.")
    if not answer or not answer.strip():
        raise ValueError("The answer is empty.")
    pending.answer, pending.answered_at, pending.answered_by = answer.strip(), now(), answered_by
    request.status = "running"
    await asyncio.to_thread(store.save_request, request)
    return await run_request(deps, request_id, usage=usage)


async def run_request(deps: AppDeps, request_id: str, usage: RunUsage | None = None) -> RequestOutcome:
    """Run every step that has no saved output, in order. Safe to call again after a pause, a failure, or a kill."""
    store = requests_of(deps)
    request = await asyncio.to_thread(store.get_request, request_id)
    if request.status == "done":
        return await outcome_for(deps, request)
    if request.status == "waiting":
        return await outcome_for(deps, request, ["The request is waiting for an answer; resume it with the answer."])
    if request_id in _running:
        return await outcome_for(deps, request, ["The request is still running."])
    _running.add(request_id)
    try:
        request.status, request.error = "running", None
        await asyncio.to_thread(store.save_request, request)
        budget = REQUEST_LIMIT if usage is None else None
        run_usage = usage if usage is not None else RunUsage()
        # The model requests this invocation spends are added to the request's own count after every step,
        # so the budget of a standalone run holds across pauses, failures, and resumes.
        used_before, requests_at_start = request.requests_used, run_usage.requests
        while (step := request.next_step()) is not None:
            try:
                output = await STEP_FUNCTIONS[step](deps, request, run_usage, budget)
            except Pause as pause:
                _count_requests(request, run_usage, used_before, requests_at_start)
                return await _pause(deps, request, pause)
            except (DatasetNotFound, Failure, ValueError) as exc:
                _count_requests(request, run_usage, used_before, requests_at_start)
                return await _fail(deps, request, str(exc))
            except duckdb.Error as exc:
                log.warning("DuckDB failed in step %s of %s: %s", step, request_id, exc)
                _count_requests(request, run_usage, used_before, requests_at_start)
                return await _fail(deps, request, "DuckDB could not run this step.")
            except Exception as exc:
                log.exception("Step %s of %s died", step, request_id)
                _count_requests(request, run_usage, used_before, requests_at_start)
                await _fail(deps, request, f"The {step} step died: {exc}")
                raise
            request.steps[step] = output
            _count_requests(request, run_usage, used_before, requests_at_start)
            await asyncio.to_thread(store.save_request, request)
        request.status = "done"
        await asyncio.to_thread(store.save_request, request)
        return await outcome_for(deps, request)
    finally:
        _running.discard(request_id)


def _count_requests(request: Request, usage: RunUsage, used_before: int, requests_at_start: int) -> None:
    request.requests_used = used_before + (usage.requests - requests_at_start)


async def _pause(deps: AppDeps, request: Request, pause: Pause) -> RequestOutcome:
    store = requests_of(deps)
    if len(request.clarifications) >= MAX_QUESTIONS:
        request.status = "failed"
        request.error = f"The request already asked {MAX_QUESTIONS} questions; the next was: {pause.clarification.question}"
        await asyncio.to_thread(store.save_request, request)
        return await outcome_for(deps, request)
    moment = now()
    request.clarifications.append(Exchange(
        step=pause.step, question=pause.clarification.question, reason=pause.clarification.reason,
        asked_at=moment, deadline=moment + timedelta(seconds=request.deadline_seconds),
    ))
    request.status = "waiting"
    await asyncio.to_thread(store.save_request, request)
    return await outcome_for(deps, request)


async def _fail(deps: AppDeps, request: Request, error: str) -> RequestOutcome:
    request.status, request.error = "failed", error
    await asyncio.to_thread(requests_of(deps).save_request, request)
    return await outcome_for(deps, request)


def _check_budget(request: Request, budget: int | None) -> None:
    """A standalone run's cap covers the whole request: what earlier invocations spent counts too."""
    if budget is not None and request.requests_used >= budget:
        raise Failure(f"The request used its budget of {budget} model requests.")


def pairs(request: Request) -> list[QuestionAnswer]:
    return [QuestionAnswer(question=e.question, answer=e.answer) for e in request.clarifications if e.answer]


async def understand(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    dataset = await asyncio.to_thread(deps.store.get_upload, request.dataset_id)
    output: dict[str, Any] = {"question": request.question}
    if request.type == "revise":
        parent = await asyncio.to_thread(requests_of(deps).get_artifact, request.parent_artifact_id)
        output.update(root_question=parent.question, parent_version=parent.version, change=request.question)
    # The language of the caller's latest words: the change, for a revision, so the reply follows the caller.
    request.language = detect_language(request.question, dataset.brief, dataset.headers)
    output["language"] = request.language
    return output


async def profile(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    profiled = await profile_dataset(deps.store, deps.profiler, request.dataset_id, usage=usage)
    return {"status": profiled.status, "created_at": profiled.created_at.isoformat(),
            "brief_fingerprint": profiled.brief_fingerprint}


async def analyze(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    store = requests_of(deps)
    parent = await asyncio.to_thread(store.get_artifact, request.parent_artifact_id) if request.parent_artifact_id else None
    if parent is not None and not request.redo_analysis:
        copied = parent.report.model_copy(update={"language": request.language or parent.report.language})
        return copied.model_dump(mode="json")
    question, previous = request.question, None
    if parent is not None:
        if parent.report.analysis is None:
            raise Failure("The artifact being revised has no analysis to change.")
        question = parent.question
        previous = PreviousAnalysis(sql=parent.report.analysis.sql, columns=parent.report.analysis.columns,
                                    change=request.question)
    _check_budget(request, budget)
    report = await analyze_dataset(deps.store, deps.profiler, deps.analyst, request.dataset_id, question,
                                   usage=usage, clarifications=pairs(request), previous=previous,
                                   language=request.language)
    if report.clarification is not None:
        raise Pause("analyze", report.clarification)
    if report.analysis is None or report.result is None:
        raise Failure("; ".join(report.warnings) or "The analyst returned no result")
    return report.model_dump(mode="json")


async def revise_analysis(deps: AppDeps, request: Request, report: AnalysisReport, revision: AnalysisRevision,
                          usage: RunUsage, budget: int | None) -> tuple[AnalysisReport, RevisionRound, str]:
    """One revised analysis for the designer's request. The decision is saved first, so a crash after it never revises again."""
    store = requests_of(deps)
    request.revision = revision
    await asyncio.to_thread(store.save_request, request)
    log.info("The designer asked the analyst to revise the table of %s: %s", request.request_id, revision.problem)
    _check_budget(request, budget)
    feedback = PreviousAnalysis(sql=report.analysis.sql, columns=report.analysis.columns,
                                change=revision.requested_change, feedback=revision)
    revised = await analyze_dataset(deps.store, deps.profiler, deps.analyst, request.dataset_id, report.question,
                                    usage=usage, clarifications=pairs(request), previous=feedback,
                                    language=request.language)
    if revised.analysis is not None and revised.result is not None:
        request.steps["analyze_before_revision"] = request.steps["analyze"]
        request.steps["analyze"] = revised.model_dump(mode="json")
        await asyncio.to_thread(store.save_request, request)
        reply = " ".join([revised.analysis.summary, *revised.analysis.assumptions])
        note = f"The designer asked the analyst to revise the table ({revision.problem}); the chart comes from the revised table."
        return revised, RevisionRound(request=revision, reply=reply), note
    reason = revised.clarification.question if revised.clarification else "; ".join(revised.warnings) or "no result"
    reply = f"The analyst did not revise the table: {reason}"
    return report, RevisionRound(request=revision, reply=reply), \
        f"The designer asked the analyst to revise the table ({revision.problem}) and the analyst could not: {reason}"


async def run_designer(deps: AppDeps, request: Request, designer, brief, previous, usage: RunUsage,
                       budget: int | None, round_: RevisionRound | None = None) -> tuple[DesignReport, RevisionRound | None]:
    """One designer run on the request's current table; when it asks for a revision and none was made yet, one more
    run on the revised table. Returns the report and the revision round, so the fallback designer can see it too.
    A further request is refused as a failure the fallback or the table answers."""
    report = AnalysisReport.model_validate(request.steps["analyze"])
    _check_budget(request, budget)
    designed = await design_chart(report, designer, brief, usage=usage, clarifications=pairs(request),
                                  previous=previous, revision=round_)
    if designed.revision is not None and request.revision is None:
        report, round_, note = await revise_analysis(deps, request, report, designed.revision, usage, budget)
        _check_budget(request, budget)
        designed = await design_chart(report, designer, brief, usage=usage, clarifications=pairs(request),
                                      previous=previous, revision=round_)
        designed.warnings.insert(0, note)
    if designed.revision is not None:
        designed.warnings.append("The designer asked for a second table revision, which is not allowed: "
                                 f"{designed.revision.problem}")
        designed.revision = None
    return designed, round_


async def design(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    report = AnalysisReport.model_validate(request.steps["analyze"])
    previous = None
    if request.parent_artifact_id:
        parent = await asyncio.to_thread(requests_of(deps).get_artifact, request.parent_artifact_id)
        previous = PreviousDesign(spec=parent.design.spec if parent.design is not None else None,
                                  change=request.question)
    brief = (await asyncio.to_thread(deps.store.get_upload, request.dataset_id)).brief
    designed, round_ = await run_designer(deps, request, deps.designer, brief, previous, usage, budget)
    if designed.design is None and designed.clarification is None and deps.designer_fallback is not None:
        first = "; ".join(designed.warnings) or "no design"
        log.warning("The designer failed on %s (%s); running the design step once more on the fallback model",
                    request.request_id, first)
        designed, _ = await run_designer(deps, request, deps.designer_fallback, brief, previous, usage, budget, round_)
        designed.warnings.insert(0, f"The first designer run failed ({first}); this chart comes from the fallback model.")
    if designed.clarification is not None:
        raise Pause("design", designed.clarification)
    if designed.design is None:
        return {"skipped": "; ".join(designed.warnings) or "The designer returned no design",
                "warnings": designed.warnings}
    return designed.model_dump(mode="json")


async def render(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    step = request.steps["design"]
    if "skipped" in step:
        return {"skipped": step["skipped"]}
    report = AnalysisReport.model_validate(request.steps["analyze"])
    designed = DesignReport.model_validate(step)
    identifier = render_id(designed.design.spec, report)
    try:
        rendered = await asyncio.to_thread(render_design, report, designed.design,
                                           deps.store.directory / "renders" / identifier)
    except (RendererUnavailable, RenderFailed, ValueError) as exc:
        return {"skipped": f"The chart could not be rendered: {exc}"}
    return {"render_id": identifier, "png_url": f"/renders/{identifier}/chart.png",
            "html_url": f"/renders/{identifier}/chart.html", "rendered": rendered.model_dump(mode="json")}


async def review(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    return dict(NOT_REVIEWED)


async def deliver(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    store = requests_of(deps)
    existing = await asyncio.to_thread(store.artifact_for_request, request.request_id)
    if existing is not None:
        request.artifact_id = existing.artifact_id
        return {"artifact_id": existing.artifact_id}
    report = AnalysisReport.model_validate(request.steps["analyze"])
    design_step, render_step, profile_step = request.steps["design"], request.steps["render"], request.steps["profile"]
    if "skipped" not in design_step:
        report.warnings.extend(design_step.get("warnings", []))
    designed = DesignReport.model_validate(design_step) if "skipped" not in design_step else None
    parent = await asyncio.to_thread(store.get_artifact, request.parent_artifact_id) if request.parent_artifact_id else None
    catalogue_version, rules_version = versions()
    # The renderer's list holds the check's compromises plus its own (dropped rows, a still picture).
    if "rendered" in render_step:
        compromises = [Compromise.model_validate(c) for c in render_step["rendered"].get("compromises", [])]
    else:
        compromises = list(designed.design.compromises) if designed else []
    artifact = Artifact(
        artifact_id=store.new_artifact_id(), request_id=request.request_id, dataset_id=request.dataset_id,
        version=parent.version + 1 if parent else 1, parent_artifact_id=parent.artifact_id if parent else None,
        question=parent.question if parent else request.question, change=request.question if parent else None,
        report=report, design=designed.design if designed else None, compromises=compromises,
        no_chart_reason=design_step.get("skipped") or render_step.get("skipped"),
        render_id=render_step.get("render_id"), png_url=render_step.get("png_url"), html_url=render_step.get("html_url"),
        review=request.steps["review"], clarifications=list(request.clarifications),
        lineage=Lineage(profile_created_at=profile_step.get("created_at"),
                        brief_fingerprint=profile_step.get("brief_fingerprint"),
                        catalogue_version=catalogue_version, rules_version=rules_version,
                        analyst_model=report.model, designer_model=designed.model if designed else None),
        created_at=now(),
    )
    await asyncio.to_thread(store.save_artifact, artifact)
    request.artifact_id = artifact.artifact_id
    return {"artifact_id": artifact.artifact_id}


STEP_FUNCTIONS = {"understand": understand, "profile": profile, "analyze": analyze, "design": design,
                  "render": render, "review": review, "deliver": deliver}
