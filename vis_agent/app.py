"""Environment wiring only. Everything else lives in the modules it names."""

import logging
import os
from pathlib import Path

import logfire
from dotenv import load_dotenv

from vis_agent.analyst.agent import DEFAULT_ANALYST_MODEL, create_analyst
from vis_agent.designer.agent import DEFAULT_DESIGNER_MODEL, DEFAULT_FALLBACK_DESIGNER_MODEL, create_designer
from vis_agent.store import DatasetStore
from vis_agent.lead import create_lead
from vis_agent.deps import AppDeps
from vis_agent.profiler.agent import DEFAULT_PROFILER_MODEL, create_profiler, profile_dataset
from vis_agent.uploads import add_upload_routes
from vis_agent.renders import add_render_routes
from vis_agent.requests.api import add_request_routes
from vis_agent.requests.store import RequestStore

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logfire.configure(send_to_logfire="if-token-present", service_name="vis-agent", console=False)
logfire.instrument_pydantic_ai()

model = os.getenv("PYDANTIC_AI_MODEL") or DEFAULT_PROFILER_MODEL  # the lead on the specialists' model, measured 2026-09-09
data_directory = Path(os.getenv("DATA_DIRECTORY", str(Path(__file__).parent.parent / "data")))
database = Path(os.environ["DUCKDB_PATH"]) if os.getenv("DUCKDB_PATH") else None

store = DatasetStore(
    data_directory,
    max_upload_bytes=int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
    database=database,
)
requests = RequestStore(store)
profiler = create_profiler(os.getenv("PYDANTIC_AI_PROFILER_MODEL") or DEFAULT_PROFILER_MODEL)
analyst = create_analyst(os.getenv("PYDANTIC_AI_ANALYST_MODEL") or DEFAULT_ANALYST_MODEL)
designer = create_designer(os.getenv("PYDANTIC_AI_DESIGNER_MODEL") or DEFAULT_DESIGNER_MODEL)
designer_fallback = create_designer(os.getenv("PYDANTIC_AI_DESIGNER_FALLBACK_MODEL") or DEFAULT_FALLBACK_DESIGNER_MODEL)
deps = AppDeps(store=store, profiler=profiler, analyst=analyst, designer=designer, requests=requests,
               designer_fallback=designer_fallback)
agent = create_lead(model, advisor_model=os.getenv("PYDANTIC_AI_ADVISOR_MODEL", "openrouter:openai/gpt-5.6-sol"))


async def auto_profile(dataset_id: str) -> None:
    try:
        await profile_dataset(store, profiler, dataset_id)
    except Exception:
        logging.getLogger("uploads").exception("Automatic profiling failed for %s", dataset_id)


app = agent.to_web(deps=deps, html_source=Path(__file__).with_name("static") / "chat.html")
add_upload_routes(app, store, auto_profile=auto_profile)
add_render_routes(app, store)
add_request_routes(app, deps, agent)
