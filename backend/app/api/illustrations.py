"""The "Pictures" section: illustrations of the book, each a dialogue with the model."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app import illustrations as service
from app.api.images import EXTENSIONS, _store
from app.config import settings
from app.db import SessionDep
from app.images.generate import SIZES, ImageGenerationFailed, ImageModel, ImageModelNotConfigured
from app.images.styles import style_key, style_prompt
from app.llm.calls import BadModelOutput, ModelNotConfigured, TextModel
from app.models import Chapter, Illustration, Image, Project

router = APIRouter(prefix="/api", tags=["illustrations"])


class Missing(BaseModel):
    entity_id: str
    name: str
    kind: str


class Message(BaseModel):
    role: str
    text: str = ""
    prompt: str = ""
    cast: list[str] = Field(default_factory=list)
    chapter_id: str = ""
    reference_urls: list[str] = Field(default_factory=list)
    image_url: str = ""
    # Cards of a plan with no picture to draw them from, as they are now (owner's notes 27.11).
    missing: list[Missing] = Field(default_factory=list)


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


def _full(session: SessionDep, item: Illustration) -> IllustrationOut:
    project = session.get(Project, item.project_id)
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
                # Only the last message can be a plan waiting to be drawn.
                missing=[
                    Missing(**c) for c in service.missing(project, service.cast_of(session, m))
                ]
                if m.get("prompt") and n == len(item.messages) - 1
                else [],
            )
            for n, m in enumerate(item.messages)
        ],
    )


def _item(session: SessionDep, illustration_id: str) -> tuple[Illustration, Project]:
    item = session.get(Illustration, illustration_id)
    if item is None:
        raise HTTPException(404, "illustration_not_found")
    return item, session.get(Project, item.project_id)


def _request_title(messages: list[dict]) -> str:
    """The user's words that led to the last picture, or to the coming one while nothing is
    drawn after the previous picture (owner's notes 27.11, item 15)."""
    drawn = [n for n, m in enumerate(messages) if m.get("image_id")]
    end = drawn[-1] if drawn else len(messages)
    start = next((n + 1 for n in reversed(drawn) if n < end), 0)
    words = [m.get("text", "") for m in messages[start:end] if m["role"] == "user"]
    return " ".join(", ".join(w for w in words if w.strip()).split())[:80]


def _say(session: SessionDep, item: Illustration, message: dict) -> None:
    # A JSON list is saved only when a new list is assigned.
    item.messages = [*item.messages, message]
    if not item.title_edited:
        item.title = _request_title(item.messages)
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
    return _full(session, item)


class PictureIdea(BaseModel):
    title: str
    description: str


@router.post("/projects/{project_id}/chapters/{chapter_id}/picture-ideas")
def picture_ideas(project_id: str, chapter_id: str, session: SessionDep) -> list[PictureIdea]:
    """ "Pick from the book": moments of a chapter worth a picture. A hidden chapter (the
    author's personal data) is never sent to a model."""
    chapter = session.get(Chapter, chapter_id)
    if chapter is None or chapter.project_id != project_id or chapter.private:
        raise HTTPException(404, "chapter_not_found")
    project = session.get(Project, project_id)
    try:
        model = TextModel(session, project.id, "prompts")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        ideas = service.picture_ideas(model, project, chapter)
    except BadModelOutput as exc:
        raise HTTPException(502, f"bad_model_output: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return [PictureIdea(**i) for i in ideas]


@router.get("/illustrations/{illustration_id}")
def get_illustration(illustration_id: str, session: SessionDep) -> IllustrationOut:
    return _full(session, _item(session, illustration_id)[0])


class RenameRequest(BaseModel):
    title: str = Field(max_length=300)


@router.patch("/illustrations/{illustration_id}")
def rename_illustration(
    illustration_id: str, body: RenameRequest, session: SessionDep
) -> IllustrationOut:
    """The user's own name for the card; an empty one gives the automatic name back."""
    item, _ = _item(session, illustration_id)
    title = " ".join(body.title.split())
    item.title_edited = bool(title)
    item.title = title or _request_title(item.messages)
    session.commit()
    return _full(session, item)


@router.delete("/illustrations/{illustration_id}", status_code=204)
def delete_illustration(illustration_id: str, session: SessionDep) -> None:
    item, _ = _item(session, illustration_id)
    session.delete(item)  # its pictures stay as pictures of the project
    session.commit()


@router.post("/illustrations/{illustration_id}/ask")
def ask(illustration_id: str, body: AskRequest, session: SessionDep) -> IllustrationOut:
    """The user's words; the model answers with a question or a plan of the picture."""
    item, project = _item(session, illustration_id)
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
    return _full(session, item)


class DrawIn(BaseModel):
    # A key of SIZES, chosen in the dialogue's field (owner's notes 27.11, item 30);
    # empty means square.
    size: str = ""

    @field_validator("size")
    @classmethod
    def known_size(cls, value: str) -> str:
        if value and value not in SIZES:
            raise ValueError("unknown size")
        return value


@router.post("/illustrations/{illustration_id}/draw")
def draw(illustration_id: str, session: SessionDep, body: DrawIn | None = None) -> IllustrationOut:
    """Draws the last plan with its references."""
    size = body.size if body else ""
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
    if last.get("template"):
        # The references are taken again: one made after the plan counts.
        prompt, references = service.fill(project, last["template"], service.cast_of(session, last))
        # A new list of new dicts: a JSON column is saved only when its value changes.
        item.messages = [
            {**m, "prompt": prompt, "reference_ids": [r.id for r in references]} if m is last else m
            for m in item.messages
        ]
        session.commit()
    else:
        prompt = last["prompt"]
        references = [session.get(Image, i) for i in last.get("reference_ids", [])]
        references = [r for r in references if r is not None]
    paths = [settings.files_dir / r.path for r in references]
    key = style_key(project)
    try:
        result = model.generate(prompt, paths, size)
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
    return _full(session, item)
