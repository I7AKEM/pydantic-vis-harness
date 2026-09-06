"""Local upload API used by the CSV control in Pydantic AI's chat, plus dataset listing."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from dataset_store import DatasetStore
from profile_models import DataBrief

AutoProfile = Callable[[str], Awaitable[None]]
BODY_SLACK = 65536


class BodyTooLarge(Exception):
    pass


async def read_body(request: Request, limit: int) -> bytes:
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise BodyTooLarge
        chunks.append(chunk)
    return b"".join(chunks)


async def one_chunk(body: bytes) -> AsyncGenerator[bytes, None]:
    yield body


def add_upload_routes(app: Starlette, store: DatasetStore, auto_profile: AutoProfile | None = None) -> None:
    too_large = JSONResponse({"error": "The CSV exceeds the upload size limit."}, status_code=413)

    async def upload(request: Request) -> Response:
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"error": "Upload the CSV from this app's chat."}, status_code=403)
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"error": "Invalid Content-Length header."}, status_code=400)
        limit = store.max_upload_bytes + BODY_SLACK
        if declared > limit:
            return too_large
        try:
            body = await read_body(request, limit)
        except BodyTooLarge:
            return too_large

        content_type = request.headers.get("content-type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            return JSONResponse({"error": "Send the CSV as a multipart form with a file field."}, status_code=400)

        try:
            parser = MultiPartParser(request.headers, one_chunk(body), max_files=1, max_fields=1)
            form = await parser.parse()
            file = form.get("file")
            if not isinstance(file, UploadFile) or not file.filename:
                raise ValueError("Choose a CSV file first.")
            brief = None
            brief_text = form.get("brief")
            if isinstance(brief_text, str) and brief_text.strip():
                try:
                    brief = DataBrief.model_validate_json(brief_text)
                except ValidationError as exc:
                    raise ValueError(f"The brief is not valid: {exc.errors()[0]['msg']}") from exc
            content = await file.read(store.max_upload_bytes + 1)
            dataset = await asyncio.to_thread(store.save_upload, file.filename, content, brief)
        except MultiPartException:
            return JSONResponse({"error": "Send the CSV as a multipart form with a file field."}, status_code=400)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # Raw CSV contents never enter a chat message. The tool receives this ID.
        background = BackgroundTask(auto_profile, dataset.dataset_id) if auto_profile else None
        return JSONResponse(
            {"dataset_id": dataset.dataset_id, "filename": dataset.filename,
             "profile_status": "queued" if auto_profile else "none"},
            status_code=201,
            background=background,
        )

    async def list_datasets(request: Request) -> Response:
        summaries = await asyncio.to_thread(store.list_datasets)
        return JSONResponse([summary.model_dump(mode="json") for summary in summaries])

    async def chat_upload_script(request: Request) -> Response:
        return FileResponse(Path(__file__).with_name("chat_upload.js"), media_type="text/javascript")

    async def profile(request: Request) -> Response:
        try:
            result = await asyncio.to_thread(store.get_profile, request.path_params["dataset_id"])
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        if result is None:
            return JSONResponse({"error": "This CSV has not been profiled yet."}, status_code=404)
        return JSONResponse(result.model_dump(mode="json"))

    # Insert before the chat UI's single-segment catch-all so /datasets is never shadowed.
    app.router.routes[0:0] = [
        Route("/datasets/upload", upload, methods=["POST"]),
        Route("/datasets", list_datasets, methods=["GET"]),
        Route("/datasets/chat-upload.js", chat_upload_script, methods=["GET"]),
        Route("/datasets/{dataset_id}/profile", profile, methods=["GET"]),
    ]
