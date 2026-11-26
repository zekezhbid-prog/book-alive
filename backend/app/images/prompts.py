"""Turning a card (facts in the book's language) into an English image prompt."""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.images.angles import ANGLES
from app.images.styles import style_prompt
from app.llm.calls import TextModel
from app.models import (
    FACT_PERMANENT,
    FACT_PROFILE,
    FACT_STATE,
    KIND_CHARACTER,
    KIND_ITEM,
    Chapter,
    Entity,
    Project,
    new_id,
)

SYSTEM = """You write one prompt for an AI image generator. The picture is a reference \
sheet image of a {subject} from a book, used later to keep it looking the same in every scene.

Rules:
- English only, one paragraph, under 120 words, no line breaks, no quotation marks.
- {framing}
- Use the facts below and nothing that contradicts them. Translate them faithfully. \
Where the facts are silent, stay neutral rather than inventing striking details.
- {visible}
- {continuity}
- {age}
- End with the style, word for word: {style}

Reply with the prompt only."""

# A set of base pictures shares one prompt; each picture gets its view put in front of it.
VIEW_FREE = (
    "Describe the appearance only. Do not mention the view, pose, framing, background or "
    "light: they are added to each picture of the set separately."
)

FRAMING = {
    "character": "Full-body view of the character alone, standing, neutral pose, plain "
    "uncluttered background, even light, face clearly visible.",
    "location": "Wide establishing view of the place with no people, showing its overall "
    "shape, materials and surroundings.",
    "item": "The object alone, whole and clearly visible, on a plain uncluttered background, "
    "even light, no people.",
}


def chapters_between(project: Project, from_id: str, to_id: str) -> list[Chapter]:
    """Chapters of a look's range, in book order. An open end means "to the edge"."""
    ordered = sorted((c for c in project.chapters if not c.private), key=lambda c: c.position)
    by_id = {c.id: c.position for c in ordered}
    low = by_id.get(from_id, 0)
    high = by_id.get(to_id, len(ordered))
    return [c for c in ordered if low <= c.position <= high]


def build_image_prompt(
    model: TextModel,
    project: Project,
    entity: Entity,
    chapters: list[Chapter] | None,
    look_label: str,
    has_reference: bool,
    angle: str = "",
    view_free: bool = False,
    note: str = "",
    variant: dict | None = None,
) -> str:
    """`chapters` given: a look at that point of the story (its state facts are used).
    None: a main picture, from permanent traits only, in the given view, or with
    `view_free` in none, for a set of views drawn from one prompt. `note` is the user's
    own wish for this picture ("a view from above")."""
    permanent = [f.text for f in entity.facts if f.category == FACT_PERMANENT]
    state: list[str] = []
    if chapters is not None:
        ids = {c.id for c in chapters}
        state = [f.text for f in entity.facts if f.category == FACT_STATE and f.chapter_id in ids]
    appearance = entity.appearance_own.strip() or entity.appearance.strip()
    who = ""
    if entity.kind == KIND_CHARACTER:
        who = " ".join((entity.description or entity.summary).split())[:400]
    if variant is not None and chapters is None:
        # One outward look of several: only its own description, so the model cannot mix in
        # the others (owner's notes 25.11: a kerchief and loose hair in one picture).
        appearance, permanent = variant.get("description", ""), []
        who = f"{who} (shown here as: {variant.get('label', '')})".strip()
    facts = "\n".join(
        [
            f"Name: {entity.name}",
            # The coherent picture first; the facts below add detail and the quoted wording.
            *([f"Appearance: {appearance}"] if appearance else []),
            # Who it is often tells the age (a boy, a grandmother) when the looks do not.
            *([f"Who it is: {who}"] if who else []),
            *(
                ["Permanent traits:", *(f"- {t}" for t in permanent or ["(none described)"])]
                if variant is None or chapters is not None
                else []
            ),
            *(["At this point of the story:", *(f"- {t}" for t in state)] if state else []),
            *([f"The look to show: {look_label}"] if look_label else []),
            *([f"The user asks for: {note.strip()}"] if note.strip() else []),
        ]
    )
    same = (
        "the face, build and identity"
        if entity.kind == KIND_CHARACTER
        else "its shape, materials, colours and details"
    )
    continuity = (
        f"Reference pictures of the same one are supplied with the prompt: say that {same} "
        "must match the references exactly, and describe only what differs."
        if has_reference
        else "No reference picture exists yet: describe the appearance completely."
    )
    age = (
        "A person or human-like being: start with the age and sex as the facts give them "
        "(a 14-year-old boy, an old woman of about 70). A child or teenager is drawn as one, "
        "with a young face and body, never with a beard or moustache unless the facts say so."
        if entity.kind == KIND_CHARACTER
        else "No people in the picture."
    )
    # Owner's notes 25.11: a limp or a voice in the facts has no place in a picture.
    visible = (
        "Only what shows in a still picture: body, face, hair, skin, clothing, things worn "
        "or carried. Leave out the voice, the way of walking or moving (a limp, a gait), "
        "smell, manner, habits, character, past and anything else not seen standing still."
        if entity.kind == KIND_CHARACTER
        else "Only what shows in a still picture: leave out sounds, smells, history and use."
    )
    system = SYSTEM.format(
        age=age,
        visible=visible,
        subject={KIND_CHARACTER: "character", KIND_ITEM: "object"}.get(entity.kind, "location"),
        framing=VIEW_FREE if view_free else ANGLES.get(angle) or FRAMING[entity.kind],
        continuity=continuity,
        style=style_prompt(project) or "(no style chosen: omit this part)",
    )
    return model.invoke("image_prompt", [SystemMessage(system), HumanMessage(facts)]).strip()


# ---------- the prompt in the user's language, and changes asked in words ----------

LANGUAGES = {"en": "English", "ru": "Russian", "by": "Belarusian"}

TRANSLATE_SYSTEM = """Translate this prompt for an AI image generator into {language}. \
Keep its meaning, order and every detail; do not add, drop or explain anything. Names of \
styles and technical words that have no good {language} equivalent stay as they are.

Reply with the translation only."""

REFINE_SYSTEM = """Below is a prompt for an AI image generator and a change the author \
wants, in any language. Rewrite the prompt in English with that change and keep everything \
else as it is, including the style at the end.

Reply with the prompt only."""


def translate_prompt(model: TextModel, text: str, language: str) -> str:
    """The prompt in another language: the user reads and edits it in theirs, the image
    model gets the English one."""
    system = TRANSLATE_SYSTEM.format(language=LANGUAGES[language])
    return model.invoke("translate_prompt", [SystemMessage(system), HumanMessage(text)]).strip()


def refine_image_prompt(model: TextModel, prompt: str, change: str) -> str:
    request = f"Prompt:\n{prompt}\n\nChange wanted:\n{change}"
    return model.invoke(
        "refine_image_prompt", [SystemMessage(REFINE_SYSTEM), HumanMessage(request)]
    ).strip()


VARIANTS_SYSTEM = """Below is everything a book says about how one character looks. Decide \
whether the character has more than one distinct outward look that must be drawn as \
separate reference sheets: the same person dressed or groomed in clearly different ways (in \
a kerchief and with loose hair), or one being that appears under several names and shapes \
(a girl who turns into a boy, a cat or a seed). Read the facts about who the character is \
as well: a change of shape or a second name is often told there, not among the looks. Small \
changes of clothes in one scene are not separate looks.

For each look give:
- "label": a few words in the language of the book, with the name used for that look \
when the book has one;
- "description": how the character looks in this look only, in the language of the book, \
from the facts, without anything from the other looks;
- "shape": "human" for a person or a human-like body, "creature" for an animal, a bird or \
another beast (a wolf cub, a kitten, a dove), "object" for something closer to a thing (a \
seed, a stone, a lantern).

Give one look only when the book really shows just one. Reply with one JSON object and nothing else:
{"variants": [{"label": "", "description": "", "shape": "human"}]}"""


class VariantDraft(BaseModel):
    label: str
    description: str = ""
    shape: str = "human"


class VariantDrafts(BaseModel):
    variants: list[VariantDraft] = Field(default_factory=list)


def find_variants(model: TextModel, entity: Entity) -> list[dict]:
    """The character's outward looks, each with its own description: what a set of base
    pictures is drawn for. Keys are new; the caller decides what to keep."""
    lines = [
        f"Name: {entity.name}",
        *([f"Other names: {', '.join(entity.aliases)}"] if entity.aliases else []),
        *([f"Appearance: {a}"] if (a := entity.appearance_own or entity.appearance) else []),
        *([f"Who it is: {w}"] if (w := entity.description or entity.summary) else []),
        "Facts:",
        # Who the character is: a change of shape or a second name is often told there.
        *(
            f"- {f.text}"
            for f in entity.facts
            if f.category in (FACT_PERMANENT, FACT_STATE, FACT_PROFILE)
        ),
    ]
    answer = model.invoke_json(
        "image_variants",
        [SystemMessage(VARIANTS_SYSTEM), HumanMessage("\n".join(lines))],
        VariantDrafts,
    )
    return [
        {
            "key": new_id()[:8],
            "label": draft.label.strip()[:120],
            "description": draft.description.strip()[:2000],
            "shape": draft.shape if draft.shape in ("object", "creature") else "human",
        }
        for draft in answer.variants
        if draft.label.strip()
    ][:8]


VIEWS_SYSTEM = """Below is what a book says about one {subject}. Propose the views a set of \
reference pictures of it should have, so that any scene can later be drawn from them. Pick \
what suits this {subject}: a castle may need a view from above, from the front, from the \
back and from both sides; a room an overall view and a view towards the door; a sword the \
whole blade and a close-up of the hilt. Two to six views, the most useful first.

For each view give:
- "label": two or three words in the language of the book, as a button caption;
- "framing": one English sentence for an image generator that sets the camera and the \
framing only (Aerial view from high above, the whole place visible.), nothing about how \
the {subject} looks.

Reply with one JSON object and nothing else:
{{"views": [{{"label": "", "framing": ""}}]}}"""


class ViewDraft(BaseModel):
    label: str
    framing: str = ""


class ViewDrafts(BaseModel):
    views: list[ViewDraft] = Field(default_factory=list)


def find_views(model: TextModel, entity: Entity) -> list[dict]:
    """Views suited to a place or object (owner's notes 26.11): each one a base picture of
    its own. Keys are new; the caller decides what to keep."""
    subject = "object" if entity.kind == KIND_ITEM else "place"
    lines = [
        f"Name: {entity.name}",
        *([f"Appearance: {a}"] if (a := entity.appearance_own or entity.appearance) else []),
        *([f"What it is: {w}"] if (w := entity.description or entity.summary) else []),
        "Facts:",
        *(f"- {f.text}" for f in entity.facts if f.category == FACT_PERMANENT),
    ]
    answer = model.invoke_json(
        "image_views",
        [SystemMessage(VIEWS_SYSTEM.format(subject=subject)), HumanMessage("\n".join(lines))],
        ViewDrafts,
    )
    return [
        {
            "key": "v" + new_id()[:7],
            "label": draft.label.strip()[:60],
            "framing": draft.framing.strip()[:400],
        }
        for draft in answer.views
        if draft.label.strip() and draft.framing.strip()
    ][:6]
