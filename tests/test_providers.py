import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.openrouter import OpenRouterModel
from starlette.applications import Starlette
from starlette.testclient import TestClient

from vis_agent.analyst.agent import DEFAULT_ANALYST_MODEL, create_analyst
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import DEFAULT_DESIGNER_MODEL, create_designer
from vis_agent.lead import create_lead
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, create_profiler
from vis_agent.providers import DEFAULT_LEAD_MODEL, Team, add_chat_route, teams_from_env
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
    teams = [team("LiteLLM", "litellm", store), team("OpenRouter", "openrouter", store)]
    with TestClient(chat_app(teams), base_url="http://localhost") as client:
        models = client.get("/api/configure").json()["models"]
    assert [model["name"] for model in models] == ["LiteLLM", "OpenRouter"]
    assert [model["id"] for model in models] == [team.model_id for team in teams]


def test_a_message_runs_the_team_the_dropdown_names(store):
    teams = [team("LiteLLM", "litellm", store), team("OpenRouter", "openrouter", store)]
    with TestClient(chat_app(teams), base_url="http://localhost") as client:
        local = client.post("/api/chat", json=submit(teams[0].model_id))
        remote = client.post("/api/chat", json=submit(teams[1].model_id))
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


def test_chat_stops_a_lead_that_keeps_calling_tools(store, monkeypatch):
    monkeypatch.setattr("vis_agent.providers.REQUEST_LIMIT", 2)
    monkeypatch.setattr("vis_agent.providers.TOOL_LIMIT", 1)
    requests = 0

    async def repeat(messages: list[ModelMessage], info: AgentInfo):
        nonlocal requests
        requests += 1
        yield {0: DeltaToolCall(name="find_dataset", json_args="{}")}

    configured = team("Test", "loop", store)
    with configured.lead.override(model=FunctionModel(stream_function=repeat)):
        with TestClient(chat_app([configured]), base_url="http://localhost") as client:
            response = client.post("/api/chat", json=submit(configured.model_id))
    assert response.status_code == 200
    assert requests == 2
    assert '"type":"error"' in response.text


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
    assert deps.lead is lead


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
    assert teams[0].model_id == DEFAULT_LEAD_MODEL


def test_teams_from_env_offers_openrouter_only_when_its_key_is_set(store, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.delenv("PYDANTIC_AI_MODEL", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    teams = teams_from_env(store, RequestStore(store))
    assert [team.label for team in teams] == ["OpenRouter"]
    assert DEFAULT_LEAD_MODEL == "openrouter:z-ai/glm-5.3"
    assert teams[0].model_id == DEFAULT_LEAD_MODEL
    assert isinstance(teams[0].lead.model, OpenRouterModel)
    assert teams[0].deps.lead is teams[0].lead
    assert teams[0].lead.model_settings["openrouter_reasoning"] == {"effort": "low"}
    assert teams[0].lead.model_settings["openrouter_provider"] == {"require_parameters": True}
    assert DEFAULT_PROFILER_MODEL == DEFAULT_ANALYST_MODEL == "openrouter:z-ai/glm-5.3"
    assert DEFAULT_DESIGNER_MODEL == "openrouter:deepseek/deepseek-v4-pro"
    assert teams[0].deps.designer.model.model_name == "deepseek/deepseek-v4-pro"
    assert teams[0].deps.designer.model_settings["thinking"] is False
    assert teams[0].deps.designer_fallback.model.model_name == "deepseek/deepseek-v4-pro"
    assert teams[0].deps.analyst.model_settings["openrouter_reasoning"] == {"effort": "low"}
    assert teams[0].deps.profiler.model_settings["openrouter_reasoning"] == {"effort": "low"}
    assert teams[0].deps.reviewer.model.model_name == "google/gemma-4-31b-it"
    assert teams[0].deps.reviewer.model_settings == {"thinking": False, "temperature": 0.0}


def test_openrouter_lead_model_can_be_overridden(store, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("PYDANTIC_AI_MODEL", "openrouter:qwen/qwen3.8-2.4t-a95b")
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    configured = teams_from_env(store, RequestStore(store))[0]
    assert configured.model_id == "openrouter:qwen/qwen3.8-2.4t-a95b"
    assert configured.deps.lead is configured.lead


def test_teams_from_env_needs_a_provider(store, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="No provider is configured: set LITELLM_BASE_URL"):
        teams_from_env(store, RequestStore(store))


def test_review_and_design_may_use_the_same_model(store, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.setenv("PYDANTIC_AI_DESIGNER_MODEL", "openrouter:google/gemma-4-31b-it:nitro")
    monkeypatch.setenv("PYDANTIC_AI_REVIEWER_MODEL", "openrouter:google/gemma-4-31b-it:nitro")
    team = teams_from_env(store, RequestStore(store))[0]
    assert team.deps.reviewer is not None and team.deps.reviewer.name == "reviewer"


def test_the_litellm_reviewer_model_is_configurable(store, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm.local:4000")
    monkeypatch.setenv("LOCAL_LLM", "google/gemma-4")
    monkeypatch.setenv("LITELLM_TOKEN", "t")
    monkeypatch.setenv("LITELLM_REVIEWER_MODEL", "google/gemma-4")
    same = teams_from_env(store, RequestStore(store))[0]
    assert same.deps.reviewer.model.model_name == "google/gemma-4"
    monkeypatch.setenv("LITELLM_REVIEWER_MODEL", "Qwen/Qwen3.8-27B")
    team = teams_from_env(store, RequestStore(store))[0]
    assert team.deps.reviewer.model.model_name == "Qwen/Qwen3.8-27B"


def test_openrouter_reasoning_effort_is_configurable_and_validated(store, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.setenv("PYDANTIC_AI_LEAD_REASONING_EFFORT", "high")
    configured = teams_from_env(store, RequestStore(store))[0]
    assert configured.lead.model_settings["openrouter_reasoning"] == {"effort": "high"}
    monkeypatch.setenv("PYDANTIC_AI_LEAD_REASONING_EFFORT", "typo")
    with pytest.raises(ValueError, match="effort"):
        teams_from_env(store, RequestStore(store))
