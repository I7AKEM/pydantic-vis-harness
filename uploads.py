"""A small CSV upload page alongside Pydantic AI's built-in chat."""

import asyncio
from html import escape

from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from dataset_store import DatasetStore


def page(content: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>CSV upload · Visualization agent</title>"
        "<style>body{font:16px system-ui;max-width:680px;margin:64px auto;padding:0 24px;"
        "line-height:1.6;color:#172b3a;background:#f8fafb}"
        "a{color:#075985}form{padding:24px;background:white;border:1px solid #cbd5e1;"
        "border-radius:8px}button{display:block;margin-top:20px;padding:10px 18px;"
        "background:#075985;color:white;border:0;border-radius:5px;font:inherit;cursor:pointer}"
        "code{overflow-wrap:anywhere}textarea{box-sizing:border-box;width:100%;padding:12px;"
        "font:14px monospace}label{display:block;margin-bottom:12px}</style>"
        f"<body><main><a href='/'>← Chat</a>{content}</main></body></html>",
        status_code=status_code,
    )


def add_upload_routes(app: Starlette, store: DatasetStore) -> None:
    async def upload(request: Request) -> Response:
        if request.method == "GET":
            return page(
                "<h1>Upload a CSV</h1><p>Choose your dataset, then use its file ID in chat "
                "to get a statistical and semantic profile.</p>"
                "<form method='post' enctype='multipart/form-data'>"
                "<label for='file'>CSV file</label>"
                "<input id='file' name='file' type='file' accept='.csv,text/csv' required>"
                "<button type='submit'>Upload CSV</button></form>"
                f"<p>UTF-8, comma-separated, with unique column headers. "
                f"Maximum {store.max_upload_bytes // (1024 * 1024)} MB and 100 columns.</p>"
                "<p>Profiling sends column statistics and a small sample to the configured "
                "model through OpenRouter.</p>"
            )

        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return page("<h1>Upload refused</h1><p>Open the upload page on this app to submit a file.</p>", 403)
        if int(request.headers.get("content-length", "0")) > store.max_upload_bytes + 65536:
            return page("<h1>File too large</h1><p>Choose a smaller CSV.</p>", 413)

        try:
            async with request.form(max_files=1, max_fields=0) as form:
                file = form.get("file")
                if not isinstance(file, UploadFile) or not file.filename:
                    raise ValueError("Choose a CSV file first.")
                content = await file.read(store.max_upload_bytes + 1)
                dataset = await asyncio.to_thread(store.save_upload, file.filename, content)
        except ValueError as exc:
            return page(f"<h1>Upload failed</h1><p>{escape(str(exc))}</p><a href='/datasets/upload'>Try again</a>", 400)

        prompt = f"Profile uploaded CSV {dataset.dataset_id} using profile_csv. Summarize the result and link to its JSON."
        return page(
            f"<h1>CSV uploaded</h1><p>{escape(dataset.filename)}</p>"
            f"<p>File ID: <code>{dataset.dataset_id}</code></p>"
            "<label for='prompt'>Copy this message into chat:</label>"
            f"<textarea id='prompt' rows='4' readonly>{escape(prompt)}</textarea>"
            "<p><a href='/'>Open chat</a></p>"
            f"<p>After profiling: <a href='/datasets/{dataset.dataset_id}/profile'>View structured profile (JSON)</a></p>"
            "<p><a href='/datasets/upload'>Upload another CSV</a></p>"
        )

    async def profile(request: Request) -> Response:
        try:
            result = await asyncio.to_thread(store.get_profile, request.path_params["dataset_id"])
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        if result is None:
            return JSONResponse({"error": "This CSV has not been profiled yet. Ask the chat agent to profile its file ID."}, status_code=404)
        return JSONResponse(result.model_dump(mode="json"))

    app.router.routes.extend([
        Route("/datasets/upload", upload, methods=["GET", "POST"]),
        Route("/datasets/{dataset_id}/profile", profile, methods=["GET"]),
    ])
