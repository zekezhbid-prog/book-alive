from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.images import EXTENSIONS, ImageOut, _store
from app.api.images import _out as image_out
from app.config import settings
from app.db import SessionDep
from app.images.generate import ImageGenerationFailed, ImageModel, ImageModelNotConfigured
from app.images.styles import style_key, style_prompt
from app.llm.calls import BadModelOutput, ModelNotConfigured, TextModel, estimate_tokens
from app.models import Chapter, Entity, Image, Project, Scene
from app.scenes import service

router = APIRouter(prefix="/api", tags=["scenes"])


class SceneBrief(BaseModel):
    id: str
    chapter_id: str
    chapter_title: str
    chapter_position: int
    paragraph_from: int
    paragraph_to: int
    title: str
    summary: str
    vivid: bool
    origin: str
    stale: bool
    has_prompt: bool


class Participant(BaseModel):
    id: str
    kind: str
    name: str


class ReferenceOut(BaseModel):
    number: int
    entity_id: str
    entity_name: str
    role: str
    look_label: str
    url: str


class SceneOut(SceneBrief):
    text: str
    prompt: str
    participants: list[Participant]
    references: list[ReferenceOut]
    frames: list[ImageOut]


class MarkRequest(BaseModel):
    paragraph_from: int
    paragraph_to: int
    title: str = Field(default="", max_length=300)


class SplitEstimate(BaseModel):
    input_tokens: int
    output_tokens: int
    existing: int  # automatic scenes that a new split will replace


class PromptRequest(BaseModel):
    note: str = Field(default="", max_length=2000)


class RefineRequest(BaseModel):
    change: str = Field(min_length=1, max_length=2000)


class PromptPatch(BaseModel):
    prompt: str = Field(max_length=6000)


def _scene(session: SessionDep, scene_id: str) -> tuple[Scene, Chapter | None, Project]:
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "scene_not_found")
    return scene, session.get(Chapter, scene.chapter_id), session.get(Project, scene.project_id)


def _chapter(session: SessionDep, chapter_id: str) -> Chapter:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(404, "chapter_not_found")
    return chapter


def _text_model(session: SessionDep, project_id: str) -> TextModel:
    try:
        return TextModel(session, project_id)
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc


def _brief(scene: Scene, chapter: Chapter | None) -> SceneBrief:
    return SceneBrief(
        id=scene.id,
        chapter_id=scene.chapter_id,
        chapter_title=chapter.title if chapter else "",
        chapter_position=chapter.position if chapter else -1,
        paragraph_from=scene.paragraph_from,
        paragraph_to=scene.paragraph_to,
        title=scene.title,
        summary=scene.summary,
        vivid=scene.vivid,
        origin=scene.origin,
        # The paragraph numbers were counted in a text that has since changed.
        stale=chapter is None or chapter.content_hash != scene.chapter_hash,
        has_prompt=bool(scene.prompt),
    )


def _full(session: SessionDep, scene: Scene, chapter: Chapter | None, project: Project) -> SceneOut:
    participants = [session.get(Entity, entity_id) for entity_id in scene.entity_ids]
    refs = service.references(session, project, scene, chapter) if chapter else []
    frames = session.scalars(
        select(Image).where(Image.scene_id == scene.id).order_by(Image.created_at.desc())
    ).all()
    return SceneOut(
        **_brief(scene, chapter).model_dump(),
        text=service.scene_text(scene, chapter) if chapter else "",
        prompt=scene.prompt,
        participants=[Participant(id=e.id, kind=e.kind, name=e.name) for e in participants if e],
        references=[
            ReferenceOut(
                number=r.number,
                entity_id=r.entity.id,
                entity_name=r.entity.name,
                role=r.role,
                look_label=r.image.look_label,
                url=f"/api/images/{r.image.id}/file",
            )
            for r in refs
        ],
        frames=[image_out(frame, project) for frame in frames],
    )


@router.get("/projects/{project_id}/scenes")
def list_scenes(project_id: str, session: SessionDep) -> list[SceneBrief]:
    chapters = {
        c.id: c for c in session.scalars(select(Chapter).where(Chapter.project_id == project_id))
    }
    scenes = session.scalars(select(Scene).where(Scene.project_id == project_id)).all()
    briefs = [_brief(scene, chapters.get(scene.chapter_id)) for scene in scenes]
    return sorted(briefs, key=lambda b: (b.chapter_position, b.paragraph_from))


@router.get("/chapters/{chapter_id}/scenes/estimate")
def split_estimate(chapter_id: str, session: SessionDep) -> SplitEstimate:
    chapter = _chapter(session, chapter_id)
    overhead = 0
    try:
        overhead = TextModel(session, chapter.project_id).request_overhead
    except ModelNotConfigured:
        pass
    existing = session.scalars(
        select(Scene).where(Scene.chapter_id == chapter.id, Scene.origin == "auto")
    ).all()
    tokens = estimate_tokens(chapter.text)
    return SplitEstimate(
        input_tokens=tokens + estimate_tokens(service.SPLIT_SYSTEM) + overhead,
        output_tokens=max(300, tokens // 8),
        existing=len(existing),
    )


@router.post("/chapters/{chapter_id}/scenes/split")
def split(chapter_id: str, session: SessionDep) -> list[SceneBrief]:
    chapter = _chapter(session, chapter_id)
    if not chapter.text.strip():
        raise HTTPException(422, "empty_chapter")
    model = _text_model(session, chapter.project_id)
    try:
        scenes = service.split_chapter(session, model, chapter)
    except BadModelOutput as exc:
        raise HTTPException(502, f"bad_model_output: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return [_brief(scene, chapter) for scene in scenes]


@router.post("/chapters/{chapter_id}/scenes")
def mark(chapter_id: str, body: MarkRequest, session: SessionDep) -> SceneBrief:
    chapter = _chapter(session, chapter_id)
    count = len(service.paragraphs_of(chapter))
    if not 0 <= body.paragraph_from <= body.paragraph_to < count:
        raise HTTPException(422, "bad_scene_range")
    scene = service.mark_scene(session, chapter, body.paragraph_from, body.paragraph_to, body.title)
    return _brief(scene, chapter)


@router.get("/scenes/{scene_id}")
def get_scene(scene_id: str, session: SessionDep) -> SceneOut:
    return _full(session, *_scene(session, scene_id))


@router.delete("/scenes/{scene_id}", status_code=204)
def delete_scene(scene_id: str, session: SessionDep) -> None:
    scene, _, _ = _scene(session, scene_id)
    session.delete(scene)  # its frames stay as pictures without a scene
    session.commit()


@router.post("/scenes/{scene_id}/prompt")
def build_prompt(scene_id: str, body: PromptRequest, session: SessionDep) -> SceneOut:
    scene, chapter, project = _scene(session, scene_id)
    if chapter is None:
        raise HTTPException(409, "chapter_not_found")
    model = _text_model(session, project.id)
    try:
        scene.prompt = service.video_prompt(session, model, project, scene, body.note)
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    session.commit()
    return _full(session, scene, chapter, project)


@router.post("/scenes/{scene_id}/prompt/refine")
def refine(scene_id: str, body: RefineRequest, session: SessionDep) -> SceneOut:
    scene, chapter, project = _scene(session, scene_id)
    if not scene.prompt:
        raise HTTPException(409, "no_prompt_yet")
    model = _text_model(session, project.id)
    try:
        scene.prompt = service.refine_prompt(model, scene.prompt, body.change)
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    session.commit()
    return _full(session, scene, chapter, project)


@router.put("/scenes/{scene_id}/prompt")
def save_prompt(scene_id: str, body: PromptPatch, session: SessionDep) -> SceneOut:
    """The user's own edit. Only the latest text is kept."""
    scene, chapter, project = _scene(session, scene_id)
    scene.prompt = body.prompt.strip()
    session.commit()
    return _full(session, scene, chapter, project)


@router.post("/scenes/{scene_id}/frame")
def generate_frame(scene_id: str, session: SessionDep) -> SceneOut:
    scene, chapter, project = _scene(session, scene_id)
    if not scene.prompt:
        raise HTTPException(409, "no_prompt_yet")
    if not style_prompt(project):
        raise HTTPException(409, "style_not_chosen")
    try:
        model = ImageModel(session, project.id)
    except ImageModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    refs = service.references(session, project, scene, chapter) if chapter else []
    try:
        result = model.generate(
            service.frame_prompt(scene.prompt), [settings.files_dir / r.image.path for r in refs]
        )
    except ImageGenerationFailed as exc:
        raise HTTPException(502, f"provider_error: {exc}") from exc
    mime = result.mime if result.mime in EXTENSIONS else "image/png"
    image_id, relative = _store(project, result.data, mime)
    session.add(
        Image(
            id=image_id,
            project_id=project.id,
            scene_id=scene.id,
            origin="generated",
            style_key=style_key(project),
            prompt=service.frame_prompt(scene.prompt),
            filename="",
            path=relative,
            mime=mime,
        )
    )
    session.commit()
    return _full(session, scene, chapter, project)


@router.get("/scenes/{scene_id}/archive")
def download(scene_id: str, session: SessionDep) -> Response:
    scene, chapter, project = _scene(session, scene_id)
    if chapter is None or not scene.prompt:
        raise HTTPException(409, "no_prompt_yet")
    name = f"{service.slug(project.title)}_{service.slug(scene.title)}.zip"
    return Response(
        service.archive(session, project, scene),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
