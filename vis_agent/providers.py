"""Providers: one team of agents per place the models run, chosen in the chat's dropdown."""

import os
from dataclasses import dataclass

from pydantic import TypeAdapter
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings, OpenRouterReasoning
from pydantic_ai.providers.litellm import LiteLLMProvider
from pydantic_ai.usage import UsageLimits
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from vis_agent.analyst.agent import DEFAULT_ANALYST_MODEL, create_analyst
from vis_agent.chat_stream import ChatAdapter
from vis_agent.deps import AppDeps
from vis_agent.designer.agent import DEFAULT_DESIGNER_MODEL, DEFAULT_FALLBACK_DESIGNER_MODEL, create_designer
from vis_agent.lead import create_lead
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, create_profiler
from vis_agent.requests.service import REQUEST_LIMIT, TOOL_LIMIT
from vis_agent.requests.store import RequestStore
from vis_agent.reviewer.agent import DEFAULT_REVIEWER_MODEL, create_reviewer
from vis_agent.store import DatasetStore

CHAT_UI_SDK_VERSION = 7  # what the bundled chat UI speaks: pydantic_ai.ui._web.api.BUNDLED_UI_SDK_VERSION
DEFAULT_LEAD_MODEL = "openrouter:z-ai/glm-5.3"


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


def openrouter_team(store: DatasetStore, requests: RequestStore, *, lead_instructions: str | None = None) -> Team:
    """A thinking lead manages fast specialists; each model can be overridden independently."""
    model_name = os.getenv("PYDANTIC_AI_MODEL") or DEFAULT_LEAD_MODEL
    model = OpenRouterModel(model_name.removeprefix("openrouter:"))
    profiler = create_profiler(os.getenv("PYDANTIC_AI_PROFILER_MODEL") or DEFAULT_PROFILER_MODEL)
    analyst = create_analyst(os.getenv("PYDANTIC_AI_ANALYST_MODEL") or DEFAULT_ANALYST_MODEL)
    designer_model = os.getenv("PYDANTIC_AI_DESIGNER_MODEL") or DEFAULT_DESIGNER_MODEL
    reviewer_model = os.getenv("PYDANTIC_AI_REVIEWER_MODEL") or DEFAULT_REVIEWER_MODEL
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
    lead = create_lead(
        model,
        advisor_model=os.getenv("PYDANTIC_AI_ADVISOR_MODEL") or None,
        **({"instructions": lead_instructions} if lead_instructions is not None else {}),
        model_settings=OpenRouterModelSettings(
            openrouter_reasoning=TypeAdapter(OpenRouterReasoning).validate_python(
                {"effort": os.getenv("PYDANTIC_AI_LEAD_REASONING_EFFORT") or "low"}
            ),
            openrouter_provider={"require_parameters": True},
        ),
    )
    deps.lead = lead
    return Team("OpenRouter", lead, deps)


def litellm_model(name: str | None = None) -> OpenAIChatModel:
    """A proxy model: LOCAL_LLM by default, or the named one, through LITELLM_BASE_URL with LITELLM_TOKEN."""
    return OpenAIChatModel(
        name or os.environ["LOCAL_LLM"],
        provider=LiteLLMProvider(api_base=os.environ["LITELLM_BASE_URL"], api_key=os.getenv("LITELLM_TOKEN")),
    )


def litellm_team(store: DatasetStore, requests: RequestStore, *, lead_instructions: str | None = None) -> Team:
    """Use configured proxy models. The lead may explicitly choose the alternate designer or reviewer."""
    model = litellm_model()
    reviewer_model = os.getenv("LITELLM_REVIEWER_MODEL") or "Qwen/Qwen3.8-27B"
    deps = AppDeps(
        store=store,
        profiler=create_profiler(model),
        analyst=create_analyst(model),
        designer=create_designer(model),
        requests=requests,
        designer_fallback=create_designer(model),
        reviewer=create_reviewer(litellm_model(reviewer_model)),
    )
    lead = create_lead(model, **({"instructions": lead_instructions} if lead_instructions is not None else {}))
    deps.lead = lead
    return Team("LiteLLM", lead, deps)


def teams_from_env(store: DatasetStore, requests: RequestStore, *, lead_instructions: str | None = None) -> list[Team]:
    """OpenRouter leads by default when configured; the first team also serves the agent channel."""
    teams: list[Team] = []
    options = {"lead_instructions": lead_instructions} if lead_instructions is not None else {}
    if os.getenv("OPENROUTER_API_KEY"):
        teams.append(openrouter_team(store, requests, **options))
    if os.getenv("LITELLM_BASE_URL"):
        teams.append(litellm_team(store, requests, **options))
    if not teams:
        raise RuntimeError(
            "No provider is configured: set LITELLM_BASE_URL with LOCAL_LLM and LITELLM_TOKEN, or OPENROUTER_API_KEY."
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
        return await ChatAdapter.dispatch_request(
            request,
            agent=team.lead,
            deps=team.deps,
            sdk_version=CHAT_UI_SDK_VERSION,
            usage_limits=UsageLimits(request_limit=REQUEST_LIMIT, tool_calls_limit=TOOL_LIMIT),
        )

    app.router.routes[0:0] = [Route("/api/chat", post_chat, methods=["POST"])]
