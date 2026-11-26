import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.analysis.entities import merge_by_hand, norm
from app.config import settings
from app.db import SessionDep
from app.images import angles
from app.images.generate import (
    SIZES,
    ImageGenerationFailed,
    ImageModel,
    ImageModelNotConfigured,
)
from app.images.prompts import (
    LANGUAGES,
    build_image_prompt,
    chapters_between,
    find_variants,
    refine_image_prompt,
    translate_prompt,
)
from app.images.reference_sort import SortResult, ask_model, decide
from app.images.style_check import StyleVerdict, check_style
from app.images.styles import CUSTOM, PRESETS, style_key, style_prompt
from app.llm.calls import ModelNotConfigured, TextModel
from app.models import (
    FACT_PERMANENT,
    FACT_PROFILE,
    KIND_CHARACTER,
    KIND_ITEM,
    KIND_LOCATION,
    Chapter,
    Entity,
    Image,
    Project,
    new_id,
)

router = APIRouter(prefix="/api", tags=["images"])

MAX_IMAGE_BYTES = 25 * 1024 * 1024
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class StyleOut(BaseModel):
    id: str
    prompt: str


class StyleBody(BaseModel):
    style_id: str
    style_text: str = Field(default="", max_length=1000)


class ImageOut(BaseModel):
    id: str
    entity_id: str | None
    origin: str
    style_key: str
    # Offered as a reference only while it matches the project's current style.
    current_style: bool
    is_main: bool
    angle: str
    variant: str = ""
    look_label: str
    chapter_from_id: str
    chapter_to_id: str
    prompt: str
    # What a generated picture was drawn from (ids of pictures, some may be deleted since).
    reference_ids: list[str] = Field(default_factory=list)
    url: str
    created_at: datetime


class ImagePatch(BaseModel):
    is_main: bool | None = None
    angle: str | None = None
    variant: str | None = Field(default=None, max_length=40)
    look_label: str | None = Field(default=None, max_length=200)
    chapter_from_id: str | None = None
    chapter_to_id: str | None = None


class LookRequest(BaseModel):
    """Empty label and chapters: a main picture, in the given view (empty: the service
    picks one still missing). Otherwise a look for part of the story."""

    angle: str = ""
    look_label: str = Field(default="", max_length=200)
    chapter_from_id: str = ""
    chapter_to_id: str = ""
    # A character's outward look (`Entity.variants` key) the base picture is drawn for.
    variant: str = Field(default="", max_length=40)
    # The user's own samples ("make it look like this"): pictures of the project, sent to
    # the image model first; the card's main pictures fill the remaining places.
    reference_ids: list[str] = Field(default_factory=list, max_length=angles.DRAWING_LIMIT)


class PromptRequest(LookRequest):
    # A prompt for a set of base pictures: the appearance only, no view.
    view_free: bool = False
    # The user's wish for this one picture of a place or object ("a view from above").
    note: str = Field(default="", max_length=1000)


class GenerateRequest(LookRequest):
    prompt: str = Field(min_length=1, max_length=4000)
    # One picture of a base set: the view's own framing goes in front of the shared prompt.
    add_view: bool = False
    # A key of SIZES; empty leaves the shape to the model.
    size: str = ""

    @field_validator("size")
    @classmethod
    def known_size(cls, value: str) -> str:
        if value and value not in SIZES:
            raise ValueError("unknown size")
        return value


class PromptOut(BaseModel):
    prompt: str
    # The view the prompt was written for; send it back with the prompt to draw it.
    angle: str


class EntityCreate(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=200)


def _project(session: SessionDep, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project_not_found")
    return project


def _entity(session: SessionDep, entity_id: str) -> Entity:
    entity = session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(404, "entity_not_found")
    return entity


def _image(session: SessionDep, image_id: str) -> Image:
    image = session.get(Image, image_id)
    if image is None:
        raise HTTPException(404, "image_not_found")
    return image


def _file_url(image: Image) -> str:
    # A picture drawn again keeps its id but gets a new file: the name in the link makes the
    # browser fetch it instead of showing the old one from its cache.
    stem = PurePath(image.path).stem
    suffix = "" if stem == image.id else f"?v={stem[:12]}"
    return f"/api/images/{image.id}/file{suffix}"


def _out(image: Image, project: Project) -> ImageOut:
    return ImageOut(
        id=image.id,
        entity_id=image.entity_id,
        origin=image.origin,
        style_key=image.style_key,
        current_style=image.style_key == style_key(project),
        is_main=image.is_main,
        angle=image.angle,
        variant=image.variant or "",
        look_label=image.look_label,
        chapter_from_id=image.chapter_from_id,
        chapter_to_id=image.chapter_to_id,
        prompt=image.prompt,
        reference_ids=list(image.reference_ids or []),
        url=_file_url(image),
        created_at=image.created_at,
    )


def _store(project: Project, data: bytes, mime: str) -> tuple[str, str]:
    """Write the bytes under the project's folder. Returns (image id, relative path)."""
    image_id = new_id()
    relative = PurePath(project.id, "images", image_id + EXTENSIONS[mime]).as_posix()
    target = settings.files_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return image_id, relative


def _has_main(entity: Entity, key: str) -> bool:
    return bool(angles.mains(entity.images, key))


# ---------- style ----------


@router.get("/styles")
def styles() -> list[StyleOut]:
    return [StyleOut(id=key, prompt=prompt) for key, prompt in PRESETS.items()]


@router.put("/projects/{project_id}/style")
def set_style(project_id: str, body: StyleBody, session: SessionDep) -> StyleBody:
    project = _project(session, project_id)
    if body.style_id not in (*PRESETS, CUSTOM, ""):
        raise HTTPException(422, "bad_style")
    if body.style_id == CUSTOM and not body.style_text.strip():
        raise HTTPException(422, "style_text_required")
    # Existing pictures keep their own label: after a change they stop being offered
    # as references until pictures in the new style are made.
    first_choice = not project.style_id
    project.style_id = body.style_id
    project.style_text = body.style_text.strip() if body.style_id == CUSTOM else ""
    if first_choice:
        # Pictures uploaded before any style existed are the user's own references:
        # they belong to the first style chosen instead of turning into "other style".
        for image in session.scalars(
            select(Image).where(Image.project_id == project.id, Image.style_key == "")
        ):
            image.style_key = style_key(project)
    session.commit()
    return StyleBody(style_id=project.style_id, style_text=project.style_text)


# ---------- galleries ----------


@router.get("/projects/{project_id}/images")
def list_images(project_id: str, session: SessionDep, entity_id: str = "") -> list[ImageOut]:
    """Pictures of one card, or the project's general references when no card is given."""
    project = _project(session, project_id)
    query = select(Image).where(Image.project_id == project_id).order_by(Image.created_at)
    if entity_id:
        query = query.where(Image.entity_id == entity_id)
    else:
        query = query.where(Image.entity_id.is_(None), Image.scene_id.is_(None))
    return [_out(image, project) for image in session.scalars(query)]


@router.post("/projects/{project_id}/images")
def upload_images(
    project_id: str,
    session: SessionDep,
    files: list[UploadFile],
    entity_id: Annotated[str, Form()] = "",
) -> list[ImageOut]:
    project = _project(session, project_id)
    entity = _entity(session, entity_id) if entity_id else None
    if entity is not None and entity.project_id != project.id:
        raise HTTPException(422, "bad_entity")
    key = style_key(project)
    created = []
    for file in files:
        data = file.file.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "file_too_large")
        mime = _sniff(data)
        if mime is None:
            raise HTTPException(422, "not_an_image")
        image_id, relative = _store(project, data, mime)
        image = Image(
            id=image_id,
            project_id=project.id,
            entity_id=entity.id if entity else None,
            origin="upload",
            # An upload is taken to be in the style the project has now.
            style_key=key,
            is_main=entity is not None and not _has_main(entity, key) and not created,
            filename=PurePath(file.filename or "image").name[:300],
            path=relative,
            mime=mime,
        )
        session.add(image)
        created.append(image)
    session.commit()
    return [_out(image, project) for image in created]


@router.post("/projects/{project_id}/style-check")
def style_check(project_id: str, session: SessionDep, file: UploadFile) -> StyleVerdict:
    """Before a picture is put in as it is: the text model looks at it and says whether it is
    in the project style. Without a chosen style there is nothing to compare with."""
    project = _project(session, project_id)
    style = style_prompt(project)
    if not style:
        return StyleVerdict(matches=True)
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "file_too_large")
    mime = _sniff(data)
    if mime is None:
        raise HTTPException(422, "not_an_image")
    try:
        model = TextModel(session, project.id, "prompts")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        return check_style(model, style, data, mime)
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc


MAX_SORTED = 6


@router.post("/entities/{entity_id}/references/sort")
def sort_references(entity_id: str, session: SessionDep, files: list[UploadFile]) -> SortResult:
    """Before a character's set is drawn from the user's own pictures: the text model looks
    at all of them at once. Nothing is stored here; the browser puts the placed ones in and
    sends the rest as references."""
    entity = _entity(session, entity_id)
    project = _project(session, entity.project_id)
    if not 1 <= len(files) <= MAX_SORTED:
        raise HTTPException(422, "too_many_references")
    pictures = []
    for file in files:
        data = file.file.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "file_too_large")
        mime = _sniff(data)
        if mime is None:
            raise HTTPException(422, "not_an_image")
        pictures.append((data, mime))
    taken = {image.angle for image in angles.mains(entity.images, style_key(project))}
    character = entity.name
    try:
        model = TextModel(session, project.id, "prompts")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        verdict = ask_model(model, style_prompt(project), pictures, character)
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return decide(verdict, len(pictures), taken)


def _sniff(data: bytes) -> str | None:
    """The type by content, not by the name the browser sent."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("/images/{image_id}/file")
def image_file(image_id: str, session: SessionDep) -> FileResponse:
    image = _image(session, image_id)
    path = (settings.files_dir / image.path).resolve()
    if not path.is_relative_to(settings.files_dir.resolve()) or not path.is_file():
        raise HTTPException(404, "image_not_found")
    # Files never change once written, so the browser may keep them.
    return FileResponse(path, media_type=image.mime, headers={"Cache-Control": "max-age=31536000"})


@router.patch("/images/{image_id}")
def update_image(image_id: str, patch: ImagePatch, session: SessionDep) -> ImageOut:
    image = _image(session, image_id)
    project = _project(session, image.project_id)
    if patch.is_main is not None:
        # A card may have any number of main pictures: each one shows another view.
        image.is_main = patch.is_main and image.entity_id is not None
    if patch.angle is not None:
        if patch.angle not in ("", *angles.ANGLES):
            raise HTTPException(422, "bad_angle")
        image.angle = patch.angle
    if patch.variant is not None:
        image.variant = patch.variant
    if patch.look_label is not None:
        image.look_label = patch.look_label.strip()
    if patch.chapter_from_id is not None:
        image.chapter_from_id = patch.chapter_from_id
    if patch.chapter_to_id is not None:
        image.chapter_to_id = patch.chapter_to_id
    session.commit()
    return _out(image, project)


@router.delete("/images/{image_id}", status_code=204)
def delete_image(image_id: str, session: SessionDep) -> None:
    """Only ever on the user's request: nothing in the app removes pictures by itself."""
    image = _image(session, image_id)
    path = (settings.files_dir / image.path).resolve()
    session.delete(image)
    session.commit()
    if path.is_relative_to(settings.files_dir.resolve()):
        path.unlink(missing_ok=True)


# ---------- generation ----------


@dataclass
class Drawing:
    project: Project
    chapters: list[Chapter] | None  # None: a main picture
    angle: str
    references: list[Image]
    # The outward look a base picture is drawn for; None: the card has one look.
    variant: dict | None = None


def _drawing(session: SessionDep, entity: Entity, body: LookRequest) -> Drawing:
    project = _project(session, entity.project_id)
    key = style_key(project)
    is_look = bool(body.look_label or body.chapter_from_id or body.chapter_to_id)
    chapters = (
        chapters_between(project, body.chapter_from_id, body.chapter_to_id) if is_look else None
    )
    variant = None
    if body.variant and not is_look:
        variant = next((v for v in entity.variants or [] if v.get("key") == body.variant), None)
        if variant is None:
            raise HTTPException(404, "variant_not_found")
    # Each look is a set of its own: views and references come from its pictures only.
    own = [i for i in entity.images if (i.variant or "") == (body.variant if not is_look else "")]
    angle = ""
    if not is_look and entity.kind == KIND_CHARACTER:
        if body.angle and body.angle not in angles.ANGLES:
            raise HTTPException(422, "bad_angle")
        angle = body.angle or angles.next_angle(own if variant else entity.images, key)
    # Every new picture is drawn from the main ones, so the face stays the same;
    # the very first main picture starts from nothing. The user's samples go first.
    samples = [session.get(Image, image_id) for image_id in dict.fromkeys(body.reference_ids)]
    if any(image is None or image.project_id != project.id for image in samples):
        raise HTTPException(404, "image_not_found")
    references = [image for image in samples if image is not None]
    if variant is None:
        drawn_from = angles.for_drawing(entity.images, key)
    else:
        # A new look starts from the face of a look already there (owner's notes 25.11), so
        # it stays the same person; a thing-like shape is not drawn from a human face.
        drawn_from = angles.for_drawing(own, key)
        if not drawn_from and variant.get("shape") != "object":
            human = {v["key"] for v in entity.variants if v.get("shape") != "object"}
            others = [i for i in entity.images if i.variant in human and i.angle == "face_front"]
            drawn_from = angles.for_drawing(others, key)[:1]
    references += [i for i in drawn_from if i not in references]
    return Drawing(project, chapters, angle, references[: angles.DRAWING_LIMIT], variant)


@router.post("/entities/{entity_id}/image-prompt")
def image_prompt(entity_id: str, body: PromptRequest, session: SessionDep) -> PromptOut:
    """Text model only. The prompt is shown for editing; nothing is drawn yet."""
    entity = _entity(session, entity_id)
    drawing = _drawing(session, entity, body)
    view_free = body.view_free and drawing.chapters is None
    try:
        model = TextModel(session, drawing.project.id, "prompts")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        prompt = build_image_prompt(
            model,
            drawing.project,
            entity,
            drawing.chapters,
            body.look_label,
            bool(drawing.references),
            "" if view_free else drawing.angle,
            view_free,
            body.note,
            drawing.variant,
        )
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return PromptOut(prompt=prompt, angle="" if view_free else drawing.angle)


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str

    @field_validator("language")
    @classmethod
    def known_language(cls, value: str) -> str:
        if value not in LANGUAGES:
            raise ValueError("unknown language")
        return value


class RefineRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    change: str = Field(min_length=1, max_length=1000)


class TextOut(BaseModel):
    text: str


def _prompt_model(session: SessionDep, entity_id: str) -> TextModel:
    entity = _entity(session, entity_id)
    try:
        return TextModel(session, entity.project_id, "prompts")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/entities/{entity_id}/image-prompt/translate")
def translate_image_prompt(entity_id: str, body: TranslateRequest, session: SessionDep) -> TextOut:
    """One half of the two-language prompt was edited: the other half follows it."""
    model = _prompt_model(session, entity_id)
    try:
        return TextOut(text=translate_prompt(model, body.text, body.language))
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc


@router.post("/entities/{entity_id}/image-prompt/refine")
def refine_image(entity_id: str, body: RefineRequest, session: SessionDep) -> TextOut:
    """The author's remark before a redraw, typed or spoken: the English prompt with it."""
    model = _prompt_model(session, entity_id)
    try:
        return TextOut(text=refine_image_prompt(model, body.prompt, body.change))
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc


@router.post("/entities/{entity_id}/images/generate")
def generate_image(entity_id: str, body: GenerateRequest, session: SessionDep) -> ImageOut:
    entity = _entity(session, entity_id)
    drawing = _drawing(session, entity, body)
    project = drawing.project
    if not style_prompt(project):
        raise HTTPException(409, "style_not_chosen")
    try:
        model = ImageModel(session, project.id)
    except ImageModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    references = [settings.files_dir / image.path for image in drawing.references]
    prompt = body.prompt.strip()
    if body.add_view and drawing.angle:
        prompt = f"{angles.ANGLES[drawing.angle]} {prompt}"
    try:
        result = model.generate(prompt, references, body.size)
    except ImageGenerationFailed as exc:
        raise HTTPException(502, f"provider_error: {exc}") from exc
    mime = result.mime if result.mime in EXTENSIONS else "image/png"
    image_id, relative = _store(project, result.data, mime)
    key = style_key(project)
    is_look = drawing.chapters is not None
    image = Image(
        id=image_id,
        project_id=project.id,
        entity_id=entity.id,
        origin="generated",
        style_key=key,
        is_main=not is_look,
        angle=drawing.angle,
        variant=drawing.variant["key"] if drawing.variant else "",
        look_label=body.look_label.strip(),
        chapter_from_id=body.chapter_from_id,
        chapter_to_id=body.chapter_to_id,
        prompt=prompt,
        reference_ids=[reference.id for reference in drawing.references],
        filename="",
        path=relative,
        mime=mime,
    )
    session.add(image)
    session.commit()
    return _out(image, project)


class RedoRequest(BaseModel):
    # Exactly one: an edited prompt (drawn anew) or a remark (the picture improved).
    prompt: str = Field(default="", max_length=4000)
    remark: str = Field(default="", max_length=1000)
    size: str = ""

    @field_validator("size")
    @classmethod
    def known_size(cls, value: str) -> str:
        if value and value not in SIZES:
            raise ValueError("unknown size")
        return value


# A remark is carried out on the picture itself: the image model sees it as the reference.
IMPROVE_PROMPT = (
    "Edit the reference image. Change only this: {remark}. Keep everything else exactly as "
    "it is: the same subject, face, clothes, pose, framing, background, lighting and style."
)


@router.post("/images/{image_id}/redo")
def redo_image(image_id: str, body: RedoRequest, session: SessionDep) -> ImageOut:
    """A finished or put in picture drawn again by the user's press (owner's notes 26.11).

    An edited prompt draws it anew from the references of its first drawing; a remark
    improves the picture as it is. The new picture takes the old one's place and id, so the
    slot, the card and the scenes that use it keep pointing at it; the old file goes, as the
    user asked to replace it.
    """
    image = _image(session, image_id)
    prompt, remark = body.prompt.strip(), body.remark.strip()
    if bool(prompt) == bool(remark):
        raise HTTPException(422, "redo_prompt_or_remark")
    project = _project(session, image.project_id)
    if not style_prompt(project):
        raise HTTPException(409, "style_not_chosen")
    try:
        model = ImageModel(session, project.id)
    except ImageModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    if prompt:
        first = [session.get(Image, i) for i in image.reference_ids or []]
        kept = [i for i in first if i is not None and i.project_id == project.id]
        references = [settings.files_dir / i.path for i in kept]
        text = prompt
    else:
        references = [settings.files_dir / image.path]
        text = IMPROVE_PROMPT.format(remark=remark)
    try:
        result = model.generate(text, references, body.size)
    except ImageGenerationFailed as exc:
        raise HTTPException(502, f"provider_error: {exc}") from exc
    mime = result.mime if result.mime in EXTENSIONS else "image/png"
    _, relative = _store(project, result.data, mime)
    old_path = (settings.files_dir / image.path).resolve()
    image.path = relative
    image.mime = mime
    image.origin = "generated"
    image.style_key = style_key(project)
    if prompt:
        # The prompt and references of the first drawing stay after an improvement, so a later
        # edit of the prompt still starts from them.
        image.prompt = prompt
        image.reference_ids = [i.id for i in kept]
    session.commit()
    if (
        old_path.is_relative_to(settings.files_dir.resolve())
        and old_path.name != PurePath(relative).name
    ):
        old_path.unlink(missing_ok=True)
    return _out(image, project)


# ---------- outward looks ----------


class Variant(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    shape: str = "human"

    @field_validator("shape")
    @classmethod
    def known_shape(cls, value: str) -> str:
        return value if value in ("human", "object") else "human"


@router.get("/entities/{entity_id}/variants")
def get_variants(entity_id: str, session: SessionDep) -> list[Variant]:
    return [Variant(**v) for v in _entity(session, entity_id).variants or []]


@router.post("/entities/{entity_id}/variants/find")
def find_entity_variants(entity_id: str, session: SessionDep) -> list[Variant]:
    """The text model lists the character's outward looks; shown, saved only by the user."""
    entity = _entity(session, entity_id)
    model = _prompt_model(session, entity_id)
    try:
        found = find_variants(model, entity)
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return [Variant(**v) for v in found]


@router.put("/entities/{entity_id}/variants")
def save_variants(entity_id: str, body: list[Variant], session: SessionDep) -> list[Variant]:
    """The looks the user kept. Pictures of a dropped look stay, shown with no look."""
    entity = _entity(session, entity_id)
    if len(body) > 8:
        raise HTTPException(422, "too_many_variants")
    had_looks = bool(entity.variants)
    entity.variants = [v.model_dump() for v in body]
    kept = {v.key for v in body}
    for image in entity.images:
        if image.variant and image.variant not in kept:
            image.variant = ""
        # The first looks of a card: the base pictures drawn so far belong to the first one.
        if not had_looks and body and image.is_main and not image.variant:
            image.variant = body[0].key
    session.commit()
    return body


# ---------- cards made by hand ----------


@router.post("/projects/{project_id}/entities")
def create_entity(project_id: str, body: EntityCreate, session: SessionDep) -> dict:
    """An empty card for someone the search has not reached yet, so references can be
    attached now. A later search adds facts to it by name."""
    project = _project(session, project_id)
    if body.kind not in (KIND_CHARACTER, KIND_LOCATION, KIND_ITEM):
        raise HTTPException(422, "bad_kind")
    name = body.name.strip()
    for existing in session.scalars(
        select(Entity).where(Entity.project_id == project.id, Entity.kind == body.kind)
    ):
        if norm(name) in {norm(existing.name), *map(norm, existing.aliases)}:
            return {"id": existing.id}
    entity = Entity(project_id=project.id, kind=body.kind, name=name, aliases=[], standalone=True)
    session.add(entity)
    session.commit()
    return {"id": entity.id}


# ---------- a card carried from one project to another ----------

CARD_FORMAT = "lorebook-card"
MAX_CARD_FILE = 200 * 1024 * 1024
MAX_CARD_IMAGES = 100
DESCRIPTION_LIMIT = 6000


@router.get("/entities/{entity_id}/export")
def export_entity(entity_id: str, session: SessionDep) -> Response:
    """One card as a zip: card.json with its texts and facts, and its pictures beside it.
    Chapters are named by title, since their ids mean nothing in another project."""
    entity = _entity(session, entity_id)
    project = _project(session, entity.project_id)
    titles = {c.id: c.title for c in project.chapters}
    positions = {c.id: c.position for c in project.chapters}
    facts = sorted(entity.facts, key=lambda f: positions.get(f.chapter_id, len(positions)))
    buffer = io.BytesIO()
    pictures = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for n, image in enumerate(entity.images, 1):
            source = settings.files_dir / image.path
            if not source.is_file():
                continue
            name = f"images/{n}{EXTENSIONS.get(image.mime, '')}"
            archive.writestr(name, source.read_bytes())
            pictures.append(
                {
                    "file": name,
                    "origin": image.origin,
                    "style_key": image.style_key,
                    "is_main": image.is_main,
                    "angle": image.angle,
                    "look_label": image.look_label,
                    "prompt": image.prompt,
                }
            )
        card = {
            "format": CARD_FORMAT,
            "version": 1,
            "kind": entity.kind,
            "name": entity.name,
            "aliases": entity.aliases,
            "description": entity.description,
            "summary": entity.summary,
            "appearance": entity.appearance,
            "appearance_own": entity.appearance_own,
            "facts": [
                {
                    "category": f.category,
                    "text": f.text,
                    "quote": f.quote,
                    "chapter": titles.get(f.chapter_id, ""),
                }
                for f in facts
                if f.text.strip()
            ],
            "images": pictures,
        }
        archive.writestr("card.json", json.dumps(card, ensure_ascii=False, indent=2))
    disposition = "attachment; filename=\"card.zip\"; filename*=UTF-8''" + quote(
        f"{entity.name}.zip"
    )
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": disposition},
    )


def _text(card: dict, key: str) -> str:
    value = card.get(key, "")
    return value.strip() if isinstance(value, str) else ""


@router.post("/projects/{project_id}/entities/import")
def import_entity(
    project_id: str,
    session: SessionDep,
    file: UploadFile,
    kind: Annotated[str, Form()] = "",
) -> dict:
    """A card from a file made by the export. Facts were read from another book's chapters,
    so the lasting ones go into the author's description, which later searches keep. A card
    of the same name here takes the new one in."""
    project = _project(session, project_id)
    data = file.file.read(MAX_CARD_FILE + 1)
    if len(data) > MAX_CARD_FILE:
        raise HTTPException(413, "file_too_large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        card = json.loads(archive.read("card.json"))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise HTTPException(422, "not_a_card_file") from exc
    if not isinstance(card, dict) or card.get("format") != CARD_FORMAT:
        raise HTTPException(422, "not_a_card_file")
    kind = kind or str(card.get("kind", ""))
    if kind not in (KIND_CHARACTER, KIND_LOCATION, KIND_ITEM):
        raise HTTPException(422, "bad_kind")
    name = _text(card, "name")[:200]
    if not name:
        raise HTTPException(422, "not_a_card_file")
    aliases = list(
        dict.fromkeys(
            a.strip()[:200]
            for a in card.get("aliases") or []
            if isinstance(a, str) and a.strip() and norm(a) != norm(name)
        )
    )

    description = _text(card, "description") or _text(card, "summary")
    lasting: list[str] = []
    for fact in card.get("facts") or []:
        if not isinstance(fact, dict) or fact.get("category") not in (FACT_PROFILE, FACT_PERMANENT):
            continue
        text = _text(fact, "text")
        if text and text not in lasting and text not in description:
            lasting.append(text)
    if lasting:
        listed = "\n".join(f"— {t}" for t in lasting)
        description = f"{description}\n\n{listed}" if description else listed
    entity = Entity(
        project_id=project.id,
        kind=kind,
        name=name,
        aliases=aliases,
        pinned_names=aliases,
        standalone=True,
        description=description[:DESCRIPTION_LIMIT],
        summary=_text(card, "summary"),
        appearance=_text(card, "appearance"),
        appearance_own=_text(card, "appearance_own"),
    )
    session.add(entity)
    session.flush()

    for picture in (card.get("images") or [])[:MAX_CARD_IMAGES]:
        if not isinstance(picture, dict) or not isinstance(picture.get("file"), str):
            continue
        try:
            info = archive.getinfo(picture["file"])
        except KeyError:
            continue
        if info.file_size > MAX_IMAGE_BYTES:
            continue
        content = archive.read(info)
        mime = _sniff(content)
        if mime is None:
            continue
        image_id, relative = _store(project, content, mime)
        angle = _text(picture, "angle")
        session.add(
            Image(
                id=image_id,
                project_id=project.id,
                entity_id=entity.id,
                origin="generated" if picture.get("origin") == "generated" else "upload",
                style_key=_text(picture, "style_key")[:40],
                is_main=bool(picture.get("is_main")),
                angle=angle if angle in angles.ANGLES else "",
                look_label=_text(picture, "look_label")[:200],
                prompt=_text(picture, "prompt"),
                filename=PurePath(info.filename).name[:300],
                path=relative,
                mime=mime,
            )
        )
    session.flush()

    for existing in session.scalars(
        select(Entity).where(
            Entity.project_id == project.id, Entity.kind == kind, Entity.id != entity.id
        )
    ):
        if norm(name) in {norm(existing.name), *map(norm, existing.aliases)}:
            fill = {
                key: getattr(entity, key)
                for key in ("description", "summary", "appearance", "appearance_own")
                if not getattr(existing, key).strip()
            }
            merge_by_hand(session, existing, entity)
            for key, value in fill.items():
                setattr(existing, key, value)
            session.commit()
            return {"id": existing.id}
    session.commit()
    return {"id": entity.id}
