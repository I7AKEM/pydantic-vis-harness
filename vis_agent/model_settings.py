"""Model settings shared by text specialists."""

from pydantic_ai.models import Model


def text_specialist_settings(model: str | Model) -> dict:
    """Let reasoning-only GLM models think; keep deterministic non-reasoning seats terse."""
    name = model if isinstance(model, str) else model.model_name
    if "z-ai/glm-5.3" in name:
        return {
            "openrouter_reasoning": {"effort": "low"},
            "openrouter_provider": {"require_parameters": True},
            "temperature": 0.0,
        }
    return {"thinking": False, "temperature": 0.0}
