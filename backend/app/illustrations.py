"""The "Pictures" section: an illustration of the book made in a dialogue.

The user says what to draw (typed or spoken). The text model, given passages the search
found for it, picks the moment of the book, who and what is in it and writes the image
prompt, or asks back when the request is unclear. The cards it names lend their base
pictures as references. Drawing is a separate press, so the user sees the plan first."""

import re

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.entities import norm
from app.images import angles
from app.images.styles import style_key, style_prompt
from app.llm.calls import TextModel
from app.models import KIND_CHARACTER, Entity, Illustration, Image, Project
from app.rag.index import index_project, search
from app.scenes.service import _mentions, is_heading

PLAN_SYSTEM = """You help an author make an illustration of their book. You get the \
conversation so far, passages of the book found for the request and the cards of those \
who may be in it.

Decide what to draw:
- Find the moment of the book the user means, using the passages. When the request points \
to no clear moment, the passages do not fit it, or it can be read in several ways, ask one \
short question in the user's language instead and leave "prompt" empty.
- "chapter": the title of that moment's chapter, exactly as given, or "".
- "cast": names of cards, exactly as listed, of those really in the picture: people, \
places, things. Never take a name from a title of the book or a chapter.
- "say": one or two sentences to the user, in the user's language: which moment you found \
and who and what you will draw.
- "prompt": an English prompt for an image generator, one paragraph under 140 words: the \
moment, the place, the light, the composition. Write [[Name]] for a card marked \
"has pictures" (its pictures are sent along); describe everyone else by how they look. \
A later message of the user changes the last picture: keep what they did not ask to change.
- End the prompt with the style, word for word: {style}

Reply with one JSON object and nothing else:
{{"question": "", "chapter": "", "cast": [], "say": "", "prompt": ""}}"""


class Plan(BaseModel):
    question: str = ""
    chapter: str = ""
    cast: list[str] = Field(default_factory=list)
    say: str = ""
    prompt: str = ""


def _cards(session: Session, project: Project, text: str) -> list[Entity]:
    """Cards named in the request or the passages: the only ones offered to the model."""
    cards = session.scalars(select(Entity).where(Entity.project_id == project.id)).all()
    return [c for c in cards if any(_mentions(text, n) for n in [c.name, *c.aliases])][:30]


def _pictures(entity: Entity, key: str) -> list[Image]:
    return angles.for_scene(entity.images, key)[:1]


def plan(session: Session, model: TextModel, project: Project, item: Illustration) -> dict:
    """The next assistant message: a question, or a plan with the prompt and references."""
    asked = " ".join(m["text"] for m in item.messages if m["role"] == "user")
    index_project(session, project)
    passages = search(session, project.id, item.messages[-1]["text"], limit=6)
    titles = {c.id: c.title for c in project.chapters}
    found = "\n\n".join(
        f"[{p.chapter_title or titles.get(p.chapter_id, '')}]\n"
        + "\n".join(
            line
            for line in p.text.split("\n\n")
            if not is_heading(line, project.title, p.chapter_title)
        )
        for p in passages
    )
    key = style_key(project)
    cards = _cards(session, project, f"{asked}\n{found}")
    card_lines = [
        f"- {c.name} ({c.kind}{', has pictures' if _pictures(c, key) else ''}): "
        + " ".join((c.appearance_own or c.appearance or c.summary).split())[:300]
        for c in cards
    ]
    talk = [
        f"{'User' if m['role'] == 'user' else 'You'}: {m.get('text') or '(picture drawn)'}"
        + (f"\n  prompt used: {m['prompt']}" if m.get("prompt") else "")
        for m in item.messages
    ]
    request = "\n".join(
        [
            "Conversation:",
            *talk,
            "",
            "Passages:",
            found or "(nothing found)",
            "",
            "Cards:",
            *(card_lines or ["(none)"]),
        ]
    )
    system = PLAN_SYSTEM.format(style=style_prompt(project) or "(no style chosen: omit it)")
    answer = model.invoke_json(
        "illustration_plan", [SystemMessage(system), HumanMessage(request)], Plan
    )
    if answer.question.strip() or not answer.prompt.strip():
        return {"role": "assistant", "text": answer.question.strip() or answer.say.strip()}
    by_name = {norm(n): c for c in cards for n in [c.name, *c.aliases]}
    cast = [by_name[norm(n)] for n in answer.cast if norm(n) in by_name]
    references: list[Image] = []
    prompt = answer.prompt.strip()
    for card in dict.fromkeys(cast):
        pictures = _pictures(card, key)
        tag = f"[[{card.name}]]"
        if pictures and len(references) < angles.DRAWING_LIMIT:
            references.append(pictures[0])
            what = "figure" if card.kind == KIND_CHARACTER else "place or thing"
            prompt = prompt.replace(tag, f"the {what} from reference {len(references)}")
    # A name left in brackets (no picture, or over the limit) is just the name.
    prompt = re.sub(r"\[\[([^\]]+)\]\]", r"\1", prompt)
    chapter = next((c for c in project.chapters if c.title == answer.chapter.strip()), None)
    return {
        "role": "assistant",
        "text": answer.say.strip(),
        "prompt": prompt,
        "chapter_id": chapter.id if chapter and not chapter.private else "",
        "cast": [c.name for c in dict.fromkeys(cast)],
        "reference_ids": [r.id for r in references],
    }
