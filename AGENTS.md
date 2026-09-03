# Minimal Pydantic AI Setup

Set up only the basic foundation for a future visualization agent.

## Goal

Create one small local Pydantic AI chat agent with:

- OpenRouter as the model provider
- `pydantic-ai-harness` installed and ready
- Temporal durability support installed
- `TemporalDurability()` attached to the agent
- Pydantic AI's built-in Web Chat UI

Do not design the visualization system yet.

## Strict scope

Do **not** add any of the following now:

- CSV upload
- visualization or chart rendering
- tools
- planner
- profiler
- reviewer
- orchestrator
- subagents
- Temporal workflow or worker
- database
- Docker
- React or a custom frontend
- custom FastAPI routes

The result should be a basic agent that opens in the browser and responds through OpenRouter.

## Project setup

Use Python 3.12 and `uv`.

```bash
uv init --python 3.12
uv add \
  pydantic-ai-harness \
  "pydantic-ai-slim[openrouter,web,temporal]" \
  python-dotenv
```

Do not install the full `pydantic-ai` package in addition to the slim package.

## Required files

Create only these files:

```text
.
├── main.py
├── .env.example
├── .gitignore
└── README.md
```

Keep the files at the project root for now.

## `.env.example`

```env
OPENROUTER_API_KEY=replace-me
PYDANTIC_AI_MODEL=openrouter:anthropic/claude-sonnet-4.6
```

The model must be configurable through `PYDANTIC_AI_MODEL`; do not hard-code one model as the only option.

## `.gitignore`

```gitignore
.venv/
.env
__pycache__/
*.pyc
```

## `main.py`

Implement exactly one agent and expose the built-in Pydantic AI Web Chat UI.

```python
import os

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.durable_exec.temporal import TemporalDurability

load_dotenv()

model = os.getenv(
    "PYDANTIC_AI_MODEL",
    "openrouter:anthropic/claude-sonnet-4.6",
)

agent = Agent(
    model,
    name="visualization-agent",
    instructions=(
        "You are the initial foundation for a future visualization agent. "
        "For now, behave as a helpful assistant. Do not claim that CSV, "
        "visualization, workflow, or subagent features exist yet."
    ),
    capabilities=[TemporalDurability()],
)

app = agent.to_web()
```

Do not add a generic `Harness()` object. Pydantic AI Harness is a library of individual capabilities; it is installed now so its capabilities can be selected later during the design phase.

## `README.md`

Include only:

1. Installation instructions.
2. How to copy `.env.example` to `.env` and set the OpenRouter key.
3. How to run the UI:

```bash
uv run uvicorn main:app --host 127.0.0.1 --port 7932 --reload
```

4. Open the browser at:

```text
http://127.0.0.1:7932
```

5. This exact durability clarification:

> Temporal support is installed and `TemporalDurability()` is attached. At this stage, Web Chat calls the agent normally, so runs are not yet durable. True durable execution starts when the agent is called inside a Temporal workflow and worker, which is intentionally deferred to the next design phase.

## Validation

After implementation:

1. Run the app locally.
2. Confirm the Web Chat UI loads.
3. Confirm a basic message receives an OpenRouter response.
4. Confirm there are no workflow, subagent, CSV, or visualization files.
5. Stop after this basic setup. Do not begin designing the visualization agent.
