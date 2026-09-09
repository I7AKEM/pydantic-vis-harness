"""Environment wiring only. Everything else lives in the modules it names."""

import logging
import os
from pathlib import Path

import logfire
from dotenv import load_dotenv
from pydantic_ai import Agent

from vis_agent.deps import AppDeps
from vis_agent.profiler.agent import profile_dataset
from vis_agent.providers import add_chat_route, teams_from_env
from vis_agent.renders import add_render_routes
from vis_agent.requests.api import add_request_routes
from vis_agent.requests.store import RequestStore
from vis_agent.store import DatasetStore
from vis_agent.uploads import add_upload_routes

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logfire.configure(send_to_logfire="if-token-present", service_name="vis-agent", console=False)
logfire.instrument_pydantic_ai()

data_directory = Path(os.getenv("DATA_DIRECTORY", str(Path(__file__).parent.parent / "data")))
database = Path(os.environ["DUCKDB_PATH"]) if os.getenv("DUCKDB_PATH") else None

store = DatasetStore(
    data_directory,
    max_upload_bytes=int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
    database=database,
)
requests = RequestStore(store)
teams = teams_from_env(store, requests)
default = teams[0]  # profiles uploads and serves the agent channel


async def auto_profile(dataset_id: str) -> None:
    try:
        await profile_dataset(store, default.deps.profiler, dataset_id)
    except Exception:
        logging.getLogger("uploads").exception("Automatic profiling failed for %s", dataset_id)


# A model-less agent owns the page and the dropdown, which lists the teams by name; add_chat_route runs the team named.
menu: Agent[AppDeps, str] = Agent(None, name="vis-menu")
app = menu.to_web(
    models={team.label: team.lead.model for team in teams},
    html_source=Path(__file__).with_name("static") / "chat.html",
)
add_chat_route(app, teams)
add_upload_routes(app, store, auto_profile=auto_profile)
add_render_routes(app, store)
add_request_routes(app, default.deps, default.lead)
