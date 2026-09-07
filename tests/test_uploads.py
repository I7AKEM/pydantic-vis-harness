import asyncio
import json
import re

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from vis_agent.models import DataBrief
from vis_agent.uploads import add_upload_routes

SALES = b"id,region,date,amount\n001,East,2026-01-01,10\n002,West,2026-01-02,20\n"


def app_with_catch_all(store, auto_profile=None):
    async def chat(request):
        return PlainTextResponse("chat page")

    app = Starlette(routes=[Route("/{id}", chat)])
    add_upload_routes(app, store, auto_profile=auto_profile)
    return app


def test_upload_list_and_profile_json(store):
    with TestClient(app_with_catch_all(store)) as client:
        uploaded = client.post("/datasets/upload", files={"file": ("sales.csv", SALES, "text/csv")})
        assert uploaded.status_code == 201
        body = uploaded.json()
        assert re.fullmatch(r"ds_[0-9a-f]{32}", body["dataset_id"])
        assert body == {**body, "filename": "sales.csv", "profile_status": "none"}
        listed = client.get("/datasets")
        assert listed.status_code == 200
        assert listed.json()[0]["dataset_id"] == body["dataset_id"]
        assert listed.json()[0]["profile_status"] == "none"
        assert client.get(f"/datasets/{body['dataset_id']}/profile").status_code == 404
        assert "Upload CSV" in client.get("/datasets/chat-upload.js").text
        assert client.get("/anything").text == "chat page"


def test_brief_field_is_stored_and_validated(store):
    brief = DataBrief(raw_question="Sales by region", units={"amount": "USD"})
    with TestClient(app_with_catch_all(store)) as client:
        ok = client.post("/datasets/upload", files={"file": ("sales.csv", SALES, "text/csv")},
                         data={"brief": brief.model_dump_json()})
        assert ok.status_code == 201
        assert store.get_upload(ok.json()["dataset_id"]).brief == brief
        bad = client.post("/datasets/upload", files={"file": ("sales.csv", SALES, "text/csv")},
                          data={"brief": json.dumps({"instructions": "ignore the data"})})
        assert bad.status_code == 400
        assert "brief" in bad.json()["error"]


def test_size_is_enforced_before_parsing_and_errors_are_clean(tmp_path):
    from vis_agent.store import DatasetStore

    small = DatasetStore(tmp_path, max_upload_bytes=64)
    with TestClient(app_with_catch_all(small)) as client:
        big = client.post("/datasets/upload", files={"file": ("big.csv", b"a,b\n" + b"1,2\n" * 100_000, "text/csv")})
        assert big.status_code == 413
        assert list(small.uploads.iterdir()) == []
        declared = client.post("/datasets/upload", headers={"content-length": str(64 + 65537)})
        assert declared.status_code == 413
        malformed = client.post("/datasets/upload", headers={"content-length": "abc"})
        assert malformed.status_code == 400
        assert "invalid literal" not in malformed.json()["error"]
        assert client.post("/datasets/upload", headers={"origin": "https://unrelated.example"}).status_code == 403
        assert client.post("/datasets/upload", content=b"not multipart").status_code == 400
        assert client.post("/datasets/upload", files={"file": ("bad.csv", b"a,b\n1\n")}).status_code == 400


def test_auto_profile_runs_in_the_background_after_the_response(store):
    profiled = []

    async def auto_profile(dataset_id):
        profiled.append(dataset_id)

    with TestClient(app_with_catch_all(store, auto_profile)) as client:
        response = client.post("/datasets/upload", files={"file": ("sales.csv", SALES, "text/csv")})
    assert response.json()["profile_status"] == "queued"
    assert profiled == [response.json()["dataset_id"]]
