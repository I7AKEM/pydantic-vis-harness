import asyncio
import re

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from starlette.applications import Starlette
from starlette.requests import Request as HttpRequest
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from vis_agent.requests.api import add_request_routes

JSON = {"Content-Type": "application/json"}


@pytest.fixture
def app(deps, agents):
    _profiler, _analyst, _designer, lead = agents
    received = []

    async def callback(request: HttpRequest):
        received.append(await request.json())
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/callback", callback, methods=["POST"])])
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    add_request_routes(app, deps, lead, http=http)
    app.state.received = received
    return app


def body(dataset_id, **extra):
    return {"dataset_id": dataset_id, "question": "Total by region",
            "caller": {"identity": "reporter", "return_address": "http://testserver/callback"}, **extra}


def test_a_program_creates_a_request_and_receives_the_artifact(app, dataset_id, fake_models, fake_render):
    with TestClient(app) as client:
        created = client.post("/requests", json=body(dataset_id))
        assert created.status_code == 202
        request_id = created.json()["request_id"]
        assert re.fullmatch(r"rq_[0-9a-f]{32}", request_id)
        shown = client.get(f"/requests/{request_id}").json()
        assert shown["status"] == "done" and shown["artifact_id"] and shown["caller"]["identity"] == "reporter"
        artifact = client.get(f"/artifacts/{shown['artifact_id']}").json()
        assert artifact["version"] == 1 and artifact["png_url"].endswith("/chart.png")
        listed = client.get("/artifacts", params={"dataset_id": dataset_id}).json()
        assert [a["artifact_id"] for a in listed] == [shown["artifact_id"]]
    assert [r["status"] for r in app.state.received] == ["done"]
    assert app.state.received[0]["artifact_id"] == shown["artifact_id"]


def test_a_question_round_trips_over_the_channel(app, deps, dataset_id, fake_models, fake_render, agents):
    from tests.requests.conftest import analyst_drive, prompt_of

    _profiler, analyst, _designer, _lead = agents

    def ask_then_answer(messages, info):
        if not prompt_of(messages).get("clarifications"):
            return ModelResponse(parts=[ToolCallPart(tool_name="ask_clarification",
                                                     args={"question": "Which amount?", "reason": "Two."})])
        return analyst_drive(messages, info)

    with analyst.override(model=FunctionModel(ask_then_answer)), TestClient(app) as client:
        request_id = client.post("/requests", json=body(dataset_id)).json()["request_id"]
        shown = client.get(f"/requests/{request_id}").json()
        assert shown["status"] == "waiting" and shown["pending_question"] == "Which amount?" and shown["overdue"] is False
        assert app.state.received[-1]["status"] == "waiting"
        answered = client.post(f"/requests/{request_id}/answer", json={"answer": "The amount column"})
        assert answered.status_code == 202
        shown = client.get(f"/requests/{request_id}").json()
        assert shown["status"] == "done"
        artifact = client.get(f"/artifacts/{shown['artifact_id']}").json()
        assert artifact["clarifications"][0]["answered_by"] == "agent"
        again = client.post(f"/requests/{request_id}/answer", json={"answer": "x"})
        assert again.status_code == 409
    assert [r["status"] for r in app.state.received] == ["waiting", "done"]


def test_the_channel_refuses_bad_input(app, dataset_id):
    with TestClient(app) as client:
        assert client.post("/requests", content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
        assert client.post("/requests", json={"question": "x"}).status_code == 400
        assert client.post("/requests", json=body("ds_" + "0" * 32)).status_code == 404
        bad = body(dataset_id)
        bad["caller"]["return_address"] = "ftp://x"
        assert client.post("/requests", json=bad).status_code == 400
        assert client.get("/requests/rq_" + "0" * 32).status_code == 404
        assert client.get("/requests/nonsense").status_code == 400
        assert client.get("/artifacts").status_code == 400
        assert client.get("/artifacts/art_" + "0" * 32).status_code == 404


def test_resume_continues_a_failed_request(app, deps, dataset_id, fake_models, fake_render, monkeypatch):
    from vis_agent.requests import runner

    real = runner.design_chart
    state = {"died": False}

    async def dying(*args, **kwargs):
        if not state["died"]:
            state["died"] = True
            raise RuntimeError("died")
        return await real(*args, **kwargs)

    monkeypatch.setattr(runner, "design_chart", dying)
    with TestClient(app) as client:
        request_id = client.post("/requests", json=body(dataset_id)).json()["request_id"]
        assert client.get(f"/requests/{request_id}").json()["status"] == "failed"
        assert client.post(f"/requests/{request_id}/resume").status_code == 202
        assert client.get(f"/requests/{request_id}").json()["status"] == "done"


def test_a_program_asks_the_lead_a_question(app, agents):
    _profiler, _analyst, _designer, lead = agents

    def reply(messages, info):
        return ModelResponse(parts=[TextPart(content="I draw charts.")])

    with lead.override(model=FunctionModel(reply)), TestClient(app) as client:
        answer = client.post("/agents/ask", json={"question": "What can you do?", "caller": {"identity": "reporter"}})
        assert answer.status_code == 200 and answer.json()["answer"] == "I draw charts."
