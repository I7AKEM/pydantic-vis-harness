import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from vis_agent.renders import add_render_routes


@pytest.fixture
def client(store):
    async def chat(request):
        return PlainTextResponse("chat")

    app = Starlette(routes=[Route("/{path:path}", chat)])
    add_render_routes(app, store)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("file,media_type,content", [
    ("chart.png", "image/png", b"fake png"),
    ("chart.html", "text/html", b"<html>Chart</html>"),
    ("config.json", "application/json", b"{}"),
])
def test_existing_render_is_served(store, client, file, media_type, content):
    directory = store.directory / "renders" / "0123456789ab"
    directory.mkdir(parents=True)
    (directory / file).write_bytes(content)
    response = client.get(f"/renders/0123456789ab/{file}")
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == media_type
    assert response.content == content


@pytest.mark.parametrize("path", [
    "/renders/0123456789ab/chart.png",
    "/renders/012345678/chart.png",
    "/renders/0123456789AB/chart.png",
    "/renders/%2E%2E/chart.png",
    "/renders/0123456789ab/notes.txt",
])
def test_invalid_or_missing_render_is_404_json(store, client, path):
    directory = store.directory / "renders" / "0123456789ab"
    directory.mkdir(parents=True)
    (directory / "notes.txt").write_text("private notes")
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert "error" in response.json()


def test_render_routes_are_read_only(client):
    assert client.post("/renders/0123456789ab/chart.png").status_code == 405
