"""Providers: one team of agents per place the models run, chosen in the chat's dropdown."""

import os
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.litellm import LiteLLMProvider
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from vis_agent.analyst.agent import DEFAULT_ANALYST_MODEL, create_analyst
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import DEFAULT_DESIGNER_MODEL, DEFAULT_FALLBACK_DESIGNER_MODEL, create_designer
from vis_agent.lead import create_lead
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, create_profiler
from vis_agent.requests.store import RequestStore
from vis_agent.reviewer.agent import DEFAULT_REVIEWER_MODEL, create_reviewer
from vis_agent.store import DatasetStore

CHAT_UI_SDK_VERSION = 7  # what the bundled chat UI speaks: pydantic_ai.ui._web.api.BUNDLED_UI_SDK_VERSION
DEFAULT_ADVISOR_MODEL = "openrouter:openai/gpt-5.6-sol"


@dataclass
class Team:
    """A lead and its specialists, all reaching their models through one provider."""

    label: str
    lead: Agent[AppDeps, str]
    deps: AppDeps

    @property
    def model_id(self) -> str:
        """What the dropdown sends for this team: a model name as given, or a model instance's id, the same rule
        the web UI applies to the models it lists."""
        model = self.lead.model
        assert model is not None
        return model if isinstance(model, str) else model.model_id


def _reviewer_seat(reviewer_model: str, designer_model: str):
    if reviewer_model.removeprefix("openrouter:") == designer_model.removeprefix("openrouter:"):
        raise RuntimeError(f"The reviewer must not sit on the designer's model ({designer_model}); "
                           "set PYDANTIC_AI_REVIEWER_MODEL or LITELLM_REVIEWER_MODEL to another model.")


def openrouter_team(store: DatasetStore, requests: RequestStore) -> Team:
    """Today's wiring: each role's model from its PYDANTIC_AI_*_MODEL variable, with the measured defaults."""
    model = os.getenv("PYDANTIC_AI_MODEL") or DEFAULT_PROFILER_MODEL
    profiler = create_profiler(os.getenv("PYDANTIC_AI_PROFILER_MODEL") or DEFAULT_PROFILER_MODEL)
    analyst = create_analyst(os.getenv("PYDANTIC_AI_ANALYST_MODEL") or DEFAULT_ANALYST_MODEL)
    designer_model = os.getenv("PYDANTIC_AI_DESIGNER_MODEL") or DEFAULT_DESIGNER_MODEL
    reviewer_model = os.getenv("PYDANTIC_AI_REVIEWER_MODEL") or DEFAULT_REVIEWER_MODEL
    _reviewer_seat(reviewer_model, designer_model)
    designer = create_designer(designer_model)
    designer_fallback = create_designer(
        os.getenv("PYDANTIC_AI_DESIGNER_FALLBACK_MODEL") or DEFAULT_FALLBACK_DESIGNER_MODEL
    )
    deps = AppDeps(
        store=store,
        profiler=profiler,
        analyst=analyst,
        designer=designer,
        requests=requests,
        designer_fallback=designer_fallback,
        reviewer=create_reviewer(reviewer_model),
    )
    lead = create_lead(model, advisor_model=os.getenv("PYDANTIC_AI_ADVISOR_MODEL", DEFAULT_ADVISOR_MODEL))
    return Team("OpenRouter", lead, deps)


def litellm_model(name: str | None = None) -> OpenAIChatModel:
    """A proxy model: LOCAL_LLM by default, or the named one, through LITELLM_BASE_URL with LITELLM_TOKEN."""
    return OpenAIChatModel(
        name or os.environ["LOCAL_LLM"],
        provider=LiteLLMProvider(api_base=os.environ["LITELLM_BASE_URL"], api_key=os.getenv("LITELLM_TOKEN")),
    )


def litellm_team(store: DatasetStore, requests: RequestStore) -> Team:
    """The reviewer uses a second proxy model; the other roles use LOCAL_LLM. No advisor: the native advisor
    needs an OpenRouter lead. The fallback designer is a second designer on LOCAL_LLM for one more attempt."""
    model = litellm_model()
    reviewer_model = os.getenv("LITELLM_REVIEWER_MODEL") or "Qwen/Qwen3.8-27B"
    _reviewer_seat(reviewer_model, os.environ["LOCAL_LLM"])
    deps = AppDeps(
        store=store,
        profiler=create_profiler(model),
        analyst=create_analyst(model),
        designer=create_designer(model),
        requests=requests,
        designer_fallback=create_designer(model),
        reviewer=create_reviewer(litellm_model(reviewer_model)),
    )
    return Team("LiteLLM", create_lead(model), deps)


def teams_from_env(store: DatasetStore, requests: RequestStore) -> list[Team]:
    """The providers the environment configures, OpenRouter first. The first team profiles uploads and serves the
    agent channel."""
    teams: list[Team] = []
    if os.getenv("OPENROUTER_API_KEY"):
        teams.append(openrouter_team(store, requests))
    if os.getenv("LITELLM_BASE_URL"):
        teams.append(litellm_team(store, requests))
    if not teams:
        raise RuntimeError(
            "No provider is configured: set OPENROUTER_API_KEY, or LITELLM_BASE_URL with LOCAL_LLM and LITELLM_TOKEN."
        )
    return teams


def add_chat_route(app: Starlette, teams: list[Team]) -> None:
    """Run each chat message on the team whose lead the dropdown names. Placed in front of the web UI's own
    /api/chat, which can run only one agent with one deps."""
    by_model = {team.model_id: team for team in teams}

    async def post_chat(request: Request) -> Response:
        media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media_type != "application/json":
            return JSONResponse(
                {"error": f"Expected `Content-Type: application/json`, got {media_type or 'no content type'}"},
                status_code=415,
            )
        body = await request.json()
        model = body.get("model") if isinstance(body, dict) else None
        team = by_model.get(model)
        if team is None:
            return JSONResponse({"error": f'Model "{model}" is not in the allowed models list'}, status_code=400)
        return await VercelAIAdapter.dispatch_request(
            request,
            agent=team.lead,
            deps=team.deps,
            sdk_version=CHAT_UI_SDK_VERSION,
        )

    app.router.routes[0:0] = [Route("/api/chat", post_chat, methods=["POST"])]
