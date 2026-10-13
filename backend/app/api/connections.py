import httpx
from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import decrypt, encrypt, mask
from app.db import SessionDep
from app.llm import registry
from app.llm.claude_cli import cli_path
from app.models import KIND_CLAUDE_CLI, KIND_OPENAI, AppSetting, Connection

router = APIRouter(prefix="/api", tags=["connections"])

# Which connection and model each kind of work uses.
SETTING_KEYS = ("text_connection_id", "text_model", "image_connection_id", "image_model")


class ConnectionOut(BaseModel):
    id: str
    name: str
    kind: str
    base_url: str
    api_key_hint: str  # never the key itself


class ConnectionIn(BaseModel):
    name: str
    kind: str = KIND_OPENAI
    base_url: str = ""
    api_key: str = ""


class ConnectionPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # None keeps the stored key


class ModelOut(BaseModel):
    id: str
    name: str
    free: bool | None
    image: bool


class TestRequest(BaseModel):
    model: str


class TestResult(BaseModel):
    reply: str
    input_tokens: int
    output_tokens: int


class SettingsBody(BaseModel):
    text_connection_id: str = ""
    text_model: str = ""
    image_connection_id: str = ""
    image_model: str = ""


class SystemInfo(BaseModel):
    claude_cli: bool


def _out(connection: Connection) -> ConnectionOut:
    return ConnectionOut(
        id=connection.id,
        name=connection.name,
        kind=connection.kind,
        base_url=connection.base_url,
        api_key_hint=mask(decrypt(connection.api_key_encrypted)),
    )


def _connection(session: Session, connection_id: str) -> Connection:
    connection = session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(404, "connection_not_found")
    return connection


def _validate(kind: str, base_url: str) -> None:
    if kind not in (KIND_OPENAI, KIND_CLAUDE_CLI):
        raise HTTPException(422, "bad_connection_kind")
    if kind == KIND_OPENAI and not base_url.strip().startswith(("http://", "https://")):
        raise HTTPException(422, "bad_base_url")


@router.get("/system")
def system_info() -> SystemInfo:
    return SystemInfo(claude_cli=cli_path() is not None)


@router.get("/connections")
def list_connections(session: SessionDep) -> list[ConnectionOut]:
    rows = session.scalars(select(Connection).order_by(Connection.created_at)).all()
    return [_out(c) for c in rows]


@router.post("/connections")
def create_connection(body: ConnectionIn, session: SessionDep) -> ConnectionOut:
    _validate(body.kind, body.base_url)
    connection = Connection(
        name=body.name.strip() or body.base_url,
        kind=body.kind,
        base_url=body.base_url.strip(),
        api_key_encrypted=encrypt(body.api_key.strip()),
    )
    session.add(connection)
    session.commit()
    return _out(connection)


@router.patch("/connections/{connection_id}")
def update_connection(
    connection_id: str, patch: ConnectionPatch, session: SessionDep
) -> ConnectionOut:
    connection = _connection(session, connection_id)
    if patch.name is not None and patch.name.strip():
        connection.name = patch.name.strip()
    if patch.base_url is not None:
        _validate(connection.kind, patch.base_url)
        connection.base_url = patch.base_url.strip()
    if patch.api_key is not None:
        connection.api_key_encrypted = encrypt(patch.api_key.strip())
    session.commit()
    return _out(connection)


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: str, session: SessionDep) -> None:
    connection = _connection(session, connection_id)
    for prefix in ("text", "image"):
        chosen = session.get(AppSetting, f"{prefix}_connection_id")
        if chosen is not None and chosen.value == connection.id:
            chosen.value = ""
            model = session.get(AppSetting, f"{prefix}_model")
            if model is not None:
                model.value = ""
    session.delete(connection)
    session.commit()


@router.get("/connections/{connection_id}/models")
def connection_models(connection_id: str, session: SessionDep) -> list[ModelOut]:
    connection = _connection(session, connection_id)
    try:
        models = registry.list_models(connection)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"provider_error: HTTP {exc.response.status_code}") from exc
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise HTTPException(502, f"provider_error: {exc}") from exc
    return [ModelOut(**vars(m)) for m in models]


@router.post("/connections/{connection_id}/test")
def test_connection(connection_id: str, body: TestRequest, session: SessionDep) -> TestResult:
    """One tiny real request, so the user knows the key and the model work."""
    connection = _connection(session, connection_id)
    try:
        llm = registry.chat_model(connection, body.model)
        answer = llm.invoke([HumanMessage("Reply with the single word: ready")])
    except Exception as exc:  # provider SDKs raise many unrelated types
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    usage = answer.usage_metadata or {}
    return TestResult(
        reply=str(answer.content)[:200],
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )


@router.get("/settings")
def get_settings(session: SessionDep) -> SettingsBody:
    rows = {s.key: s.value for s in session.scalars(select(AppSetting)).all()}
    return SettingsBody(**{key: rows.get(key, "") for key in SETTING_KEYS})


@router.put("/settings")
def put_settings(body: SettingsBody, session: SessionDep) -> SettingsBody:
    for key in SETTING_KEYS:
        session.merge(AppSetting(key=key, value=getattr(body, key)))
    session.commit()
    return body
