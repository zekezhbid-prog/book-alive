import httpx
from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import KeyUnreadable, decrypt, encrypt, mask
from app.db import SessionDep
from app.llm import prefs, registry
from app.models import KIND_OPENAI, AppSetting, Connection

router = APIRouter(prefix="/api", tags=["connections"])

# Which connection and model each kind of work uses.
SETTING_KEYS = prefs.NAMES


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
    kind: str


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
    # Chosen now, used once video generation exists.
    video_connection_id: str = ""
    video_model: str = ""


def _hint(connection: Connection) -> str:
    try:
        return mask(decrypt(connection.api_key_encrypted))
    except KeyUnreadable:
        return "?"


def _out(connection: Connection) -> ConnectionOut:
    return ConnectionOut(
        id=connection.id,
        name=connection.name,
        kind=connection.kind,
        base_url=connection.base_url,
        api_key_hint=_hint(connection),
    )


def _connection(session: Session, connection_id: str) -> Connection:
    connection = session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(404, "connection_not_found")
    return connection


def _validate(kind: str, base_url: str) -> None:
    if kind != KIND_OPENAI:
        raise HTTPException(422, "bad_connection_kind")
    if not base_url.strip().startswith(("http://", "https://")):
        raise HTTPException(422, "bad_base_url")


@router.get("/connections")
def list_connections(request: Request, session: SessionDep) -> list[ConnectionOut]:
    rows = session.scalars(select(Connection).order_by(Connection.created_at)).all()
    out = [_out(c) for c in rows]
    if not request.state.is_admin:  # others only pick from the list: no address, no key hint
        for item in out:
            item.base_url = ""
            item.api_key_hint = ""
    return out


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
    # The shared choice and every person's own one that pointed at it.
    for row in session.scalars(select(AppSetting).where(AppSetting.value == connection.id)).all():
        if not row.key.endswith("_connection_id"):
            continue
        row.value = ""
        model = session.get(AppSetting, row.key.removesuffix("_connection_id") + "_model")
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
    except KeyUnreadable as exc:
        raise HTTPException(409, str(exc)) from exc
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
    except KeyUnreadable as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    usage = answer.usage_metadata or {}
    return TestResult(
        reply=str(answer.content)[:200],
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )


@router.get("/settings")
def get_settings(request: Request, session: SessionDep) -> SettingsBody:
    """The caller's own choice of models, with the shared default where they chose nothing."""
    user_id = request.state.user_id
    return SettingsBody(**{key: prefs.value(session, user_id, key) or "" for key in SETTING_KEYS})


@router.put("/settings")
def put_settings(body: SettingsBody, request: Request, session: SessionDep) -> SettingsBody:
    """Everyone picks their own models; without accounts there is one shared choice."""
    user_id = request.state.user_id
    for key in SETTING_KEYS:
        name = prefs.personal_key(user_id, key) if user_id else key
        session.merge(AppSetting(key=name, value=getattr(body, key)))
    session.commit()
    return body
