"""The agent channel: JSON routes for requests, answers, artifacts, and inbound questions, with one callback."""

import asyncio
import logging
from dataclasses import replace

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request as HttpRequest
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from vis_agent.deps import AppDeps
from vis_agent.requests.models import DEFAULT_DEADLINE_SECONDS, Caller, RequestType
from vis_agent.requests.runner import REQUEST_LIMIT, answer_request, create_request, requests_of, run_request
from vis_agent.requests.store import ArtifactNotFound, RequestNotFound, now
from vis_agent.store import DatasetNotFound

JSON_MEDIA_TYPE = "application/json"
CALLBACK_TIMEOUT_SECONDS = 10
log = logging.getLogger("requests")


class CallerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: str
    return_address: str | None = None


class CreateRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: RequestType = "new"
    dataset_id: str
    question: str
    parent_artifact_id: str | None = None
    redo_analysis: bool = False
    caller: CallerInput
    deadline_seconds: int = Field(default=DEFAULT_DEADLINE_SECONDS, gt=0, le=30 * 24 * 60 * 60)


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


class AskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    dataset_id: str | None = None
    caller: CallerInput


def error(message: str, status: int) -> Response:
    return JSONResponse({"error": message}, status_code=status)


def require_json(request: HttpRequest) -> None:
    """The control the built-in chat endpoint uses: a JSON content type forces a browser preflight, so a page
    the user happens to visit cannot start, answer, or resume a request, or ask one. Raises TypeError otherwise."""
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != JSON_MEDIA_TYPE:
        raise TypeError(f"Expected Content-Type: {JSON_MEDIA_TYPE}, got {media_type or 'no content type'}")


async def read_json(request: HttpRequest, model):
    """Parse a JSON body into a model. Raises ValueError for a bad body; the content type is checked first."""
    require_json(request)
    try:
        return model.model_validate_json(await request.body())
    except ValidationError as exc:
        raise ValueError(exc.errors()[0]["msg"]) from exc


def add_request_routes(app: Starlette, deps: AppDeps, lead: Agent, http: httpx.AsyncClient | None = None) -> None:
    client = http or httpx.AsyncClient(timeout=CALLBACK_TIMEOUT_SECONDS)

    async def notify(request_id: str) -> None:
        """Post the request record to the caller's return address once. Any failure is logged, never retried,
        and never leaves the background task."""
        try:
            record = await asyncio.to_thread(requests_of(deps).get_request, request_id)
            if not record.caller.return_address:
                return
            response = await client.post(record.caller.return_address, json=shown(record),
                                         timeout=CALLBACK_TIMEOUT_SECONDS)
            response.raise_for_status()
        except Exception as exc:
            log.warning("The callback for %s failed: %s", request_id, exc)

    async def run_then_notify(request_id: str, answer: str | None = None) -> None:
        try:
            if answer is not None:
                await answer_request(deps, request_id, answer, "agent")
            else:
                await run_request(deps, request_id)
        except Exception:
            log.exception("Request %s died on the channel", request_id)
        await notify(request_id)

    def shown(record) -> dict:
        pending = record.pending()

        return {**record.model_dump(mode="json"),
                "pending_question": pending.question if pending else None,
                "overdue": pending.overdue(now()) if pending else False}

    async def post_requests(request: HttpRequest) -> Response:
        try:
            data = await read_json(request, CreateRequestInput)
            caller = Caller(kind="agent", identity=data.caller.identity, return_address=data.caller.return_address)
            record = create_request(deps, type=data.type, dataset_id=data.dataset_id, question=data.question,
                                    caller=caller, parent_artifact_id=data.parent_artifact_id,
                                    redo_analysis=data.redo_analysis, deadline_seconds=data.deadline_seconds)
        except TypeError as exc:
            return error(str(exc), 415)
        except (DatasetNotFound, ArtifactNotFound) as exc:
            return error(str(exc), 404)
        except (ValueError, ValidationError) as exc:
            return error(str(exc), 400)
        return JSONResponse({"request_id": record.request_id, "status": record.status}, status_code=202,
                            background=BackgroundTask(run_then_notify, record.request_id))

    async def get_request(request: HttpRequest) -> Response:
        try:
            record = await asyncio.to_thread(requests_of(deps).get_request, request.path_params["request_id"])
        except RequestNotFound as exc:
            return error(str(exc), 404)
        except ValueError as exc:
            return error(str(exc), 400)
        return JSONResponse(shown(record))

    async def post_answer(request: HttpRequest) -> Response:
        request_id = request.path_params["request_id"]
        try:
            data = await read_json(request, AnswerInput)
            record = await asyncio.to_thread(requests_of(deps).get_request, request_id)
        except TypeError as exc:
            return error(str(exc), 415)
        except RequestNotFound as exc:
            return error(str(exc), 404)
        except ValueError as exc:
            return error(str(exc), 400)
        if record.pending() is None:
            return error("This request is not waiting for an answer.", 409)
        if not data.answer.strip():
            return error("The answer is empty.", 400)
        return JSONResponse({"request_id": request_id, "status": "running"}, status_code=202,
                            background=BackgroundTask(run_then_notify, request_id, data.answer))

    async def post_resume(request: HttpRequest) -> Response:
        request_id = request.path_params["request_id"]
        try:
            require_json(request)
            record = await asyncio.to_thread(requests_of(deps).get_request, request_id)
        except TypeError as exc:
            return error(str(exc), 415)
        except RequestNotFound as exc:
            return error(str(exc), 404)
        except ValueError as exc:
            return error(str(exc), 400)
        if record.status == "done":
            return JSONResponse(shown(record))
        if record.status == "waiting":
            return error("This request is waiting for an answer; post the answer instead.", 409)
        return JSONResponse({"request_id": request_id, "status": "running"}, status_code=202,
                            background=BackgroundTask(run_then_notify, request_id))

    async def get_artifact(request: HttpRequest) -> Response:
        try:
            artifact = await asyncio.to_thread(requests_of(deps).get_artifact, request.path_params["artifact_id"])
        except ArtifactNotFound as exc:
            return error(str(exc), 404)
        except ValueError as exc:
            return error(str(exc), 400)
        return JSONResponse(artifact.model_dump(mode="json"))

    async def list_artifacts(request: HttpRequest) -> Response:
        dataset_id = request.query_params.get("dataset_id")
        if not dataset_id:
            return error("Give a dataset_id.", 400)
        try:
            summaries = await asyncio.to_thread(requests_of(deps).list_artifacts, dataset_id=dataset_id)
        except ValueError as exc:
            return error(str(exc), 400)
        return JSONResponse([s.model_dump(mode="json") for s in summaries])

    async def post_ask(request: HttpRequest) -> Response:
        try:
            data = await read_json(request, AskInput)
        except TypeError as exc:
            return error(str(exc), 415)
        except ValueError as exc:
            return error(str(exc), 400)
        prompt = data.question if not data.dataset_id else f"{data.question}\n\nDataset: {data.dataset_id}"
        # A program's question runs the lead once, capped like a channel request; anything the lead draws on
        # the way is recorded as that program's request, not the chat's.
        result = await lead.run(prompt, deps=replace(deps, caller_kind="agent"),
                                usage_limits=UsageLimits(request_limit=REQUEST_LIMIT))
        return JSONResponse({"answer": result.output, "caller": data.caller.identity})

    app.router.routes[0:0] = [
        Route("/requests", post_requests, methods=["POST"]),
        Route("/requests/{request_id}", get_request, methods=["GET"]),
        Route("/requests/{request_id}/answer", post_answer, methods=["POST"]),
        Route("/requests/{request_id}/resume", post_resume, methods=["POST"]),
        Route("/artifacts", list_artifacts, methods=["GET"]),
        Route("/artifacts/{artifact_id}", get_artifact, methods=["GET"]),
        Route("/agents/ask", post_ask, methods=["POST"]),
    ]
