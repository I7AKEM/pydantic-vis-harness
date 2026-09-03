import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.durable_exec.temporal import TemporalDurability
from pydantic_ai_harness import Advisor, CodeMode

from dataset_store import DatasetStore
from profiler import AppDeps, create_semantic_profiler, profile_csv
from uploads import add_upload_routes

load_dotenv()

model = os.getenv(
    "PYDANTIC_AI_MODEL",
    "openrouter:anthropic/claude-sonnet-4.6",
)

store = DatasetStore(
    Path(os.getenv("DATA_DIRECTORY", str(Path(__file__).parent / "data"))),
    max_upload_bytes=int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
)
deps = AppDeps(
    store=store,
    semantic_profiler=create_semantic_profiler(os.getenv("PYDANTIC_AI_PROFILER_MODEL") or model),
)

agent = Agent(
    model,
    name="visualization-agent",
    deps_type=AppDeps,
    instructions="""
    You are a helpful visualization assistant with CSV profiling support.
    To upload a CSV, direct the user to [Upload CSV](/datasets/upload).
    When the user supplies an uploaded file ID, call profile_csv directly.
    It imports the CSV into DuckDB, computes statistics, and runs semantic profiling.
    Use its structured result to answer. Keep measured statistics and uncertain
    semantic interpretations distinct. Never invent data or claim charts exist.
    If the profile is partial, explain that semantic profiling can be retried.
    Link the saved JSON at /datasets/{dataset_id}/profile using the returned source ID.
    """,
    capabilities=[
        CodeMode(tools=lambda ctx, tool: tool.name != "profile_csv"),
        Advisor(
            "openrouter:openai/gpt-5.6-sol",
            mode="native",
        ),
        TemporalDurability(),
    ],
)

agent.tool(profile_csv, sequential=True)

app = agent.to_web(deps=deps)
add_upload_routes(app, store)
