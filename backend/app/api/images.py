from datetime import datetime
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analysis.entities import norm
from app.config import settings
from app.db import SessionDep
from app.images.generate import ImageGenerationFailed, ImageModel, ImageModelNotConfigured
from app.images.prompts import build_image_prompt, chapters_between
from app.images.styles import CUSTOM, PRESETS, style_key, style_prompt
from app.llm.calls import ModelNotConfigured, TextModel
from app.models import KIND_CHARACTER, KIND_LOCATION, Entity, Image, Project, new_id

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
    look_label: str
    chapter_from_id: str
    chapter_to_id: str
    prompt: str
    url: str
    created_at: datetime


class ImagePatch(BaseModel):
    is_main: bool | None = None
    look_label: str | None = Field(default=None, max_length=200)
    chapter_from_id: str | None = None
    chapter_to_id: str | None = None


class LookRequest(BaseModel):
    """Empty label and chapters: the base image. Otherwise a look for part of the story."""

    look_label: str = Field(default="", max_length=200)
    chapter_from_id: str = ""
    chapter_to_id: str = ""


class GenerateRequest(LookRequest):
    prompt: str = Field(min_length=1, max_length=4000)


class PromptOut(BaseModel):
    prompt: str


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


def _out(image: Image, project: Project) -> ImageOut:
    return ImageOut(
        id=image.id,
        entity_id=image.entity_id,
        origin=image.origin,
        style_key=image.style_key,
        current_style=image.style_key == style_key(project),
        is_main=image.is_main,
        look_label=image.look_label,
        chapter_from_id=image.chapter_from_id,
        chapter_to_id=image.chapter_to_id,
        prompt=image.prompt,
        url=f"/api/images/{image.id}/file",
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


def _main(session: SessionDep, entity: Entity, key: str) -> Image | None:
    """The picture that defines the face and build, in the given style."""
    return next((i for i in entity.images if i.is_main and i.style_key == key), None)


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
    query = query.where(Image.entity_id == entity_id if entity_id else Image.entity_id.is_(None))
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
            is_main=entity is not None and _main(session, entity, key) is None and not created,
            filename=PurePath(file.filename or "image").name[:300],
            path=relative,
            mime=mime,
        )
        session.add(image)
        created.append(image)
    session.commit()
    return [_out(image, project) for image in created]


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
        if patch.is_main and image.entity_id:
            # One main picture per card and style.
            for other in session.get(Entity, image.entity_id).images:
                if other.style_key == image.style_key:
                    other.is_main = False
        image.is_main = patch.is_main and image.entity_id is not None
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


def _look(session: SessionDep, entity: Entity, body: LookRequest):
    project = _project(session, entity.project_id)
    is_look = bool(body.look_label or body.chapter_from_id or body.chapter_to_id)
    chapters = (
        chapters_between(project, body.chapter_from_id, body.chapter_to_id) if is_look else None
    )
    # A look is drawn from the main picture; the main picture itself starts from nothing.
    reference = _main(session, entity, style_key(project)) if is_look else None
    return project, chapters, reference


@router.post("/entities/{entity_id}/image-prompt")
def image_prompt(entity_id: str, body: LookRequest, session: SessionDep) -> PromptOut:
    """Text model only. The prompt is shown for editing; nothing is drawn yet."""
    entity = _entity(session, entity_id)
    project, chapters, reference = _look(session, entity, body)
    try:
        model = TextModel(session, project.id)
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        prompt = build_image_prompt(
            model, project, entity, chapters, body.look_label, reference is not None
        )
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return PromptOut(prompt=prompt)


@router.post("/entities/{entity_id}/images/generate")
def generate_image(entity_id: str, body: GenerateRequest, session: SessionDep) -> ImageOut:
    entity = _entity(session, entity_id)
    project, _, reference = _look(session, entity, body)
    if not style_prompt(project):
        raise HTTPException(409, "style_not_chosen")
    try:
        model = ImageModel(session, project.id)
    except ImageModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    references = [settings.files_dir / reference.path] if reference else []
    try:
        result = model.generate(body.prompt, references)
    except ImageGenerationFailed as exc:
        raise HTTPException(502, f"provider_error: {exc}") from exc
    mime = result.mime if result.mime in EXTENSIONS else "image/png"
    image_id, relative = _store(project, result.data, mime)
    key = style_key(project)
    is_look = bool(body.look_label or body.chapter_from_id or body.chapter_to_id)
    image = Image(
        id=image_id,
        project_id=project.id,
        entity_id=entity.id,
        origin="generated",
        style_key=key,
        is_main=not is_look and _main(session, entity, key) is None,
        look_label=body.look_label.strip(),
        chapter_from_id=body.chapter_from_id,
        chapter_to_id=body.chapter_to_id,
        prompt=body.prompt,
        filename="",
        path=relative,
        mime=mime,
    )
    session.add(image)
    session.commit()
    return _out(image, project)


# ---------- cards made by hand ----------


@router.post("/projects/{project_id}/entities")
def create_entity(project_id: str, body: EntityCreate, session: SessionDep) -> dict:
    """An empty card for someone the search has not reached yet, so references can be
    attached now. A later search adds facts to it by name."""
    project = _project(session, project_id)
    if body.kind not in (KIND_CHARACTER, KIND_LOCATION):
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
