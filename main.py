"""Environment wiring only. Everything else lives in the modules it names."""

import logging
import os
from pathlib import Path

import logfire
from dotenv import load_dotenv

from dataset_store import DatasetStore
from lead import create_lead
from profiler import AppDeps, create_profiler, profile_dataset
from uploads import add_upload_routes

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logfire.configure(send_to_logfire="if-token-present", service_name="vis-agent", console=False)
logfire.instrument_pydantic_ai()

model = os.getenv("PYDANTIC_AI_MODEL", "openrouter:anthropic/claude-sonnet-4.6")
data_directory = Path(os.getenv("DATA_DIRECTORY", str(Path(__file__).parent / "data")))
database = Path(os.environ["DUCKDB_PATH"]) if os.getenv("DUCKDB_PATH") else None

store = DatasetStore(
    data_directory,
    max_upload_bytes=int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
    database=database,
)
profiler = create_profiler(os.getenv("PYDANTIC_AI_PROFILER_MODEL") or model)
deps = AppDeps(store=store, profiler=profiler)
agent = create_lead(model, advisor_model=os.getenv("PYDANTIC_AI_ADVISOR_MODEL", "openrouter:openai/gpt-5.6-sol"))


async def auto_profile(dataset_id: str) -> None:
    try:
        await profile_dataset(store, profiler, dataset_id)
    except Exception:
        logging.getLogger("uploads").exception("Automatic profiling failed for %s", dataset_id)


app = agent.to_web(deps=deps, html_source=Path(__file__).with_name("chat.html"))
add_upload_routes(app, store, auto_profile=auto_profile)
