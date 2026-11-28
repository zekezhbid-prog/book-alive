"""Scenes: a stretch of a chapter, who is in it, and the prompt that brings it to life."""

import io
import re
import zipfile
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.entities import norm
from app.config import settings
from app.images import angles
from app.images.styles import style_key, style_prompt
from app.llm.calls import TextModel
from app.models import (
    FACT_PERMANENT,
    FACT_STATE,
    KIND_CHARACTER,
    KIND_ITEM,
    Chapter,
    Entity,
    Image,
    Project,
    Scene,
    SceneSplit,
    now,
)

SPLIT_SYSTEM = """You divide one chapter of a book into scenes for a screen adaptation. \
The paragraphs are numbered from 0.

A scene is a continuous stretch of the text in one place and time. Rules:
- Cover every paragraph, in order, with no gaps and no overlaps.
- "from" and "to" are paragraph numbers, inclusive.
- "title": a few words, in the language of the chapter.
- "summary": the scene as a film director would see it, 3 to 6 sentences in the language \
of the chapter: where and when it happens and what the place looks like, who is there, \
what they do one after another, what happens and why it matters for the story. Read the \
paragraphs around the scene to understand what is going on and say it plainly, but add \
no events the chapter does not give.
- A paragraph marked [heading] is a title of the book or the chapter, not part of the story.
- Do not make a scene of a passage that only announces, sums up or comments on what a \
neighbouring scene shows: join it to that scene. Two scenes must never tell the same event. \
A short chapter is often a single scene.
- "vivid": true for the two or three scenes of the chapter that would look most striking \
on screen, false for the rest.
- "characters": names of those who take part, as the text writes them. "location": the \
name of the place, or an empty string.

Reply with one JSON object and nothing else:
{"scenes": [{"from": 0, "to": 4, "title": "", "summary": "", "vivid": false, \
"characters": [], "location": ""}]}"""

VIDEO_SYSTEM = """You write one prompt for an AI video generator that makes video with \
sound: 5 to 15 seconds that bring a scene from a book to life.

Rules:
- English, except the spoken lines. Under 250 words, no line breaks.
- A scene may take several shots. When the action moves on (someone arrives, then they \
talk, then one leaves) or the camera has to change, write 2 to 4 shots, each beginning with \
its number and time, for example: Shot 1 (0-4s): ... Shot 2 (4-9s): ... Otherwise write one \
shot. Each shot has one clear action.
- Dialogue: when people speak in the scene text, put their lines into the shot where they \
are said, word for word in the language of the book, in quotation marks, with who says \
them and how (for example: the figure from reference 1 says quietly: "..."). Take only \
lines the text gives, the ones that fit the time, about 2.5 words a second. Also name the \
sounds of the place in a few words.
- Video models do not know the book. Never rely on names: describe who is on screen by how \
they look. When you use a reference picture for someone, call them "the figure from \
reference N" and add only what the picture cannot show (action, expression, state).
- Choose the reference pictures the shots need from those listed. For each person or place \
on screen, take the look made for this chapter when there is one; otherwise take only the \
base views the shots need (a face for a close-up, a full-length view for a wide shot). Use \
as few as serve, at most 4 in all, and mention in the prompt only the ones you chose.
- Appearance comes only from the facts given. Do not invent clothes, colours or features.
- A character's "nature" says how it moves, speaks and feels: let it shape the pace and \
manner of its movements, the tone of its lines and its expression, unless the scene shows \
otherwise.
- Say once where it happens, the time of day and the light; for each shot the camera: shot \
size and one movement.
- If the author's note below asks for something, it overrides your own choices.
- End with the style, word for word: {style}

Reply with one JSON object and nothing else:
{{"references": [1, 3], "prompt": ""}}"""

REFINE_SYSTEM = """Below are a scene of a book, who is in it with the reference pictures \
that may go with the video, a prompt for an AI video generator written for it, and a change \
the author wants. Rewrite the prompt with that change and keep everything else as it is, \
including the shots, the spoken lines (in the language of the book) and the style at the end.

- The prompt calls people and places "the figure from reference N"; N are the numbers of \
the list below. Keep the pictures the prompt uses unless the change says otherwise.
- The author may ask to add a picture ("take the full-length view of ...", "we need the \
mill") or to drop one ("no reference for ..."): change the list and the prompt to match. \
Without a picture, describe that person or place by how they look.
- At most 4 pictures in all. English apart from the spoken lines, under 250 words, no line \
breaks.

Reply with one JSON object and nothing else:
{"references": [1, 3], "prompt": ""}"""


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


class VideoAnswer(BaseModel):
    references: list[int] = Field(default_factory=list)
    prompt: str


def paragraphs_of(chapter: Chapter) -> list[str]:
    return chapter.text.split("\n\n") if chapter.text else []


def _folded(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text).casefold().split())


def is_heading(paragraph: str, project_title: str, chapter_title: str) -> bool:
    """A title line inside the chapter text ("THE BOOK TITLE"): the book's or the chapter's
    name, or a short line in capitals without a sentence end. Names in it are not the
    scene's cast (owner's notes 25.11: a name was taken from the book title)."""
    line = paragraph.strip()
    if not line or "\n" in line or len(line.split()) > 10:
        return False
    folded = _folded(line)
    if not folded:
        return True
    if folded == _folded(chapter_title) or folded == _folded(project_title):
        return True
    # The book's title with a working mark ("… MAIN"): two words or more of it, in order.
    if len(folded.split()) >= 2 and f" {folded} " in f" {_folded(project_title)} ":
        return True
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 3 and line.upper() == line and line[-1] not in ".!?…"


def _story_text(paragraphs: list[str], project_title: str, chapter_title: str) -> str:
    """The paragraphs without title lines: what the cast of a scene is looked for in."""
    return "\n\n".join(p for p in paragraphs if not is_heading(p, project_title, chapter_title))


def _project_title(session: Session, chapter: Chapter) -> str:
    project = session.get(Project, chapter.project_id)
    return project.title if project else ""


def scene_text(scene: Scene, chapter: Chapter) -> str:
    return "\n\n".join(paragraphs_of(chapter)[scene.paragraph_from : scene.paragraph_to + 1])


def _stem(name: str) -> str:
    """Names change their endings in Slavic languages: match on the stem."""
    return re.sub(r"(?<=.{3})[аяоеыиьйуюіaeo]$", "", name.strip().casefold())


def _mentions(text: str, name: str) -> bool:
    """The name, with any Slavic ending, in the text."""
    stem = _stem(name)
    return len(stem) >= 3 and bool(
        re.search(rf"(?<!\w){re.escape(stem)}\w{{0,3}}(?!\w)", text.casefold())
    )


def entities_in(session: Session, project_id: str, text: str, named: list[str]) -> list[str]:
    """Cards that belong to a stretch of text: named by the model, or found by name."""
    wanted = {norm(n) for n in named if n.strip()}
    found = []
    for entity in session.scalars(select(Entity).where(Entity.project_id == project_id)):
        names = [entity.name, *entity.aliases]
        by_model = any(norm(n) in wanted for n in names)
        by_text = any(_mentions(text, n) for n in names)
        if by_model or by_text:
            found.append(entity.id)
    return found


def propose_scenes(session: Session, model: TextModel, chapter: Chapter) -> SceneSplit:
    """Ask the model for scene boundaries and keep them as the chapter's proposals. No card
    is made or removed here: the user picks a proposal (owner's notes 27.11, item 25)."""
    paragraphs = paragraphs_of(chapter)
    book = _project_title(session, chapter)
    numbered = "\n\n".join(
        f"[{n}] [heading] {text}" if is_heading(text, book, chapter.title) else f"[{n}] {text}"
        for n, text in enumerate(paragraphs)
    )
    headings = "\n".join(p for p in paragraphs if is_heading(p, book, chapter.title))
    answer = model.invoke_json(
        "split_scenes", [SystemMessage(SPLIT_SYSTEM), HumanMessage(numbered)], SceneDrafts
    )
    drafts = sorted(answer.scenes, key=lambda d: d.start)
    # The model's numbers are a suggestion; the result must tile the chapter exactly.
    spans: list[tuple[int, int, SceneDraft]] = []
    cursor = 0
    last = len(paragraphs) - 1
    for index, draft in enumerate(drafts):
        if cursor > last:
            break
        end = last if index == len(drafts) - 1 else min(max(draft.end, cursor), last)
        spans.append((cursor, end, draft))
        cursor = end + 1
    spans = _join_lead_ins(spans, paragraphs, book, chapter.title)
    proposals = []
    for start, end, draft in spans:
        text = _story_text(paragraphs[start : end + 1], book, chapter.title)
        # A name the model took from a title line is not someone in the scene either.
        named = [
            n
            for n in [*draft.characters, draft.location]
            if not (_mentions(headings, n) and not _mentions(text, n))
        ]
        proposals.append(
            {
                "from": start,
                "to": end,
                "title": draft.title.strip()[:300],
                "summary": draft.summary.strip(),
                "vivid": draft.vivid,
                "entity_ids": entities_in(session, chapter.project_id, text, named),
            }
        )
    split = session.get(SceneSplit, chapter.id) or SceneSplit(
        chapter_id=chapter.id, project_id=chapter.project_id
    )
    split.chapter_hash = chapter.content_hash
    split.proposals = proposals
    split.created_at = now()
    session.add(split)
    session.commit()
    return split


def scene_from_proposal(session: Session, chapter: Chapter, proposal: dict) -> Scene:
    """The card of a proposal the user picked; picked twice, it is the same card."""
    same = session.scalars(
        select(Scene).where(
            Scene.chapter_id == chapter.id,
            Scene.chapter_hash == chapter.content_hash,
            Scene.paragraph_from == proposal["from"],
            Scene.paragraph_to == proposal["to"],
            Scene.origin == "auto",
        )
    ).first()
    if same is not None:
        return same
    scene = Scene(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        chapter_hash=chapter.content_hash,
        paragraph_from=proposal["from"],
        paragraph_to=proposal["to"],
        title=proposal["title"],
        summary=proposal["summary"],
        vivid=proposal["vivid"],
        origin="auto",
        entity_ids=list(proposal["entity_ids"]),
    )
    session.add(scene)
    session.commit()
    return scene


# A stretch with less story than this is a line or two of lead-in, not a scene to film.
LEAD_IN_CHARS = 60


def _join_lead_ins(
    spans: list[tuple[int, int, SceneDraft]], paragraphs: list[str], book: str, title: str
) -> list[tuple[int, int, SceneDraft]]:
    """Join a stretch with almost no story to the scene after it (the last one to the scene
    before), keeping that scene's title and description: owner's notes 26.11, a prologue
    line "a miracle happened" became a second card about the same falling star."""
    joined = list(spans)
    n = 0
    while len(joined) > 1 and n < len(joined):
        start, end, _ = joined[n]
        if len(_story_text(paragraphs[start : end + 1], book, title)) >= LEAD_IN_CHARS:
            n += 1
            continue
        if n + 1 < len(joined):
            _, next_end, draft = joined[n + 1]
            joined[n : n + 2] = [(start, next_end, draft)]
            n += 1  # joined once: a run of short lines must not melt into one scene (review)
        else:
            before_start, _, draft = joined[n - 1]
            joined[n - 1 : n + 1] = [(before_start, end, draft)]
            break
    return joined


def mark_scene(session: Session, chapter: Chapter, start: int, end: int, title: str) -> Scene:
    """A scene the user marked in the reader. No model involved."""
    picked = paragraphs_of(chapter)[start : end + 1]
    text = "\n\n".join(picked)
    story = _story_text(picked, _project_title(session, chapter), chapter.title)
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
        entity_ids=entities_in(session, chapter.project_id, story, []),
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
    """The best main pictures (a face and a full-length view), and the look whose chapter
    range covers this chapter. Only pictures in the project's current style count."""
    key = style_key(project)
    positions = {c.id: c.position for c in project.chapters}
    current = [i for i in entity.images if i.style_key == key]
    picked = [(i, "main") for i in angles.for_scene(current, key)]

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


def _cast(session: Session, scene: Scene) -> list[Entity]:
    entities = [session.get(Entity, entity_id) for entity_id in scene.entity_ids]
    # Characters first: they matter most for consistency, and models take few pictures.
    return sorted((e for e in entities if e), key=lambda e: (e.kind != KIND_CHARACTER, e.name))


def _covers(project: Project, image: Image, chapter: Chapter) -> bool:
    positions = {c.id: c.position for c in project.chapters}
    start = positions.get(image.chapter_from_id, 0)
    end = positions.get(image.chapter_to_id, len(positions))
    return start <= chapter.position <= end


def candidates(
    session: Session, project: Project, scene: Scene, chapter: Chapter
) -> list[Reference]:
    """Everything the model may choose from: every base view in the current style and every
    look whose chapters cover this one."""
    key = style_key(project)
    result: list[Reference] = []
    for entity in _cast(session, scene):
        for image in angles.mains(entity.images, key):
            result.append(Reference(len(result) + 1, image, entity, "main"))
        for image in entity.images:
            if (
                image.style_key == key
                and not image.is_main
                and (image.look_label or image.chapter_from_id or image.chapter_to_id)
                and _covers(project, image, chapter)
            ):
                result.append(Reference(len(result) + 1, image, entity, "look"))
    return result


def references(
    session: Session, project: Project, scene: Scene, chapter: Chapter
) -> list[Reference]:
    """The pictures that go with the video prompt: those the model chose when it wrote it,
    or, before that (or when they are gone or out of style), a choice by fixed rules."""
    by_id = {r.image.id: r for r in candidates(session, project, scene, chapter)}
    chosen = [by_id[i] for i in scene.reference_ids if i in by_id]
    if not chosen:
        chosen = [
            Reference(0, image, entity, role)
            for entity in _cast(session, scene)
            for image, role in pick_images(project, entity, chapter)
        ]
    return [Reference(n, r.image, r.entity, r.role) for n, r in enumerate(chosen, 1)]


def missing_references(session: Session, project: Project, scene: Scene) -> list[dict]:
    """The pictures a scene would want and its cards do not have yet, by fixed rules and
    no model (owner's notes 26.11): a character's face and full-length view, one base
    picture of a place or object. Only pictures in the project's current style count."""
    key = style_key(project)
    missing = []
    for entity in _cast(session, scene):
        taken = {i.angle for i in angles.mains(entity.images, key)}
        has_main = bool(angles.mains(entity.images, key))
        if entity.kind == KIND_CHARACTER:
            needs = [
                need
                for need, views in (("face", angles.FACES), ("figure", angles.FIGURES))
                if not taken & set(views)
            ]
            # An animal or a bird has no face portraits, only views of its whole body.
            looks = entity.variants or []
            if looks and all(v.get("shape") == "creature" for v in looks):
                needs = [need for need in needs if need != "face"]
        else:
            needs = [] if has_main else ["base"]
        missing += [
            {"entity_id": entity.id, "name": entity.name, "kind": entity.kind, "need": need}
            for need in needs
        ]
    return missing


def choose_references(
    session: Session, project: Project, scene: Scene, chapter: Chapter, image_ids: list[str]
) -> None:
    """The user's own choice of the pictures that go with the scene (owner's notes 26.11),
    in the given order. Only pictures the scene may use count."""
    allowed = {r.image.id for r in candidates(session, project, scene, chapter)}
    scene.reference_ids = [i for i in dict.fromkeys(image_ids) if i in allowed]


# ---------- prompt ----------


def _facts_at(project: Project, entity: Entity, chapter: Chapter) -> tuple[list[str], list[str]]:
    """Permanent traits, and the state as of this chapter: its own state facts, or
    those of the nearest earlier chapter that has any."""
    positions = {c.id: c.position for c in project.chapters}
    # The card's coherent appearance first (the user's own wins), then the separate traits.
    appearance = entity.appearance_own.strip() or entity.appearance.strip()
    permanent = [
        *([appearance] if appearance else []),
        *(f.text for f in entity.facts if f.category == FACT_PERMANENT),
    ]
    earlier = [
        f
        for f in entity.facts
        if f.category == FACT_STATE and positions.get(f.chapter_id, -1) <= chapter.position
    ]
    if not earlier:
        return permanent, []
    latest = max(positions.get(f.chapter_id, -1) for f in earlier)
    return permanent, [f.text for f in earlier if positions.get(f.chapter_id) == latest]


def _label(ref: Reference) -> str:
    if ref.role == "look":
        return f"look: {ref.image.look_label}" if ref.image.look_label else "look for this chapter"
    return ", ".join(filter(None, ["base", ref.image.angle]))


def scene_context(
    session: Session,
    project: Project,
    scene: Scene,
    chapter: Chapter,
    note: str,
    refs: list[Reference],
) -> str:
    lines = ["Scene text:", scene_text(scene, chapter), ""]
    for entity_id in scene.entity_ids:
        entity = session.get(Entity, entity_id)
        if entity is None:
            continue
        permanent, state = _facts_at(project, entity, chapter)
        numbers = [f"reference {r.number} ({_label(r)})" for r in refs if r.entity.id == entity.id]
        kind = {KIND_CHARACTER: "Character", KIND_ITEM: "Item"}.get(entity.kind, "Location")
        lines.append(f"{kind}: {entity.name} - {', '.join(numbers) or 'no reference picture'}")
        lines += [f"  permanent: {t}" for t in permanent]
        lines += [f"  at this point: {t}" for t in state]
        # How it behaves, speaks and moves: for the acting in the video (owner's notes, item 28).
        if entity.temper.strip():
            lines.append(f"  nature: {' '.join(entity.temper.split())}")
    if note.strip():
        lines += ["", f"Author's note: {note.strip()}"]
    return "\n".join(lines)


_REFERENCE = re.compile(r"\b(references?\s+)(\d+)\b", re.IGNORECASE)


def _renumbered(prompt: str, numbers: list[int], pool: list[Reference]) -> tuple[str, list[str]]:
    """The prompt with the pool's numbers turned into 1, 2... in the order the pictures go
    into the archive, and their ids. A picture the prompt names counts as chosen even if the
    list forgot it."""
    named = {int(m.group(2)) for m in _REFERENCE.finditer(prompt)}
    chosen = [r for r in pool if r.number in {*numbers, *named}]
    new_number = {r.number: n for n, r in enumerate(chosen, 1)}
    prompt = _REFERENCE.sub(
        lambda m: m.group(1) + str(new_number.get(int(m.group(2)), m.group(2))), prompt
    )
    return prompt, [r.image.id for r in chosen]


def video_prompt(
    session: Session, model: TextModel, project: Project, scene: Scene, note: str
) -> tuple[str, list[str]]:
    """The prompt and the ids of the pictures it refers to, renumbered from 1 in the
    order they go into the archive."""
    chapter = session.get(Chapter, scene.chapter_id)
    pool = candidates(session, project, scene, chapter)
    system = VIDEO_SYSTEM.format(style=style_prompt(project) or "(no style chosen: omit this part)")
    context = scene_context(session, project, scene, chapter, note, pool)
    answer = model.invoke_json(
        "video_prompt", [SystemMessage(system), HumanMessage(context)], VideoAnswer
    )
    return _renumbered(answer.prompt.strip(), answer.references, pool)


def refine_prompt(
    session: Session, model: TextModel, project: Project, scene: Scene, change: str
) -> tuple[str, list[str]]:
    """The author's change to the video prompt, said in the scene's dialogue: it may also
    take a reference picture in or leave one out (owner's notes 27.11, scene dialogue)."""
    chapter = session.get(Chapter, scene.chapter_id)
    pool = candidates(session, project, scene, chapter)
    by_id = {r.image.id: r for r in pool}
    # The prompt counts its pictures from 1 in the scene's order; the model sees the pool's.
    current = [by_id[i] for i in scene.reference_ids if i in by_id]
    to_pool = {n: r.number for n, r in enumerate(current, 1)}
    prompt = _REFERENCE.sub(
        lambda m: m.group(1) + str(to_pool.get(int(m.group(2)), m.group(2))), scene.prompt
    )
    used = ", ".join(str(r.number) for r in current) or "none"
    request = "\n".join(
        [
            scene_context(session, project, scene, chapter, "", pool),
            "",
            f"Pictures the prompt uses now: {used}",
            "",
            f"Prompt:\n{prompt}",
            "",
            f"Change wanted:\n{change}",
        ]
    )
    answer = model.invoke_json(
        "refine_prompt", [SystemMessage(REFINE_SYSTEM), HumanMessage(request)], VideoAnswer
    )
    return _renumbered(answer.prompt.strip(), answer.references, pool)


ENRICH_SYSTEM = """You help an author turn a scene of their book into a film scene. Below \
are the scene's current description, its text in the book, the paragraphs around it and \
who is in it.

Write the description again, keeping everything it already says, and add what the book \
does not say but what fits naturally: what the characters present do with their hands and \
bodies, small actions between the lines, details of the place, light and sound, what \
happens in the background. Every addition must agree with the book and the surrounding \
paragraphs; add no new characters, no new events that change the story and nothing about \
later chapters. Write in the language of the book, as plain prose, at most 10 sentences. \
When the author's wishes are given at the end, add above all what they ask for.

Reply with one JSON object and nothing else:
{"text": "the whole new description", "added": ["each added fragment, copied exactly as it \
stands in text"], "why": "one or two sentences: what you added and why it fits"}"""


class EnrichAnswer(BaseModel):
    text: str
    added: list[str] = Field(default_factory=list)
    why: str = ""


def enrich_scene(
    session: Session,
    model: TextModel,
    project: Project,
    scene: Scene,
    chapter: Chapter,
    wishes: str = "",
) -> EnrichAnswer:
    """Suggested additions to the scene's description; nothing is saved here: the author
    sees them marked and applies them or not (owner's notes 25.11)."""
    paragraphs = paragraphs_of(chapter)
    book, title = project.title, chapter.title

    def around(start: int, end: int) -> str:
        return _story_text(paragraphs[max(start, 0) : max(end, 0)], book, title)

    cast = [session.get(Entity, entity_id) for entity_id in scene.entity_ids]
    lines = [
        "Current description:",
        scene.summary.strip() or "(none yet)",
        "",
        "Scene text:",
        _story_text(paragraphs[scene.paragraph_from : scene.paragraph_to + 1], book, title),
        "",
        "Before the scene:",
        around(scene.paragraph_from - 4, scene.paragraph_from) or "(start of the chapter)",
        "",
        "After the scene:",
        around(scene.paragraph_to + 1, scene.paragraph_to + 5) or "(end of the chapter)",
        "",
        "In the scene:",
    ]
    for entity in cast:
        if entity is None:
            continue
        permanent, state = _facts_at(project, entity, chapter)
        lines.append(f"- {entity.name}: " + "; ".join([*permanent, *state][:6]))
    if wishes.strip():
        lines += ["", f"Author's wishes: {wishes.strip()}"]
    answer = model.invoke_json(
        "enrich_scene",
        [SystemMessage(ENRICH_SYSTEM), HumanMessage("\n".join(lines))],
        EnrichAnswer,
    )
    text = answer.text.strip()
    # Only fragments really in the text can be marked.
    added = [a.strip() for a in answer.added if a.strip() and a.strip() in text]
    return EnrichAnswer(text=text, added=added, why=answer.why.strip())


def frame_prompt(prompt: str) -> str:
    """The still that a video model animates from: the same shot, frozen at its start."""
    return (
        "A single still frame, the opening moment of the first shot, no motion blur, "
        f"no text: {prompt}"
    )


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
            label = (
                slug(ref.image.look_label)
                if ref.role == "look"
                else "_".join(filter(None, ["main", ref.image.angle]))
            )
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
