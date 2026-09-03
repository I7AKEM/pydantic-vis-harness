import os

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.durable_exec.temporal import TemporalDurability
from pydantic_ai_harness import Advisor, CodeMode

load_dotenv()

model = os.getenv(
    "PYDANTIC_AI_MODEL",
    "openrouter:anthropic/claude-sonnet-4.6",
)

agent = Agent(
    model,
    name="visualization-agent",
    instructions="""
    You are the foundation for a future visualization agent.
    You can inspect problems, reason about them, and use code when useful.
    """,
    capabilities=[
        CodeMode(),
        Advisor(
            "openrouter:openai/gpt-5.6-sol",
            mode="native",
        ),
        TemporalDurability(),
    ],
)

app = agent.to_web()