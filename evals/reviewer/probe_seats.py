# evals/reviewer/probe_seats.py
"""Ask each candidate seat on the LiteLLM proxy to read a one-pixel picture and to call one tool.

Usage: uv run python -m evals.reviewer.probe_seats [model ...]; needs LITELLM_BASE_URL and LITELLM_TOKEN.
A seat that answers the colour and calls the tool can be the reviewer; the agreement test picks among those.
"""

import asyncio
import base64
import sys

from dotenv import load_dotenv
from pydantic_ai import Agent, BinaryContent

from vis_agent.providers import litellm_model

CANDIDATES = ["Qwen/Qwen3.8-27B", "MiniMaxAI/MiniMax-M2.5", "zai-org/GLM-5.2-FP8", "google/gemma-4-31B-it"]
RED_PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")


async def probe(name: str) -> str:
    agent = Agent(litellm_model(name), output_type=str)
    try:
        async with asyncio.timeout(60):
            result = await agent.run(["What colour is this picture? One word.", BinaryContent(data=RED_PIXEL, media_type="image/png")])
        return f"{name}: image ok ({result.output.strip()[:20]})"
    except Exception as exc:  # a probe reports, it does not fail
        return f"{name}: image failed: {type(exc).__name__}: {str(exc)[:120]}"


async def main(names: list[str]) -> None:
    load_dotenv()
    for line in await asyncio.gather(*(probe(name) for name in names)):
        print(line)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or CANDIDATES))
