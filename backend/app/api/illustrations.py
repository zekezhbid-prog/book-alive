"""The "Pictures" section: illustrations of the book, each a dialogue with the model."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import illustrations as service
from app.api.images import EXTENSIONS, _store
from app.config import settings
from app.db import SessionDep
from app.images.generate import ImageGenerationFailed, ImageModel, ImageModelNotConfigured
from app.images.styles import style_key, style_prompt
from app.llm.calls import BadModelOutput, ModelNotConfigured, TextModel
from app.models import Illustration, Image, Project

router = APIRouter(prefix="/api", tags=["illustrations"])


class Message(BaseModel):
    role: str
    text: str = ""
    prompt: str = ""
    cast: list[str] = Field(default_factory=list)
    chapter_id: str = ""
    reference_urls: list[str] = Field(default_factory=list)
    image_url: str = ""


class IllustrationBrief(BaseModel):
    id: str
    title: str
    cover: str
    created_at: datetime


class IllustrationOut(IllustrationBrief):
    messages: list[Message]


class AskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _url(image_id: str) -> str:
    return f"/api/images/{image_id}/file"


def _cover(item: Illustration) -> str:
    drawn = [m["image_id"] for m in item.messages if m.get("image_id")]
    return _url(drawn[-1]) if drawn else ""


def _brief(item: Illustration) -> IllustrationBrief:
    return IllustrationBrief(
        id=item.id, title=item.title, cover=_cover(item), created_at=item.created_at
    )


def _full(item: Illustration) -> IllustrationOut:
    return IllustrationOut(
        **_brief(item).model_dump(),
        messages=[
            Message(
                role=m["role"],
                text=m.get("text", ""),
                prompt=m.get("prompt", ""),
                cast=m.get("cast", []),
                chapter_id=m.get("chapter_id", ""),
                reference_urls=[_url(i) for i in m.get("reference_ids", [])],
                image_url=_url(m["image_id"]) if m.get("image_id") else "",
            )
            for m in item.messages
        ],
    )


def _item(session: SessionDep, illustration_id: str) -> tuple[Illustration, Project]:
    item = session.get(Illustration, illustration_id)
    if item is None:
        raise HTTPException(404, "illustration_not_found")
    return item, session.get(Project, item.project_id)


def _say(session: SessionDep, item: Illustration, message: dict) -> None:
    # A JSON list is saved only when a new list is assigned.
    item.messages = [*item.messages, message]
    session.commit()


@router.get("/projects/{project_id}/illustrations")
def list_illustrations(project_id: str, session: SessionDep) -> list[IllustrationBrief]:
    items = session.scalars(
        select(Illustration)
        .where(Illustration.project_id == project_id)
        .order_by(Illustration.created_at.desc())
    ).all()
    return [_brief(item) for item in items]


@router.post("/projects/{project_id}/illustrations")
def create_illustration(project_id: str, session: SessionDep) -> IllustrationOut:
    """Cards are only ever added by the user's own press."""
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project_not_found")
    item = Illustration(project_id=project_id, messages=[])
    session.add(item)
    session.commit()
    return _full(item)


@router.get("/illustrations/{illustration_id}")
def get_illustration(illustration_id: str, session: SessionDep) -> IllustrationOut:
    return _full(_item(session, illustration_id)[0])


@router.delete("/illustrations/{illustration_id}", status_code=204)
def delete_illustration(illustration_id: str, session: SessionDep) -> None:
    item, _ = _item(session, illustration_id)
    session.delete(item)  # its pictures stay as pictures of the project
    session.commit()


@router.post("/illustrations/{illustration_id}/ask")
def ask(illustration_id: str, body: AskRequest, session: SessionDep) -> IllustrationOut:
    """The user's words; the model answers with a question or a plan of the picture."""
    item, project = _item(session, illustration_id)
    if not item.title:
        item.title = " ".join(body.text.split())[:80]
    _say(session, item, {"role": "user", "text": body.text.strip()})
    try:
        model = TextModel(session, project.id, "prompts")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        reply = service.plan(session, model, project, item)
    except BadModelOutput as exc:
        raise HTTPException(502, f"bad_model_output: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    item = session.get(Illustration, illustration_id)
    _say(session, item, reply)
    return _full(item)


@router.post("/illustrations/{illustration_id}/draw")
def draw(illustration_id: str, session: SessionDep) -> IllustrationOut:
    """Draws the last plan with its references."""
    item, project = _item(session, illustration_id)
    last = next((m for m in reversed(item.messages) if m.get("prompt")), None)
    if last is None:
        raise HTTPException(409, "no_plan_yet")
    if not style_prompt(project):
        raise HTTPException(409, "style_not_chosen")
    try:
        model = ImageModel(session, project.id)
    except ImageModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    references = [session.get(Image, i) for i in last.get("reference_ids", [])]
    references = [r for r in references if r is not None]
    paths = [settings.files_dir / r.path for r in references]
    prompt, key = last["prompt"], style_key(project)
    try:
        result = model.generate(prompt, paths, "")
    except ImageGenerationFailed as exc:
        raise HTTPException(502, f"provider_error: {exc}") from exc
    mime = result.mime if result.mime in EXTENSIONS else "image/png"
    image_id, relative = _store(project, result.data, mime)
    item = session.get(Illustration, illustration_id)
    session.add(
        Image(
            id=image_id,
            project_id=project.id,
            illustration_id=item.id,
            origin="generated",
            style_key=key,
            prompt=prompt,
            reference_ids=[r.id for r in references],
            path=relative,
            mime=mime,
        )
    )
    _say(
        session,
        item,
        {"role": "assistant", "image_id": image_id, "reference_ids": [r.id for r in references]},
    )
    return _full(item)
