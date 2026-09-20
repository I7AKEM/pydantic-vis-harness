"""Request persistence and the lead entry point. Specialists run only when the lead calls them."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from weakref import WeakValueDictionary

from pydantic_ai.usage import RunUsage, UsageLimits

from vis_agent.analyst.agent import detect_language
from vis_agent.analyst.models import AnalysisReport, Clarification
from vis_agent.card import card as build_card
from vis_agent.deps import AppDeps
from vis_agent.designer.models import Compromise, DesignReport
from vis_agent.models import QuestionAnswer
from vis_agent.requests.models import (
    DEFAULT_DEADLINE_SECONDS, Artifact, Caller, CallerKind, Exchange, LeadArtifact, Lineage,
    Request, RequestOutcome, RequestType,
)
from vis_agent.requests.store import RequestStore, now

log = logging.getLogger("requests")
REQUEST_LIMIT = 18
TOOL_LIMIT = 16
_running: set[str] = set()
_request_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


@asynccontextmanager
async def request_lock(request_id: str):
    """Serialize mutations of one saved request across concurrent lead runs in this process."""
    lock = _request_locks.setdefault(request_id, asyncio.Lock())
    async with lock:
        yield


def requests_of(deps: AppDeps) -> RequestStore:
    if deps.requests is None:
        raise RuntimeError("AppDeps.requests is not set.")
    return deps.requests


def create_request(deps: AppDeps, *, type: RequestType, dataset_id: str, question: str, caller: Caller,
                   parent_artifact_id: str | None = None, redo_analysis: bool = False,
                   deadline_seconds: int = DEFAULT_DEADLINE_SECONDS) -> Request:
    return requests_of(deps).new_request(type, dataset_id, question, caller, parent_artifact_id,
                                         redo_analysis, deadline_seconds)


def latest_unfinished(deps: AppDeps, conversation_id: str | None) -> Request | None:
    if not conversation_id:
        return None
    store = requests_of(deps)
    summaries = store.list_requests(conversation_id=conversation_id, unfinished_only=True, limit=1)
    return store.get_request(summaries[0].request_id) if summaries else None


def pairs(request: Request) -> list[QuestionAnswer]:
    return [QuestionAnswer(question=e.question, answer=e.answer) for e in request.clarifications if e.answer]


async def outcome_for(deps: AppDeps, request: Request, warnings: list[str] | None = None) -> RequestOutcome:
    pending = request.pending()
    artifact, shown = None, None
    if request.artifact_id:
        artifact = LeadArtifact.from_artifact(await asyncio.to_thread(requests_of(deps).get_artifact, request.artifact_id))
        shown = build_card(language=request.language or "English", png_url=artifact.png_url,
                           no_chart_reason=artifact.no_chart_reason, summary=artifact.summary,
                           explanation=artifact.explanation, columns=artifact.columns, rows=artifact.rows,
                           row_count=artifact.row_count, assumptions=artifact.assumptions,
                           compromises=artifact.compromises, warnings=[*artifact.warnings, *(warnings or [])],
                           review=artifact.review, artifact_id=artifact.artifact_id, request_id=artifact.request_id,
                           display_labels=artifact.display_labels)
    return RequestOutcome(request_id=request.request_id, status=request.status, artifact=artifact, card=shown,
                          clarification=Clarification(question=pending.question, reason=pending.reason) if pending else None,
                          overdue=pending.overdue(now()) if pending else False, error=request.error,
                          warnings=list(warnings or []))


async def prepare_request(deps: AppDeps, request: Request) -> dict:
    """Load the supplied table once. Resuming returns completed work, without selecting another action."""
    from vis_agent.analyst.source import SourceUnavailable, load_csv_report

    if "source_error" in request.steps:
        if request.status != "failed" or request.error != request.steps["source_error"]:
            request.status, request.error = "failed", request.steps["source_error"]
            await asyncio.to_thread(requests_of(deps).save_request, request)
        return {"request_id": request.request_id, "status": "failed", "terminal": True,
                "error": request.steps["source_error"],
                "next": "Explain this technical limitation honestly; another tool/model cannot change it."}

    source = await asyncio.to_thread(deps.store.get_upload, request.dataset_id)
    request.language = detect_language(request.question, source.brief, source.headers)
    parent = await asyncio.to_thread(requests_of(deps).get_artifact, request.parent_artifact_id) if request.parent_artifact_id else None
    if "analyze" not in request.steps:
        if parent is not None and not request.redo_analysis:
            report = parent.report.model_copy(update={"language": request.language})
        else:
            try:
                report = await asyncio.to_thread(load_csv_report, deps.store, request.dataset_id, request.question,
                                                 language=request.language)
            except SourceUnavailable as exc:
                request.status, request.error = "failed", str(exc)
                request.steps["source_error"] = str(exc)
                await asyncio.to_thread(requests_of(deps).save_request, request)
                return await prepare_request(deps, request)
        request.steps["analyze"] = report.model_dump(mode="json")
        await asyncio.to_thread(requests_of(deps).save_request, request)
    report = AnalysisReport.model_validate(request.steps["analyze"])
    from vis_agent.designer.agent import build_prompt
    context = build_prompt(report, source.brief).model_dump(mode="json")
    return {"request_id": request.request_id, "status": request.status, "dataset_id": request.dataset_id,
            "question": request.question, "brief": source.brief.model_dump(mode="json") if source.brief else None,
            "table": context, "completed": list(request.steps), "design": request.steps.get("design"),
            "render": request.steps.get("render"), "review": request.steps.get("review"),
            "specialist_feedback": request.steps.get("specialist_feedback"),
            "convergence": {"render_attempts": request.render_attempts,
                            "design_attempts": request.design_attempts,
                            "visual_repairs": request.visual_repair_attempts,
                            "routine_repairs_remaining": max(0, 1 - request.visual_repair_attempts)},
            "parent": parent.summary().model_dump(mode="json") if parent else None,
            "previous_spec": parent.design.spec if parent and parent.design else None,
            "answers": [p.model_dump() for p in pairs(request)],
            "artifact_id": request.artifact_id, "warnings": report.warnings}


def invalidate_chart(request: Request) -> None:
    for key in ("design", "render", "review", "specialist_feedback"):
        request.steps.pop(key, None)
    request.review_feedback = None


async def record_answer(deps: AppDeps, request_id: str, answer: str, answered_by: CallerKind) -> Request:
    async with request_lock(request_id):
        request = await asyncio.to_thread(requests_of(deps).get_request, request_id)
        pending = request.pending()
        if pending is None:
            raise ValueError("This request is not waiting for an answer.")
        if not answer.strip():
            raise ValueError("The answer is empty.")
        pending.answer, pending.answered_at, pending.answered_by = answer.strip(), now(), answered_by
        request.status, request.error = "running", None
        await asyncio.to_thread(requests_of(deps).save_request, request)
        return request


async def pause_request(deps: AppDeps, request: Request, question: str, reason: str) -> RequestOutcome:
    moment = now()
    request.clarifications.append(Exchange(step="understand", question=question, reason=reason, asked_at=moment,
                                           deadline=moment + timedelta(seconds=request.deadline_seconds)))
    request.status = "waiting"
    await asyncio.to_thread(requests_of(deps).save_request, request)
    return await outcome_for(deps, request)


async def publish(deps: AppDeps, request: Request, *, no_chart_reason: str | None = None,
                  lead_run_id: str | None = None) -> RequestOutcome:
    """Persist the lead's chosen preview or explicit source-table fallback; never schedule other work."""
    store = requests_of(deps)
    existing = await asyncio.to_thread(store.artifact_for_request, request.request_id)
    if existing:
        request.artifact_id, request.status = existing.artifact_id, "done"
        await asyncio.to_thread(store.save_request, request)
        return await outcome_for(deps, request)
    fallback = no_chart_reason is not None
    if fallback and not no_chart_reason.strip():
        raise ValueError("A table fallback needs an honest, nonempty reason why no chart was delivered.")
    if "analyze" not in request.steps:
        raise ValueError(request.error or "No safe source table is available to publish.")
    render = {} if fallback else request.steps.get("render", {})
    if not fallback and not render.get("png_url"):
        raise ValueError("There is no rendered chart to publish. Call render_visualization on a successful design first.")
    report = AnalysisReport.model_validate(request.steps["analyze"])
    designed = DesignReport.model_validate(request.steps["design"]) if request.steps.get("design") else None
    review = ({"status": "not_reviewed", "reason": "No chart was delivered."} if fallback else
              request.steps.get("review", {"status": "not_reviewed", "reason": "The lead did not request a visual review."}))
    report.warnings.extend([*(designed.warnings if designed else []), *review.get("warnings", [])])
    parent = await asyncio.to_thread(store.get_artifact, request.parent_artifact_id) if request.parent_artifact_id else None
    source = await asyncio.to_thread(deps.store.get_upload, request.dataset_id)
    designer_dir = Path(__file__).resolve().parent.parent / "designer"
    artifact = Artifact(
        artifact_id=store.new_artifact_id(), request_id=request.request_id, dataset_id=request.dataset_id,
        version=parent.version + 1 if parent else 1, parent_artifact_id=request.parent_artifact_id,
        question=parent.question if parent else request.question, change=request.question if parent else None,
        report=report, design=designed.design if designed and not fallback else None,
        no_chart_reason=no_chart_reason,
        compromises=[Compromise.model_validate(c) for c in render.get("rendered", {}).get("compromises", [])],
        render_id=render.get("render_id"), png_url=render.get("png_url"), html_url=render.get("html_url"),
        review={**review, "rounds": [r.review for r in request.rounds]}, clarifications=list(request.clarifications),
        lineage=Lineage(brief_fingerprint=source.brief.fingerprint() if source.brief else None,
                        catalogue_version=sha256((designer_dir / "catalogue.json").read_bytes()).hexdigest()[:12],
                        rules_version="expert-led-v1", analyst_model=report.model, designer_model=designed.model if designed else None,
                        reviewer_model=review.get("model")), created_at=now(),
    )
    await asyncio.to_thread(store.save_artifact, artifact)
    if lead_run_id is not None:
        # Publication completes this turn's work. A later user turn may revise it, but this same lead
        # run must not use a fresh revision to reset a spent repair budget. Idempotent re-publication
        # above deliberately retains the original run ID rather than claiming an older artifact.
        request.steps["publication_run_id"] = lead_run_id
    request.artifact_id, request.status, request.error = artifact.artifact_id, "done", None
    await asyncio.to_thread(store.save_request, request)
    return await outcome_for(deps, request)


async def run_request(deps: AppDeps, request_id: str, usage: RunUsage | None = None) -> RequestOutcome:
    """API/CLI adapter: ask the same lead to finish a saved request. No prescribed specialist sequence."""
    store = requests_of(deps)
    request = await asyncio.to_thread(store.get_request, request_id)
    if request.status in ("done", "waiting"):
        return await outcome_for(deps, request)
    if "source_error" in request.steps:
        await prepare_request(deps, request)
        return await outcome_for(deps, request)
    if request_id in _running:
        return await outcome_for(deps, request, ["The request is still running."])
    if deps.lead is None:
        raise RuntimeError("Wire AppDeps.lead to the team's lead agent.")
    _running.add(request_id)
    usage = usage if usage is not None else RunUsage()
    starting = usage.requests
    failure: str | None = None
    cancelled = False
    try:
        async with request_lock(request_id):
            request = await asyncio.to_thread(store.get_request, request_id)
            if request.status in ("done", "waiting"):
                return await outcome_for(deps, request)
            if "source_error" in request.steps:
                await prepare_request(deps, request)
                return await outcome_for(deps, request)
            remaining = max(0, REQUEST_LIMIT - request.requests_used)
            request.status, request.error = "running", None
            await asyncio.to_thread(store.save_request, request)
        if not remaining:
            raise ValueError(f"The request used its budget of {REQUEST_LIMIT} model requests.")
        await deps.lead.run(
            f"Finish existing visualization request {request_id}. Call resume to inspect saved work, then direct "
            "the specialists as needed and publish_visualization when ready. Reuse successful saved work.",
            deps=replace(deps, caller_kind=request.caller.kind, caller_identity=request.caller.identity),
            conversation_id=request.caller.conversation_id, usage=usage,
            usage_limits=UsageLimits(request_limit=starting + remaining, tool_calls_limit=usage.tool_calls + TOOL_LIMIT),
        )
        request = await asyncio.to_thread(store.get_request, request_id)
        if request.status == "running":
            failure = "The lead ended before publishing the chart. Resume to continue from saved work."
    except asyncio.CancelledError:
        cancelled = True
        failure = "The lead was interrupted. Resume to continue from saved work."
        raise
    except Exception as exc:
        failure = str(exc) or type(exc).__name__
        log.warning("Lead could not finish %s: %s", request_id, exc)
    finally:
        try:
            # Tools save their own Request instances. Always reload, including on cancellation,
            # so accounting cannot overwrite a completed design or render with our initial copy.
            async with request_lock(request_id):
                request = await asyncio.to_thread(store.get_request, request_id)
                if failure and request.status not in ("done", "waiting"):
                    request.status, request.error = "failed", failure
                request.requests_used += usage.requests - starting
                await asyncio.to_thread(store.save_request, request)
        except Exception:
            if not cancelled:
                raise
            log.exception("Could not persist interruption of %s", request_id)
        finally:
            _running.discard(request_id)
    return await outcome_for(deps, request)


async def answer_request(deps: AppDeps, request_id: str, answer: str, answered_by: CallerKind,
                         usage: RunUsage | None = None) -> RequestOutcome:
    await record_answer(deps, request_id, answer, answered_by)
    return await run_request(deps, request_id, usage=usage)
