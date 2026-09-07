"""Read-only routes for the renderer's three public artifacts."""

import re

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from vis_agent.store import DatasetStore

RENDER_ID = re.compile(r"[0-9a-f]{12}\Z")
FILES = {"chart.png": "image/png", "chart.html": "text/html", "config.json": "application/json"}


def add_render_routes(app: Starlette, store: DatasetStore) -> None:
    async def render_file(request: Request) -> Response:
        identifier, file = request.path_params["render_id"], request.path_params["file"]
        if not RENDER_ID.fullmatch(identifier) or file not in FILES:
            return JSONResponse({"error": "Render file not found."}, status_code=404)
        path = store.directory / "renders" / identifier / file
        if not path.is_file():
            return JSONResponse({"error": "Render file not found."}, status_code=404)
        return FileResponse(path, media_type=FILES[file])

    app.router.routes[0:0] = [Route("/renders/{render_id}/{file}", render_file, methods=["GET"])]
