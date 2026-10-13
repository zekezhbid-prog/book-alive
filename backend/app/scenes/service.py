"""Scenes: a stretch of a chapter, who is in it, and the prompt that brings it to life."""

import io
import re
import zipfile
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.entities import norm
from app.config import settings
from app.images.styles import style_key, style_prompt
from app.llm.calls import TextModel
from app.models import (
    FACT_PERMANENT,
    FACT_STATE,
    KIND_CHARACTER,
    Chapter,
    Entity,
    Image,
    Project,
    Scene,
)

SPLIT_SYSTEM = """You divide one chapter of a book into scenes for a screen adaptation. \
The paragraphs are numbered from 0.

A scene is a continuous stretch of the text in one place and time. Rules:
- Cover every paragraph, in order, with no gaps and no overlaps.
- "from" and "to" are paragraph numbers, inclusive.
- "title": a few words. "summary": one sentence. Both in the language of the chapter.
- "vivid": true for the two or three scenes of the chapter that would look most striking \
on screen, false for the rest.
- "characters": names of those who take part, as the text writes them. "location": the \
name of the place, or an empty string.

Reply with one JSON object and nothing else:
{"scenes": [{"from": 0, "to": 4, "title": "", "summary": "", "vivid": false, \
"characters": [], "location": ""}]}"""

VIDEO_SYSTEM = """You write one prompt for an AI video generator: a single shot of 5 to 10 \
seconds that brings a scene from a book to life.

Rules:
- English only, one paragraph, under 130 words, no line breaks, no quotation marks.
- Pick the single most visual moment of the scene and describe one clear action.
- Video models do not know the book. Never rely on names: describe who is on screen by how \
they look. When a reference picture is listed for someone, call them "the figure from \
reference N" and add only what the picture cannot show (action, expression, state).
- Appearance comes only from the facts given. Do not invent clothes, colours or features.
- Say where it happens, the time of day and the light, then the camera: shot size and one \
movement.
- If the author's note below asks for something, it overrides your own choices.
- End with the style, word for word: {style}

Reply with the prompt only."""

REFINE_SYSTEM = """Below is a prompt for an AI video generator and a change the author \
wants. Rewrite the prompt with that change and keep everything else as it is, including \
the references and the style at the end. English only, one paragraph, under 130 words.

Reply with the prompt only."""


class SceneDraft(BaseModel):
    start: int = Field(alias="from")
    end: int = Field(alias="to")
    title: str = ""
    summary: str = ""
    vivid: bool = False
    characters: list[str] = Field(default_factory=list)
    location: str = ""


class SceneDrafts(BaseModel):
    scenes: list[SceneDraft]


def paragraphs_of(chapter: Chapter) -> list[str]:
    return chapter.text.split("\n\n") if chapter.text else []


def scene_text(scene: Scene, chapter: Chapter) -> str:
    return "\n\n".join(paragraphs_of(chapter)[scene.paragraph_from : scene.paragraph_to + 1])


def _stem(name: str) -> str:
    """Names change their endings in Slavic languages: match on the stem."""
    return re.sub(r"(?<=.{3})[аяоеыиьйуюіaeo]$", "", name.strip().casefold())


def entities_in(session: Session, project_id: str, text: str, named: list[str]) -> list[str]:
    """Cards that belong to a stretch of text: named by the model, or found by name."""
    lowered = text.casefold()
    wanted = {norm(n) for n in named if n.strip()}
    found = []
    for entity in session.scalars(select(Entity).where(Entity.project_id == project_id)):
        names = [entity.name, *entity.aliases]
        by_model = any(norm(n) in wanted for n in names)
        by_text = any(
            re.search(rf"(?<!\w){re.escape(_stem(n))}\w{{0,3}}(?!\w)", lowered)
            for n in names
            if len(_stem(n)) >= 3
        )
        if by_model or by_text:
            found.append(entity.id)
    return found


def split_chapter(session: Session, model: TextModel, chapter: Chapter) -> list[Scene]:
    """Ask the model for scene boundaries. Replaces the chapter's earlier automatic
    scenes; scenes the user marked by hand stay."""
    paragraphs = paragraphs_of(chapter)
    numbered = "\n\n".join(f"[{n}] {text}" for n, text in enumerate(paragraphs))
    answer = model.invoke_json(
        "split_scenes", [SystemMessage(SPLIT_SYSTEM), HumanMessage(numbered)], SceneDrafts
    )
    drafts = sorted(answer.scenes, key=lambda d: d.start)
    session.execute(delete(Scene).where(Scene.chapter_id == chapter.id, Scene.origin == "auto"))
    scenes: list[Scene] = []
    cursor = 0
    last = len(paragraphs) - 1
    for index, draft in enumerate(drafts):
        if cursor > last:
            break
        # The model's numbers are a suggestion; the result must tile the chapter exactly.
        end = last if index == len(drafts) - 1 else min(max(draft.end, cursor), last)
        text = "\n\n".join(paragraphs[cursor : end + 1])
        scenes.append(
            Scene(
                project_id=chapter.project_id,
                chapter_id=chapter.id,
                chapter_hash=chapter.content_hash,
                paragraph_from=cursor,
                paragraph_to=end,
                title=draft.title.strip()[:300],
                summary=draft.summary.strip(),
                vivid=draft.vivid,
                origin="auto",
                entity_ids=entities_in(
                    session, chapter.project_id, text, [*draft.characters, draft.location]
                ),
            )
        )
        cursor = end + 1
    session.add_all(scenes)
    session.commit()
    return scenes


def mark_scene(session: Session, chapter: Chapter, start: int, end: int, title: str) -> Scene:
    """A scene the user marked in the reader. No model involved."""
    text = "\n\n".join(paragraphs_of(chapter)[start : end + 1])
    scene = Scene(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        chapter_hash=chapter.content_hash,
        paragraph_from=start,
        paragraph_to=end,
        title=title.strip()[:300] or text[:60].strip(),
        summary="",
        vivid=False,
        origin="manual",
        entity_ids=entities_in(session, chapter.project_id, text, []),
    )
    session.add(scene)
    session.commit()
    return scene


# ---------- references ----------


@dataclass
class Reference:
    number: int
    image: Image
    entity: Entity
    role: str  # main | look


def pick_images(project: Project, entity: Entity, chapter: Chapter) -> list[tuple[Image, str]]:
    """The main picture, and the look whose chapter range covers this chapter. Only
    pictures in the project's current style count."""
    key = style_key(project)
    positions = {c.id: c.position for c in project.chapters}
    current = [i for i in entity.images if i.style_key == key]
    picked = [(i, "main") for i in current if i.is_main][:1]

    def span(image: Image) -> tuple[int, int]:
        return (
            positions.get(image.chapter_from_id, 0),
            positions.get(image.chapter_to_id, len(positions)),
        )

    looks = [
        i
        for i in current
        if not i.is_main
        and (i.look_label or i.chapter_from_id or i.chapter_to_id)
        and span(i)[0] <= chapter.position <= span(i)[1]
    ]
    if looks:
        # The narrowest range is the most specific statement about this chapter.
        picked.append((min(looks, key=lambda i: span(i)[1] - span(i)[0]), "look"))
    return picked


def references(
    session: Session, project: Project, scene: Scene, chapter: Chapter
) -> list[Reference]:
    entities = [session.get(Entity, entity_id) for entity_id in scene.entity_ids]
    # Characters first: they matter most for consistency, and models take few pictures.
    ordered = sorted((e for e in entities if e), key=lambda e: (e.kind != KIND_CHARACTER, e.name))
    result: list[Reference] = []
    for entity in ordered:
        for image, role in pick_images(project, entity, chapter):
            result.append(Reference(len(result) + 1, image, entity, role))
    return result


# ---------- prompt ----------


def _facts_at(project: Project, entity: Entity, chapter: Chapter) -> tuple[list[str], list[str]]:
    """Permanent traits, and the state as of this chapter: its own state facts, or
    those of the nearest earlier chapter that has any."""
    positions = {c.id: c.position for c in project.chapters}
    permanent = [f.text for f in entity.facts if f.category == FACT_PERMANENT]
    earlier = [
        f
        for f in entity.facts
        if f.category == FACT_STATE and positions.get(f.chapter_id, -1) <= chapter.position
    ]
    if not earlier:
        return permanent, []
    latest = max(positions.get(f.chapter_id, -1) for f in earlier)
    return permanent, [f.text for f in earlier if positions.get(f.chapter_id) == latest]


def scene_context(
    session: Session, project: Project, scene: Scene, chapter: Chapter, note: str
) -> str:
    refs = references(session, project, scene, chapter)
    lines = ["Scene text:", scene_text(scene, chapter), ""]
    for entity_id in scene.entity_ids:
        entity = session.get(Entity, entity_id)
        if entity is None:
            continue
        permanent, state = _facts_at(project, entity, chapter)
        numbers = [f"reference {r.number} ({r.role})" for r in refs if r.entity.id == entity.id]
        kind = "Character" if entity.kind == KIND_CHARACTER else "Location"
        lines.append(f"{kind}: {entity.name} - {', '.join(numbers) or 'no reference picture'}")
        lines += [f"  permanent: {t}" for t in permanent]
        lines += [f"  at this point: {t}" for t in state]
    if note.strip():
        lines += ["", f"Author's note: {note.strip()}"]
    return "\n".join(lines)


def video_prompt(
    session: Session, model: TextModel, project: Project, scene: Scene, note: str
) -> str:
    chapter = session.get(Chapter, scene.chapter_id)
    system = VIDEO_SYSTEM.format(style=style_prompt(project) or "(no style chosen: omit this part)")
    context = scene_context(session, project, scene, chapter, note)
    return model.invoke("video_prompt", [SystemMessage(system), HumanMessage(context)]).strip()


def refine_prompt(model: TextModel, prompt: str, change: str) -> str:
    request = f"Prompt:\n{prompt}\n\nChange wanted:\n{change}"
    return model.invoke(
        "refine_prompt", [SystemMessage(REFINE_SYSTEM), HumanMessage(request)]
    ).strip()


def frame_prompt(prompt: str) -> str:
    """The still that a video model animates from: the same shot, frozen at its start."""
    return f"A single still frame, the opening moment of this shot, no motion blur: {prompt}"


# ---------- archive ----------

_LATIN = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюяіўїє",
        [
            "a",
            "b",
            "v",
            "g",
            "d",
            "e",
            "yo",
            "zh",
            "z",
            "i",
            "y",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "r",
            "s",
            "t",
            "u",
            "f",
            "kh",
            "ts",
            "ch",
            "sh",
            "sch",
            "_",
            "y",
            "_",
            "e",
            "yu",
            "ya",
            "i",
            "u",
            "yi",
            "ye",
        ],
        strict=True,
    )
)


def slug(text: str) -> str:
    """File names in plain Latin: other services and scripts choke on Cyrillic paths."""
    latin = "".join(_LATIN.get(ch, ch) for ch in text.casefold())
    return re.sub(r"[^a-z0-9]+", "_", latin).strip("_")[:40] or "x"


def archive(session: Session, project: Project, scene: Scene) -> bytes:
    """Everything to take to a video service: the prompt, the pictures under readable
    names, and a note saying which picture is who."""
    chapter = session.get(Chapter, scene.chapter_id)
    refs = references(session, project, scene, chapter)
    frame = session.scalars(
        select(Image).where(Image.scene_id == scene.id).order_by(Image.created_at.desc())
    ).first()
    notes = [
        f"{project.title} - {chapter.title} - {scene.title}",
        "",
        "prompt.txt: the video prompt",
        "",
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", zipfile.ZIP_STORED
    ) as bundle:  # pictures are compressed already
        bundle.writestr("prompt.txt", scene.prompt)
        if frame is not None:
            name = "frame" + _extension(frame)
            bundle.write(settings.files_dir / frame.path, name)
            notes.append(f"{name}: first frame of the scene (use as the start image)")
        for ref in refs:
            label = slug(ref.image.look_label) if ref.role == "look" else "main"
            name = f"ref{ref.number:02d}_{slug(ref.entity.name)}_{label}{_extension(ref.image)}"
            bundle.write(settings.files_dir / ref.image.path, name)
            detail = (
                f" ({ref.image.look_label})" if ref.role == "look" and ref.image.look_label else ""
            )
            notes.append(f"{name}: reference {ref.number} - {ref.entity.name}, {ref.role}{detail}")
        bundle.writestr("README.txt", "\n".join(notes))
    return buffer.getvalue()


def _extension(image: Image) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(
        image.mime, ".png"
    )
