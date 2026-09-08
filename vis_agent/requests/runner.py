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
from vis_agent.analyst.models import AnalysisReport, Clarification, PreviousAnalysis
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import design_chart, render_design, render_id
from vis_agent.designer.models import DesignReport, PreviousDesign
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


def outcome_for(deps: AppDeps, request: Request, warnings: list[str] | None = None) -> RequestOutcome:
    pending = request.pending()
    artifact = None
    if request.artifact_id:
        artifact = LeadArtifact.from_artifact(requests_of(deps).get_artifact(request.artifact_id))
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
    request = store.get_request(request_id)
    pending = request.pending()
    if pending is None:
        raise ValueError("This request is not waiting for an answer.")
    if not answer or not answer.strip():
        raise ValueError("The answer is empty.")
    pending.answer, pending.answered_at, pending.answered_by = answer.strip(), now(), answered_by
    request.status = "running"
    store.save_request(request)
    return await run_request(deps, request_id, usage=usage)


async def run_request(deps: AppDeps, request_id: str, usage: RunUsage | None = None) -> RequestOutcome:
    """Run every step that has no saved output, in order. Safe to call again after a pause, a failure, or a kill."""
    store = requests_of(deps)
    request = store.get_request(request_id)
    if request.status == "done":
        return outcome_for(deps, request)
    if request.status == "waiting":
        return outcome_for(deps, request, ["The request is waiting for an answer; resume it with the answer."])
    if request_id in _running:
        return outcome_for(deps, request, ["The request is still running."])
    _running.add(request_id)
    try:
        request.status, request.error = "running", None
        store.save_request(request)
        budget = REQUEST_LIMIT if usage is None else None
        run_usage = usage if usage is not None else RunUsage()
        while (step := request.next_step()) is not None:
            try:
                output = await STEP_FUNCTIONS[step](deps, request, run_usage, budget)
            except Pause as pause:
                return _pause(deps, request, pause)
            except (DatasetNotFound, Failure, ValueError) as exc:
                return _fail(deps, request, str(exc))
            except duckdb.Error as exc:
                log.warning("DuckDB failed in step %s of %s: %s", step, request_id, exc)
                return _fail(deps, request, "DuckDB could not run this step.")
            except Exception as exc:
                log.exception("Step %s of %s died", step, request_id)
                _fail(deps, request, f"The {step} step died: {exc}")
                raise
            request.steps[step] = output
            store.save_request(request)
        request.status = "done"
        store.save_request(request)
        return outcome_for(deps, request)
    finally:
        _running.discard(request_id)


def _pause(deps: AppDeps, request: Request, pause: Pause) -> RequestOutcome:
    store = requests_of(deps)
    if len(request.clarifications) >= MAX_QUESTIONS:
        request.status = "failed"
        request.error = f"The request already asked {MAX_QUESTIONS} questions; the next was: {pause.clarification.question}"
        store.save_request(request)
        return outcome_for(deps, request)
    moment = now()
    request.clarifications.append(Exchange(
        step=pause.step, question=pause.clarification.question, reason=pause.clarification.reason,
        asked_at=moment, deadline=moment + timedelta(seconds=request.deadline_seconds),
    ))
    request.status = "waiting"
    store.save_request(request)
    return outcome_for(deps, request)


def _fail(deps: AppDeps, request: Request, error: str) -> RequestOutcome:
    request.status, request.error = "failed", error
    requests_of(deps).save_request(request)
    return outcome_for(deps, request)


def _check_budget(usage: RunUsage, budget: int | None) -> None:
    if budget is not None and usage.requests >= budget:
        raise Failure(f"The request used its budget of {budget} model requests.")


def pairs(request: Request) -> list[QuestionAnswer]:
    return [QuestionAnswer(question=e.question, answer=e.answer) for e in request.clarifications if e.answer]


def single_number(report: AnalysisReport) -> bool:
    return (report.result is not None and report.result.row_count == 1 and report.analysis is not None
            and len(report.analysis.columns) == 1 and report.analysis.columns[0].kind in ("measure", "share"))


async def understand(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    dataset = await asyncio.to_thread(deps.store.get_upload, request.dataset_id)
    output: dict[str, Any] = {"question": request.question}
    if request.type == "revise":
        parent = requests_of(deps).get_artifact(request.parent_artifact_id)
        output.update(root_question=parent.question, parent_version=parent.version, change=request.question)
    request.language = detect_language(output.get("root_question", request.question), dataset.brief, dataset.headers)
    output["language"] = request.language
    return output


async def profile(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    profiled = await profile_dataset(deps.store, deps.profiler, request.dataset_id, usage=usage)
    return {"status": profiled.status, "created_at": profiled.created_at.isoformat(),
            "brief_fingerprint": profiled.brief_fingerprint}


async def analyze(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    store = requests_of(deps)
    parent = store.get_artifact(request.parent_artifact_id) if request.parent_artifact_id else None
    if parent is not None and not request.redo_analysis:
        return parent.report.model_dump(mode="json")
    question, previous = request.question, None
    if parent is not None:
        if parent.report.analysis is None:
            raise Failure("The artifact being revised has no analysis to change.")
        question = parent.question
        previous = PreviousAnalysis(sql=parent.report.analysis.sql, columns=parent.report.analysis.columns,
                                    change=request.question)
    _check_budget(usage, budget)
    report = await analyze_dataset(deps.store, deps.profiler, deps.analyst, request.dataset_id, question,
                                   usage=usage, clarifications=pairs(request), previous=previous)
    if report.clarification is not None:
        raise Pause("analyze", report.clarification)
    if report.analysis is None or report.result is None:
        raise Failure("The analyst could not answer: " + ("; ".join(report.warnings) or "no result"))
    return report.model_dump(mode="json")


async def design(deps: AppDeps, request: Request, usage: RunUsage, budget: int | None) -> dict[str, Any]:
    report = AnalysisReport.model_validate(request.steps["analyze"])
    if single_number(report):
        return {"skipped": "The answer is a single number; it needs no chart."}
    previous = None
    if request.parent_artifact_id:
        parent = requests_of(deps).get_artifact(request.parent_artifact_id)
        if parent.design is not None:
            previous = PreviousDesign(spec=parent.design.spec, change=request.question)
    brief = (await asyncio.to_thread(deps.store.get_upload, request.dataset_id)).brief
    _check_budget(usage, budget)
    designed = await design_chart(report, deps.designer, brief, usage=usage, clarifications=pairs(request),
                                  previous=previous)
    if designed.clarification is not None:
        raise Pause("design", designed.clarification)
    if designed.design is None:
        return {"skipped": "The designer could not finish: " + ("; ".join(designed.warnings) or "no design"),
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
    existing = store.artifact_for_request(request.request_id)
    if existing is not None:
        request.artifact_id = existing.artifact_id
        return {"artifact_id": existing.artifact_id}
    report = AnalysisReport.model_validate(request.steps["analyze"])
    design_step, render_step, profile_step = request.steps["design"], request.steps["render"], request.steps["profile"]
    designed = DesignReport.model_validate(design_step) if "skipped" not in design_step else None
    parent = store.get_artifact(request.parent_artifact_id) if request.parent_artifact_id else None
    catalogue_version, rules_version = versions()
    artifact = Artifact(
        artifact_id=store.new_artifact_id(), request_id=request.request_id, dataset_id=request.dataset_id,
        version=parent.version + 1 if parent else 1, parent_artifact_id=parent.artifact_id if parent else None,
        question=parent.question if parent else request.question, change=request.question if parent else None,
        report=report, design=designed.design if designed else None,
        no_chart_reason=design_step.get("skipped") or render_step.get("skipped"),
        render_id=render_step.get("render_id"), png_url=render_step.get("png_url"), html_url=render_step.get("html_url"),
        review=request.steps["review"], clarifications=list(request.clarifications),
        lineage=Lineage(profile_created_at=profile_step.get("created_at"),
                        brief_fingerprint=profile_step.get("brief_fingerprint"),
                        catalogue_version=catalogue_version, rules_version=rules_version,
                        analyst_model=report.model, designer_model=designed.model if designed else None),
        created_at=now(),
    )
    store.save_artifact(artifact)
    request.artifact_id = artifact.artifact_id
    return {"artifact_id": artifact.artifact_id}


STEP_FUNCTIONS = {"understand": understand, "profile": profile, "analyze": analyze, "design": design,
                  "render": render, "review": review, "deliver": deliver}
