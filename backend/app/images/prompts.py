"""Turning a card (facts in the book's language) into an English image prompt."""

from langchain_core.messages import HumanMessage, SystemMessage

from app.images.angles import ANGLES
from app.images.styles import style_prompt
from app.llm.calls import TextModel
from app.models import FACT_PERMANENT, FACT_STATE, KIND_CHARACTER, Chapter, Entity, Project

SYSTEM = """You write one prompt for an AI image generator. The picture is a reference \
sheet image of a {subject} from a book, used later to keep it looking the same in every scene.

Rules:
- English only, one paragraph, under 120 words, no line breaks, no quotation marks.
- {framing}
- Use the facts below and nothing that contradicts them. Translate them faithfully. \
Where the facts are silent, stay neutral rather than inventing striking details.
- {continuity}
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
}


def chapters_between(project: Project, from_id: str, to_id: str) -> list[Chapter]:
    """Chapters of a look's range, in book order. An open end means "to the edge"."""
    ordered = sorted(project.chapters, key=lambda c: c.position)
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
) -> str:
    """`chapters` given: a look at that point of the story (its state facts are used).
    None: a main picture, from permanent traits only, in the given view, or with
    `view_free` in none, for a set of views drawn from one prompt."""
    permanent = [f.text for f in entity.facts if f.category == FACT_PERMANENT]
    state: list[str] = []
    if chapters is not None:
        ids = {c.id for c in chapters}
        state = [f.text for f in entity.facts if f.category == FACT_STATE and f.chapter_id in ids]
    facts = "\n".join(
        [
            f"Name: {entity.name}",
            "Permanent traits:",
            *(f"- {t}" for t in permanent or ["(none described)"]),
            *(["At this point of the story:", *(f"- {t}" for t in state)] if state else []),
            *([f"The look to show: {look_label}"] if look_label else []),
        ]
    )
    continuity = (
        "Reference pictures of the same one are supplied with the prompt: say that the face, "
        "build and identity must match the references exactly, and describe only what differs."
        if has_reference
        else "No reference picture exists yet: describe the appearance completely."
    )
    system = SYSTEM.format(
        subject="character" if entity.kind == KIND_CHARACTER else "location",
        framing=VIEW_FREE if view_free else ANGLES.get(angle) or FRAMING[entity.kind],
        continuity=continuity,
        style=style_prompt(project) or "(no style chosen: omit this part)",
    )
    return model.invoke("image_prompt", [SystemMessage(system), HumanMessage(facts)]).strip()
