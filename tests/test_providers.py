import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from starlette.applications import Starlette
from starlette.testclient import TestClient

from vis_agent.analyst.agent import create_analyst
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import create_designer
from vis_agent.lead import create_lead
from vis_agent.profiler.agent import create_profiler
from vis_agent.providers import Team, add_chat_route, teams_from_env
from vis_agent.requests.store import RequestStore


def saying(text: str, name: str) -> FunctionModel:
    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    async def stream(messages: list[ModelMessage], info: AgentInfo):
        yield text

    return FunctionModel(reply, stream_function=stream, model_name=name)


def team(label: str, name: str, store) -> Team:
    lead = create_lead(saying(f"{label} lead here", name))
    deps = AppDeps(
        store=store,
        profiler=create_profiler("test"),
        analyst=create_analyst("test"),
        designer=create_designer("test"),
    )
    return Team(label, lead, deps)


def chat_app(teams: list[Team]) -> Starlette:
    menu: Agent[AppDeps, str] = Agent(None, name="vis-menu")
    app = menu.to_web(models={t.label: t.lead.model for t in teams})
    add_chat_route(app, teams)
    return app


def submit(model_id: str) -> dict:
    return {
        "id": "c1",
        "trigger": "submit-message",
        "model": model_id,
        "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "hello"}]}],
    }


def test_the_dropdown_lists_the_teams_by_name(store):
    teams = [team("OpenRouter", "openrouter", store), team("LiteLLM", "litellm", store)]
    with TestClient(chat_app(teams), base_url="http://localhost") as client:
        models = client.get("/api/configure").json()["models"]
    assert [model["name"] for model in models] == ["OpenRouter", "LiteLLM"]
    assert [model["id"] for model in models] == [team.model_id for team in teams]


def test_a_message_runs_the_team_the_dropdown_names(store):
    teams = [team("OpenRouter", "openrouter", store), team("LiteLLM", "litellm", store)]
    with TestClient(chat_app(teams), base_url="http://localhost") as client:
        local = client.post("/api/chat", json=submit(teams[1].model_id))
        remote = client.post("/api/chat", json=submit(teams[0].model_id))
    assert local.status_code == 200 and "LiteLLM lead here" in local.text
    assert remote.status_code == 200 and "OpenRouter lead here" in remote.text


def test_an_unknown_model_is_refused(store):
    teams = [team("OpenRouter", "openrouter", store)]
    with TestClient(chat_app(teams), base_url="http://localhost") as client:
        response = client.post("/api/chat", json=submit("unknown:model"))
    assert response.status_code == 400
    assert response.json()["error"] == 'Model "unknown:model" is not in the allowed models list'


def test_a_form_post_is_refused(store):
    teams = [team("OpenRouter", "openrouter", store)]
    with TestClient(chat_app(teams), base_url="http://localhost") as client:
        response = client.post("/api/chat", data={"model": "x"})
    assert response.status_code == 415


def test_teams_from_env_offers_litellm_only_when_its_url_is_set(store, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm.local:4000")
    monkeypatch.setenv("LOCAL_LLM", "google/gemma-4")
    monkeypatch.setenv("LITELLM_TOKEN", "t")
    teams = teams_from_env(store, RequestStore(store))
    assert [team.label for team in teams] == ["LiteLLM"]
    lead = teams[0].lead
    deps = teams[0].deps
    assert teams[0].model_id == "litellm:google/gemma-4"
    assert lead.model is not None
    assert lead.model.base_url.rstrip("/") == "http://litellm.local:4000"
    assert deps.profiler.model is deps.analyst.model is deps.designer.model is deps.designer_fallback.model is lead.model


def test_a_team_on_a_named_model_sends_the_name(store):
    deps = AppDeps(store=store, profiler=create_profiler("test"), analyst=create_analyst("test"), designer=create_designer("test"))
    assert Team("Test", create_lead("test"), deps).model_id == "test"


def test_teams_from_env_puts_openrouter_first(store, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.delenv("PYDANTIC_AI_MODEL", raising=False)
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm.local:4000")
    monkeypatch.setenv("LOCAL_LLM", "google/gemma-4")
    monkeypatch.setenv("LITELLM_TOKEN", "t")
    teams = teams_from_env(store, RequestStore(store))
    assert [team.label for team in teams] == ["OpenRouter", "LiteLLM"]
    assert teams[0].model_id == "openrouter:google/gemma-4-31b-it:nitro"


def test_teams_from_env_needs_a_provider(store, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="No provider is configured: set OPENROUTER_API_KEY, or LITELLM_BASE_URL"):
        teams_from_env(store, RequestStore(store))
