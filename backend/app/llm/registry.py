"""The only place that knows how to reach a model. Everything else asks for a
LangChain chat model by connection and model name."""

from dataclasses import dataclass

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.crypto import decrypt
from app.llm.claude_cli import CLI_MODELS, ChatClaudeCLI, cli_path
from app.models import KIND_CLAUDE_CLI, Connection


@dataclass
class ModelInfo:
    id: str
    name: str
    free: bool | None = None  # None: the endpoint does not publish prices
    image: bool = False  # can produce images


def chat_model(connection: Connection, model: str, **kwargs) -> BaseChatModel:
    if connection.kind == KIND_CLAUDE_CLI:
        return ChatClaudeCLI(model=model)
    return ChatOpenAI(
        model=model,
        base_url=connection.base_url.rstrip("/"),
        # Local routers accept any key, but the client requires a non-empty one.
        api_key=decrypt(connection.api_key_encrypted) or "none",
        max_retries=3,
        **kwargs,
    )


def list_models(connection: Connection) -> list[ModelInfo]:
    if connection.kind == KIND_CLAUDE_CLI:
        if not cli_path():
            raise RuntimeError("Claude Code CLI is not installed on this machine")
        return [ModelInfo(id=m, name=f"Claude {m.capitalize()}", free=True) for m in CLI_MODELS]
    key = decrypt(connection.api_key_encrypted)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    response = httpx.get(f"{connection.base_url.rstrip('/')}/models", headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    items = payload.get("data", payload) if isinstance(payload, dict) else payload
    models = [_model_info(item) for item in items if isinstance(item, dict) and item.get("id")]
    return sorted(models, key=lambda m: m.id)


def _model_info(item: dict) -> ModelInfo:
    model_id = item["id"]
    free: bool | None = True if model_id.endswith(":free") else None
    pricing = item.get("pricing")
    if isinstance(pricing, dict) and free is None:
        try:
            free = all(float(pricing.get(k) or 0) == 0 for k in ("prompt", "completion", "image"))
        except (TypeError, ValueError):
            free = None
    architecture = item.get("architecture") or {}
    outputs = architecture.get("output_modalities") or item.get("output_modalities") or []
    return ModelInfo(
        id=model_id, name=item.get("name") or model_id, free=free, image="image" in outputs
    )
