"""Image generation through an OpenAI-compatible endpoint.

Two request shapes exist in the wild and a router may support either:

1. chat completions with image output (OpenRouter and Gemini-style models). Reference
   pictures go in as message content, the result comes back in `message.images`.
2. the classic `/images/generations`, text prompt only.

With reference pictures only the first can work. Without them the first is tried and
the second is the fallback.
"""

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.crypto import decrypt
from app.db import release_connection
from app.llm import prefs
from app.models import Connection, UsageEvent

TIMEOUT = httpx.Timeout(300, connect=20)

# Picture shapes offered in the UI. Chat-style image models take an aspect ratio, the
# classic endpoint a size in pixels; empty means the model's own default.
SIZES = {
    "1:1": "1024x1024",
    "2:3": "1024x1536",
    "3:2": "1536x1024",
    "9:16": "1024x1792",
    "16:9": "1792x1024",
}


class ImageModelNotConfigured(RuntimeError):
    pass


class ImageGenerationFailed(RuntimeError):
    pass


@dataclass
class GeneratedImage:
    data: bytes
    mime: str


class ImageModel:
    """The image model chosen in Settings."""

    def __init__(
        self, session: Session, project_id: str, transport: httpx.BaseTransport | None = None
    ):
        connection_id = prefs.for_project(session, project_id, "image_connection_id")
        model_name = prefs.for_project(session, project_id, "image_model")
        connection = session.get(Connection, connection_id) if connection_id else None
        if connection is None or not model_name:
            raise ImageModelNotConfigured("image_model_not_configured")
        self.session = session
        self.engine = session.get_bind()
        self.project_id = project_id
        self.connection_name = connection.name
        self.model_name = model_name
        key = decrypt(connection.api_key_encrypted)
        self.client = httpx.Client(
            base_url=connection.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {key}"} if key else {},
            timeout=TIMEOUT,
            transport=transport,
        )

    def generate(
        self, prompt: str, references: list[Path] | None = None, size: str = ""
    ) -> GeneratedImage:
        references = references or []
        if size and size not in SIZES:
            raise ValueError(f"unknown size {size!r}")
        release_connection(self.session)  # a picture can take minutes
        try:
            image, usage = self._via_chat(prompt, references, size)
            if image is None and not references:
                image, usage = self._via_images(prompt, size)
        except httpx.HTTPError as exc:
            raise ImageGenerationFailed(str(exc)[:300]) from exc
        if image is None:
            raise ImageGenerationFailed("the model returned no image")
        with Session(self.engine) as journal:
            journal.add(
                UsageEvent(
                    project_id=self.project_id,
                    operation="image",
                    connection_name=self.connection_name,
                    model=self.model_name,
                    input_tokens=usage.get("prompt_tokens", 0) or 0,
                    output_tokens=usage.get("completion_tokens", 0) or 0,
                )
            )
            journal.commit()
        return image

    def _via_chat(
        self, prompt: str, references: list[Path], size: str
    ) -> tuple[GeneratedImage | None, dict]:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for path in references:
            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            encoded = base64.b64encode(path.read_bytes()).decode()
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
            )
        body: dict = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["image", "text"],
        }
        if size:
            body["image_config"] = {"aspect_ratio": size}
        response = self.client.post("/chat/completions", json=body)
        if response.status_code >= 400:
            if references:
                raise ImageGenerationFailed(f"HTTP {response.status_code}: {response.text[:200]}")
            return None, {}  # this endpoint may only speak /images/generations
        payload = response.json()
        message = (payload.get("choices") or [{}])[0].get("message") or {}
        for item in message.get("images") or []:
            url = (item.get("image_url") or {}).get("url", "")
            if url:
                return self._from_url(url), payload.get("usage") or {}
        return None, payload.get("usage") or {}

    def _via_images(self, prompt: str, size: str) -> tuple[GeneratedImage | None, dict]:
        body: dict = {"model": self.model_name, "prompt": prompt, "n": 1}
        if size:
            body["size"] = SIZES[size]
        response = self.client.post("/images/generations", json=body)
        if response.status_code >= 400:
            raise ImageGenerationFailed(f"HTTP {response.status_code}: {response.text[:200]}")
        payload = response.json()
        item = (payload.get("data") or [{}])[0]
        if item.get("b64_json"):
            return GeneratedImage(base64.b64decode(item["b64_json"]), "image/png"), {}
        if item.get("url"):
            return self._from_url(item["url"]), {}
        return None, {}

    def _from_url(self, url: str) -> GeneratedImage:
        if url.startswith("data:"):
            header, _, encoded = url.partition(",")
            mime = header[5:].split(";")[0] or "image/png"
            return GeneratedImage(base64.b64decode(encoded), mime)
        # A hosted result: fetched without our Authorization header.
        fetched = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
        fetched.raise_for_status()
        return GeneratedImage(fetched.content, fetched.headers.get("content-type", "image/png"))
