"""Local file upload API used by the CSV control in Pydantic AI's chat."""

import asyncio
from pathlib import Path

from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from dataset_store import DatasetStore


def add_upload_routes(app: Starlette, store: DatasetStore) -> None:
    async def upload(request: Request) -> Response:
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"error": "Upload the CSV from this app's chat."}, status_code=403)

        try:
            if int(request.headers.get("content-length", "0")) > store.max_upload_bytes + 65536:
                return JSONResponse({"error": "The CSV exceeds the upload size limit."}, status_code=413)
            async with request.form(max_files=1, max_fields=0) as form:
                file = form.get("file")
                if not isinstance(file, UploadFile) or not file.filename:
                    raise ValueError("Choose a CSV file first.")
                content = await file.read(store.max_upload_bytes + 1)
                dataset = await asyncio.to_thread(store.save_upload, file.filename, content)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # Raw CSV contents never enter a chat message. The tool receives this ID.
        return JSONResponse({"dataset_id": dataset.dataset_id, "filename": dataset.filename}, status_code=201)

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

    app.router.routes.extend([
        Route("/datasets/upload", upload, methods=["POST"]),
        Route("/datasets/chat-upload.js", chat_upload_script, methods=["GET"]),
        Route("/datasets/{dataset_id}/profile", profile, methods=["GET"]),
    ])
