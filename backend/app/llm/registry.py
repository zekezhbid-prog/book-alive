"""The only place that knows how to reach a model. Everything else asks for a
LangChain chat model by connection and model name."""

from dataclasses import dataclass

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.crypto import decrypt
from app.models import Connection


@dataclass
class ModelInfo:
    id: str
    name: str
    free: bool | None = None  # None: the endpoint does not publish prices
    image: bool = False  # can produce images
    # What the model produces: text, image, video, other (audio and the like) or unknown
    # when the endpoint does not say. The pickers use it to offer only fitting models.
    kind: str = "unknown"


def chat_model(connection: Connection, model: str, **kwargs) -> BaseChatModel:
    return ChatOpenAI(
        model=model,
        base_url=connection.base_url.rstrip("/"),
        # Local routers accept any key, but the client requires a non-empty one.
        api_key=decrypt(connection.api_key_encrypted) or "none",
        max_retries=3,
        **kwargs,
    )


def list_models(connection: Connection) -> list[ModelInfo]:
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
    pricing = item.get("pricing")
    free: bool | None = True if model_id.endswith(":free") else None
    if isinstance(pricing, dict) and free is None:
        if isinstance(pricing.get("is_free"), bool):
            free = pricing["is_free"]
        else:
            try:
                prices = [float(pricing.get(k) or 0) for k in ("prompt", "completion", "image")]
                free = all(p == 0 for p in prices)
            except (TypeError, ValueError):
                free = None
    architecture = item.get("architecture") or {}
    outputs = item.get("output_modalities") or architecture.get("output_modalities") or []
    if "video" in outputs:
        kind = "video"
    elif "image" in outputs:
        kind = "image"
    elif outputs == ["text"]:
        kind = "text"
    elif outputs:
        kind = "other"
    else:
        kind = "unknown"
    name = item.get("display_name") or item.get("name") or model_id
    return ModelInfo(id=model_id, name=name, free=free, image="image" in outputs, kind=kind)
