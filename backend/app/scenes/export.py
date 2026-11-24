"""Scene export for video: one archive with everything a video generator, a voice tool and
an assistant with Remotion need to bring a scene to life. Nothing is generated here but
the text: the shot plan comes from the text model, the files are the card pictures as
they are (owner's notes, 24.11.2026)."""

import io
import json
import re
import zipfile

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.images.styles import style_prompt
from app.llm.calls import TextModel
from app.models import KIND_CHARACTER, KIND_ITEM, Chapter, Image, Project, Scene
from app.scenes.service import (
    Reference,
    _cast,
    _extension,
    _facts_at,
    _label,
    candidates,
    scene_text,
    slug,
)

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
# One generation of Seedance 2.0 and its kin: at most this long, at most this many pictures.
CLIP_SECONDS = 15
IMAGE_LIMIT = 9
FPS = 30

TAIL = (
    "Preserve exact likeness throughout. No beautification. Stable face throughout. "
    "No morphing. No deformation. No flickering. No ghosting. Realistic physics. 4K cinematic."
)
CAMERA_MOVES = (
    "static, slow push in, slow pull out, pan, tilt, tracking shot, orbital shot, crane shot, "
    "handheld, low angle, high angle, over the shoulder, crash zoom"
)


class ExportOptions(BaseModel):
    """What the export window asks before the plan is written; the rest comes from cards."""

    aspect: str = "16:9"
    duration: int = Field(default=15, ge=4, le=120)
    dialogue: bool = True
    narration: bool = False
    effects: str = Field(default="", max_length=300)
    palette: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=1000)
    images_per_clip: int = Field(default=5, ge=1, le=IMAGE_LIMIT)

    @field_validator("aspect")
    @classmethod
    def known_aspect(cls, value: str) -> str:
        if value not in ASPECTS:
            raise ValueError("unknown aspect")
        return value


class Subject(BaseModel):
    name: str
    look: str


class Line(BaseModel):
    speaker: str = ""
    text: str
    narration: bool = False


class Shot(BaseModel):
    start: float
    end: float
    shot_size: str = ""
    camera: str = ""
    action: str
    on_screen: list[str] = Field(default_factory=list)
    references: list[int] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    sound: str = ""
    script: str = ""


class Plan(BaseModel):
    language: str = ""
    setting: str = ""
    mood: str = ""
    palette: str = ""
    music: str = ""
    subjects: list[Subject] = Field(default_factory=list)
    shots: list[Shot]


PLAN_SYSTEM = """You plan a short video of one scene from a book, {duration} seconds long, \
format {aspect}. The video is made by an AI video generator in clips of up to {clip} seconds; \
each clip is generated on its own and remembers nothing of the others, so every person, \
place and object must be described the same way, word for word, every time.

Rules:
- "subjects": one entry per person, place or object that appears on screen. "look" is a \
plain English description (face, hair, build, age, clothes; for a place its shape, materials, \
light; for an object its form and material) built only from the facts given. Never invent a \
colour or a feature that is not in the facts. Names are labels only: the video model does not \
know the book.
- "setting": English, where and when: the place, time of day, weather, light.
- "shots": they follow each other from 0 to {duration} seconds without gaps, each 2 to 6 \
seconds. For each: "shot_size" (wide, medium, close-up, extreme close-up), "camera" (one of: \
{moves}), "action" in English (what is seen, what moves), "on_screen" (subject names), \
"references" (numbers of the pictures listed below that this shot needs: a face for a \
close-up, a full view for a wide shot; only from the list), "sound" (English, effects and \
ambience), "script" (one sentence in the language of the book: what happens in this shot).
- {dialogue}
- "mood" and "palette": English, concrete ("cold blue dusk, amber torchlight"). {palette}
- "music": English, one line, or an empty string.
- "language": the ISO code of the book's language ("be", "ru", "en").
- If the author's note below asks for something, it overrides your own choices.

Reply with one JSON object and nothing else:
{{"language": "", "setting": "", "mood": "", "palette": "", "music": "", \
"subjects": [{{"name": "", "look": ""}}], "shots": [{{"start": 0, "end": 4, "shot_size": "", \
"camera": "", "action": "", "on_screen": [], "references": [], "lines": [{{"speaker": "", \
"text": "", "narration": false}}], "sound": "", "script": ""}}]}}"""


def _dialogue_rule(options: ExportOptions) -> str:
    parts = []
    if options.dialogue:
        parts.append(
            '"lines": what the people on screen say in this shot, copied word for word from '
            "the scene text in the book's language, with the speaker's name; only lines that "
            "fit the shot's time (about 2.5 words a second)."
        )
    else:
        parts.append('"lines": no spoken lines, leave it empty')
    if options.narration:
        parts.append(
            'Add the narrator\'s lines too ("narration": true, no speaker), word for word '
            "from the scene text, where they fit."
        )
    return " ".join(parts)


def _context(
    session: Session, project: Project, scene: Scene, chapter: Chapter, pool: list[Reference]
) -> str:
    lines = ["Scene text:", scene_text(scene, chapter), ""]
    for entity in _cast(session, scene):
        permanent, state = _facts_at(project, entity, chapter)
        numbers = [f"{r.number} ({_label(r)})" for r in pool if r.entity.id == entity.id]
        kind = {KIND_CHARACTER: "Character", KIND_ITEM: "Object"}.get(entity.kind, "Place")
        lines.append(f"{kind}: {entity.name} - pictures: {', '.join(numbers) or 'none'}")
        lines += [f"  permanent: {t}" for t in permanent]
        lines += [f"  at this point: {t}" for t in state]
    return "\n".join(lines)


def plan_scene(
    session: Session,
    model: TextModel,
    project: Project,
    scene: Scene,
    chapter: Chapter,
    options: ExportOptions,
) -> tuple[Plan, list[Reference]]:
    pool = candidates(session, project, scene, chapter)
    palette = (
        f'The author wants this palette: "{options.palette}".'
        if options.palette.strip()
        else "Choose one that suits the scene and the style."
    )
    system = PLAN_SYSTEM.format(
        duration=options.duration,
        aspect=options.aspect,
        clip=CLIP_SECONDS,
        moves=CAMERA_MOVES,
        dialogue=_dialogue_rule(options),
        palette=palette,
    )
    context = _context(session, project, scene, chapter, pool)
    wishes = [
        f"Visual effects wanted: {options.effects.strip()}" if options.effects.strip() else "",
        f"Author's note: {options.note.strip()}" if options.note.strip() else "",
    ]
    context = "\n\n".join([context, *filter(None, wishes)])
    plan = model.invoke_json("scene_export", [SystemMessage(system), HumanMessage(context)], Plan)
    return tidy(plan, options.duration, len(pool)), pool


def tidy(plan: Plan, duration: int, pictures: int) -> Plan:
    """Shots in order, inside the video, none longer than a clip; references that exist."""
    shots = []
    for shot in sorted(plan.shots, key=lambda s: s.start):
        start = max(0.0, min(float(shot.start), float(duration)))
        end = min(float(shot.end), float(duration), start + CLIP_SECONDS)
        if end - start < 0.5:
            continue
        refs = [n for n in dict.fromkeys(shot.references) if 1 <= n <= pictures]
        shots.append(shot.model_copy(update={"start": start, "end": end, "references": refs}))
    return plan.model_copy(update={"shots": shots})


def clips_of(shots: list[Shot]) -> list[list[Shot]]:
    """Shots grouped into generations of at most CLIP_SECONDS each, in order."""
    clips: list[list[Shot]] = []
    for shot in shots:
        if clips and shot.end - clips[-1][0].start <= CLIP_SECONDS:
            clips[-1].append(shot)
        else:
            clips.append([shot])
    return clips


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


def verified(line: Line, source: str) -> bool:
    """A line counts as the book's own only if its words stand in the scene text."""
    return bool(_norm(line.text)) and _norm(line.text) in _norm(source)


def _clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def clip_prompt(
    shots: list[Shot],
    tags: list[tuple[str, Reference]],
    plan: Plan,
    project: Project,
    options: ExportOptions,
) -> str:
    """One generation in the order the video models read best: references, format, style,
    setting, timeline by seconds, the technical tail."""
    begin = shots[0].start
    length = round(shots[-1].end - begin)
    names = {n for shot in shots for n in shot.on_screen}
    lines = ["References:"]
    for tag, ref in tags:
        kind = "identity" if ref.entity.kind == KIND_CHARACTER else "appearance"
        lines.append(f"{tag} - strict {kind} reference for {ref.entity.name} ({_label(ref)})")
    if not tags:
        lines.append("(none)")
    lines += [
        "",
        f"Format: {options.aspect}, {length} seconds, stabilized cinematic camera.",
        f"Style: {style_prompt(project) or 'cinematic'}.",
        f"Palette and mood: {plan.palette or options.palette}. {plan.mood}".strip(),
        f"Setting: {plan.setting}",
        "",
        "Subjects (keep exactly as described in every shot):",
    ]
    lines += [f"- {s.name}: {s.look}" for s in plan.subjects if s.name in names or not names]
    lines += ["", "Timeline:"]
    for shot in shots:
        said = " ".join(
            f'{"Narrator" if line.narration else line.speaker or "Someone"} says: "{line.text}"'
            for line in shot.lines
        )
        lines.append(
            f"[{_clock(shot.start - begin)}-{_clock(shot.end - begin)}] "
            f"{shot.shot_size}, {shot.camera}. {shot.action} {said}".strip()
        )
        if shot.sound:
            lines.append(f"  Sound: {shot.sound}")
    if options.effects.strip():
        lines += ["", f"Effects: {options.effects.strip()}"]
    lines += ["", TAIL]
    return "\n".join(lines)


def _clip_tags(shots: list[Shot], pool: list[Reference], limit: int) -> list[tuple[str, Reference]]:
    by_number = {r.number: r for r in pool}
    wanted = [by_number[n] for shot in shots for n in shot.references if n in by_number]
    # People first: their faces drift most when a model gets too few pictures.
    unique = list({r.number: r for r in wanted}.values())
    unique.sort(key=lambda r: r.entity.kind != KIND_CHARACTER)
    return [(f"@Image{n}", ref) for n, ref in enumerate(unique[:limit], 1)]


def _file_name(ref: Reference) -> str:
    label = slug(ref.image.look_label) if ref.role == "look" else slug(_label(ref))
    return f"ref{ref.number:02d}_{slug(ref.entity.name)}_{label}{_extension(ref.image)}"


START_HERE = """# {title}

A scene from "{book}" ({chapter}), prepared in Lorebook for an AI video.
Format {aspect}, {duration} seconds, {clips} clip(s) of up to {clip} seconds.

## Files
- `scene.json`: the whole plan: subjects with their exact descriptions, shots with times,
  camera and references, spoken lines, clips and which picture goes under which tag.
- `clips/clipNN.txt`: a ready prompt for each generation (Seedance 2.0 style: `@ImageN` tags).
- `refs/`: the reference pictures. {frame}
- `script.md`: the scene by seconds in the language of the book.

## 1. Generate the clips
For each `clips/clipNN.txt`: upload the pictures listed for that clip in `scene.json`
(`clips[].images`) in the given order, so the first becomes `@Image1`, paste the prompt,
set the format {aspect} and the clip's length. If a generator takes fewer pictures, keep
the first ones: people come first. Save the result as `clips/clipNN.mp4`.

Keep the subjects identical between clips: the same pictures, the same description,
word for word. Do not shorten the subject lines of a prompt.

## 2. Voice
`scene.json` → `shots[].lines`: who speaks, the words, from which second. Language: `{language}`.
Generate one audio file per line (`voice/lineNN.mp3`): with free edge-tts (for example
the `remotion-voiceover-ru` skill for Russian) or a voice service such as ElevenLabs for
other languages. Keep one voice per speaker. Lines marked `"verified": false` are not word
for word from the book: check them.

## 3. Assemble in Remotion
Ask an assistant with Remotion (for example Claude Code) to:
1. create a composition {width}x{height}, {fps} fps, {duration} seconds;
2. put each `clips/clipNN.mp4` in a `<Sequence>` from its `start` second (`clips[]`);
3. put each line's audio in an `<Audio>` from its shot's `start` and add captions from the text;
4. add music and ambience from `music` and `shots[].sound` if wanted;
5. render to `scene.mp4`.
"""


def export_archive(
    session: Session,
    project: Project,
    scene: Scene,
    chapter: Chapter,
    plan: Plan,
    pool: list[Reference],
    options: ExportOptions,
) -> bytes:
    source = scene_text(scene, chapter)
    clips = clips_of(plan.shots)
    used = {
        tag_ref.number: tag_ref
        for shots in clips
        for _, tag_ref in _clip_tags(shots, pool, options.images_per_clip)
    }
    files = {number: _file_name(ref) for number, ref in sorted(used.items())}
    frame = session.scalars(
        select(Image).where(Image.scene_id == scene.id).order_by(Image.created_at.desc())
    ).first()
    width, height = ASPECTS[options.aspect]
    manifest = {
        "version": 1,
        "book": project.title,
        "chapter": chapter.title,
        "scene": scene.title,
        "language": plan.language,
        "aspect": options.aspect,
        "size": [width, height],
        "fps": FPS,
        "duration": options.duration,
        "style": style_prompt(project),
        "palette": plan.palette or options.palette,
        "mood": plan.mood,
        "music": plan.music,
        "setting": plan.setting,
        "effects": options.effects.strip(),
        "first_frame": f"frame{_extension(frame)}" if frame else None,
        "subjects": [s.model_dump() for s in plan.subjects],
        "references": [
            {
                "file": f"refs/{files[n]}",
                "subject": ref.entity.name,
                "kind": ref.entity.kind,
                "role": ref.role,
                "label": _label(ref),
            }
            for n, ref in sorted(used.items())
        ],
        "shots": [],
        "clips": [],
    }
    for n, shot in enumerate(plan.shots, 1):
        manifest["shots"].append(
            {
                "n": n,
                "start": shot.start,
                "end": shot.end,
                "shot_size": shot.shot_size,
                "camera": shot.camera,
                "action": shot.action,
                "on_screen": shot.on_screen,
                "references": [f"refs/{files[r]}" for r in shot.references if r in files],
                "sound": shot.sound,
                "script": shot.script,
                "lines": [
                    {**line.model_dump(), "start": shot.start, "verified": verified(line, source)}
                    for line in shot.lines
                ],
            }
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for n, shots in enumerate(clips, 1):
            tags = _clip_tags(shots, pool, options.images_per_clip)
            name = f"clips/clip{n:02d}.txt"
            bundle.writestr(name, clip_prompt(shots, tags, plan, project, options))
            manifest["clips"].append(
                {
                    "n": n,
                    "start": shots[0].start,
                    "end": shots[-1].end,
                    "prompt": name,
                    "video": f"clips/clip{n:02d}.mp4",
                    "images": [
                        {"tag": tag, "file": f"refs/{files[ref.number]}"} for tag, ref in tags
                    ],
                }
            )
        for number, name in files.items():
            bundle.write(settings.files_dir / used[number].image.path, f"refs/{name}")
        if frame is not None:
            bundle.write(settings.files_dir / frame.path, manifest["first_frame"])
        bundle.writestr("scene.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        script = [f"# {scene.title}", ""]
        for shot in plan.shots:
            script.append(f"**{_clock(shot.start)}-{_clock(shot.end)}** {shot.script}")
            script += [
                f"- {'Narrator' if line.narration else line.speaker}: «{line.text}»"
                for line in shot.lines
            ]
            script.append("")
        bundle.writestr("script.md", "\n".join(script))
        bundle.writestr(
            "START_HERE.md",
            START_HERE.format(
                title=scene.title,
                book=project.title,
                chapter=chapter.title,
                aspect=options.aspect,
                duration=options.duration,
                clips=len(clips),
                clip=CLIP_SECONDS,
                frame=(
                    f"`{manifest['first_frame']}`: the first frame, the start image of clip 1."
                    if frame
                    else ""
                ),
                language=plan.language or "the book's",
                width=width,
                height=height,
                fps=FPS,
            ),
        )
    return buffer.getvalue()
