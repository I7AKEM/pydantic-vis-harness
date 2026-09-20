import re

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
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


def test_an_existing_caller_decision_round_trips_over_the_channel(app, deps, dataset_id, fake_models, fake_render):
    import asyncio

    from vis_agent.requests.models import Caller
    from vis_agent.requests.service import create_request, pause_request

    request = create_request(deps, type="new", dataset_id=dataset_id, question="Compare regional sales",
                             caller=Caller(kind="agent", identity="reporter", return_address="http://testserver/callback"))
    asyncio.run(pause_request(deps, request, "Use your brand colours?", "An explicit presentation preference."))
    request_id = request.request_id
    with TestClient(app) as client:
        shown = client.get(f"/requests/{request_id}").json()
        assert shown["status"] == "waiting" and shown["pending_question"] == "Use your brand colours?"
        assert client.post(f"/requests/{request_id}/resume", headers=JSON).status_code == 409
        answered = client.post(f"/requests/{request_id}/answer", json={"answer": "Use blue"})
        assert answered.status_code == 202
        shown = client.get(f"/requests/{request_id}").json()
        assert shown["status"] == "done"
        artifact = client.get(f"/artifacts/{shown['artifact_id']}").json()
        assert artifact["clarifications"][0]["answered_by"] == "agent"
        assert client.post(f"/requests/{request_id}/answer", json={"answer": "x"}).status_code == 409
    assert [r["status"] for r in app.state.received] == ["done"]


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
    from vis_agent import lead as lead_module

    real = lead_module.design_chart
    state = {"died": False}

    async def dying(*args, **kwargs):
        if not state["died"]:
            state["died"] = True
            raise RuntimeError("died")
        return await real(*args, **kwargs)

    monkeypatch.setattr(lead_module, "design_chart", dying)
    with TestClient(app) as client:
        request_id = client.post("/requests", json=body(dataset_id)).json()["request_id"]
        assert client.get(f"/requests/{request_id}").json()["status"] == "failed"
        assert client.post(f"/requests/{request_id}/resume").status_code == 415
        assert client.post(f"/requests/{request_id}/resume", headers=JSON).status_code == 202
        assert client.get(f"/requests/{request_id}").json()["status"] == "done"


def test_a_program_asks_the_lead_a_question(app, agents):
    _profiler, _analyst, _designer, lead = agents

    def reply(messages, info):
        return ModelResponse(parts=[TextPart(content="I draw charts.")])

    with lead.override(model=FunctionModel(reply)), TestClient(app) as client:
        answer = client.post("/agents/ask", json={"question": "What can you do?", "caller": {"identity": "reporter"}})
        assert answer.status_code == 200 and answer.json()["answer"] == "I draw charts."


def test_a_broken_callback_is_logged_not_raised(deps, agents, dataset_id, fake_models, fake_render, caplog):
    _profiler, _analyst, _designer, lead = agents

    class Broken:
        async def post(self, *args, **kwargs):
            raise RuntimeError("the return address exploded")

    app = Starlette(routes=[])
    add_request_routes(app, deps, lead, http=Broken())
    with TestClient(app) as client:
        request_id = client.post("/requests", json=body(dataset_id)).json()["request_id"]
        shown = client.get(f"/requests/{request_id}").json()
    assert shown["status"] == "done" and shown["artifact_id"]
    assert any("callback" in message and "exploded" in message for message in caplog.messages)


def test_a_program_question_that_draws_is_recorded_as_the_programs(app, deps, agents, dataset_id, fake_models, fake_render):
    _profiler, _analyst, _designer, lead = agents

    def drawing(messages, info):
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart(tool_name="draw", args={"dataset_id": dataset_id,
                                                                            "question": "Total by region"})])
        context = returns[-1].model_response_object()
        request_id = context["request_id"]
        if returns[-1].tool_name == "draw":
            return ModelResponse(parts=[ToolCallPart(tool_name="design_visualization", args={"request_id": request_id})])
        if returns[-1].tool_name == "design_visualization":
            return ModelResponse(parts=[ToolCallPart(tool_name="render_visualization", args={"request_id": request_id})])
        if returns[-1].tool_name == "render_visualization":
            return ModelResponse(parts=[ToolCallPart(tool_name="review_visualization", args={"request_id": request_id})])
        if returns[-1].tool_name == "review_visualization":
            return ModelResponse(parts=[ToolCallPart(tool_name="publish_visualization", args={"request_id": request_id})])
        return ModelResponse(parts=[TextPart(content=context["card"])])

    with lead.override(model=FunctionModel(drawing)), TestClient(app) as client:
        answer = client.post("/agents/ask", json={"question": "Chart total by region", "dataset_id": dataset_id,
                                                  "caller": {"identity": "reporter"}})
        assert answer.status_code == 200 and "/renders/" in answer.json()["answer"]
    summaries = deps.requests.list_requests(dataset_id=dataset_id)
    assert len(summaries) == 1
    caller = deps.requests.get_request(summaries[0].request_id).caller
    assert caller.kind == "agent" and caller.identity == "reporter"


def test_deadlines_are_bounded(app, dataset_id):
    with TestClient(app) as client:
        assert client.post("/requests", json=body(dataset_id, deadline_seconds=0)).status_code == 400
        assert client.post("/requests", json=body(dataset_id, deadline_seconds=40 * 24 * 3600)).status_code == 400
