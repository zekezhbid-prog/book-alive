"""Checks of the manuscript for the writer: language, editorial polish, contradictions.

Nothing here changes the book or is stored: the result is a list of remarks the author
reads and decides on. Every quote shown is verified against the text it came from; a remark
whose quote cannot be found is dropped, never displayed."""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.entities import locate_quote
from app.llm.calls import TextModel
from app.models import Chapter, Entity, EntityFact, Project
from app.review import prompts

KIND_GRAMMAR = "grammar"
KIND_EDITORIAL = "editorial"
KIND_CONTRADICTIONS = "contradictions"
KINDS = (KIND_GRAMMAR, KIND_EDITORIAL, KIND_CONTRADICTIONS)

WINDOW_CHARS = 6000  # text sent in one call; remarks come back more precise on short pieces
FACTS_CHARS = 20_000  # facts of several cards sent in one contradictions call
MAX_REMARKS = 200


class Place(BaseModel):
    chapter_id: str
    chapter_title: str
    paragraph: int | None = None
    quote: str


class Remark(BaseModel):
    category: str
    problem: str
    suggestion: str = ""
    places: list[Place]


class _RawRemark(BaseModel):
    paragraph: int
    quote: str
    category: str = ""
    problem: str
    suggestion: str = ""


class _TextAnswer(BaseModel):
    remarks: list[_RawRemark] = Field(default_factory=list)


class _RawContradiction(BaseModel):
    facts: list[int]
    problem: str
    suggestion: str = ""


class _ContradictionAnswer(BaseModel):
    contradictions: list[_RawContradiction] = Field(default_factory=list)


def windows(paragraphs: list[str], limit: int = WINDOW_CHARS) -> list[list[int]]:
    """Paragraph numbers grouped into pieces of about `limit` characters."""
    pieces: list[list[int]] = []
    current: list[int] = []
    size = 0
    for index, paragraph in enumerate(paragraphs):
        if current and size + len(paragraph) > limit:
            pieces.append(current)
            current, size = [], 0
        current.append(index)
        size += len(paragraph)
    return [*pieces, current] if current else pieces


def check_text(model: TextModel, chapter: Chapter, kind: str) -> list[Remark]:
    """Grammar or editorial remarks for one chapter, with verified quotes."""
    paragraphs = chapter.text.split("\n\n") if chapter.text else []
    system = prompts.GRAMMAR if kind == KIND_GRAMMAR else prompts.EDITORIAL
    remarks: list[Remark] = []
    for piece in windows(paragraphs):
        body = "\n\n".join(f"[{i}] {paragraphs[i]}" for i in piece if paragraphs[i].strip())
        if not body:
            continue
        answer = model.invoke_json(
            f"review_{kind}", [SystemMessage(system), HumanMessage(body)], _TextAnswer
        )
        for raw in answer.remarks:
            index = raw.paragraph if raw.paragraph in piece else None
            if index is None or locate_quote(raw.quote, [paragraphs[index]]) is None:
                # The model may give a wrong paragraph number: search the whole piece.
                found = locate_quote(raw.quote, [paragraphs[i] for i in piece])
                if found is None:
                    continue
                index = piece[found]
            remarks.append(
                Remark(
                    category=raw.category,
                    problem=raw.problem,
                    suggestion=raw.suggestion,
                    places=[
                        Place(
                            chapter_id=chapter.id,
                            chapter_title=chapter.title,
                            paragraph=index,
                            quote=raw.quote.strip(),
                        )
                    ],
                )
            )
    return remarks[:MAX_REMARKS]


def check_contradictions(session: Session, model: TextModel, project: Project) -> list[Remark]:
    """Contradictions between what different chapters say about the same card. Works on the
    stored facts, whose quotes were verified when they were found."""
    titles = {c.id: c.title for c in project.chapters}
    order = {c.id: c.position for c in project.chapters}
    entities = session.scalars(select(Entity).where(Entity.project_id == project.id)).all()

    blocks: list[tuple[str, dict[int, EntityFact]]] = []
    counter = 0
    for entity in sorted(entities, key=lambda e: e.name):
        facts = sorted(
            (f for f in entity.facts if f.chapter_id in titles),
            key=lambda f: order[f.chapter_id],
        )
        if len(facts) < 2:
            continue
        lines: list[str] = []
        local: dict[int, EntityFact] = {}
        for fact in facts:
            counter += 1
            local[counter] = fact
            lines.append(f"[{counter}] ({titles[fact.chapter_id]}) {fact.text}")
        blocks.append((f"## {entity.name} ({entity.kind})\n" + "\n".join(lines), local))

    batches: list[tuple[str, dict[int, EntityFact]]] = []
    text, bag = "", {}
    for block, local in blocks:
        if text and len(text) + len(block) > FACTS_CHARS:
            batches.append((text, bag))
            text, bag = "", {}
        text = f"{text}\n\n{block}" if text else block
        bag = {**bag, **local}
    if text:
        batches.append((text, bag))

    remarks: list[Remark] = []
    for text, bag in batches:
        answer = model.invoke_json(
            f"review_{KIND_CONTRADICTIONS}",
            [SystemMessage(prompts.CONTRADICTIONS), HumanMessage(text)],
            _ContradictionAnswer,
        )
        for raw in answer.contradictions:
            facts = [bag[n] for n in dict.fromkeys(raw.facts) if n in bag]
            if len(facts) < 2:
                continue
            remarks.append(
                Remark(
                    category="contradiction",
                    problem=raw.problem,
                    suggestion=raw.suggestion,
                    places=[_place(titles, f) for f in facts],
                )
            )
    return remarks[:MAX_REMARKS]


def _place(titles: dict[str, str], fact: EntityFact) -> Place:
    return Place(
        chapter_id=fact.chapter_id,
        chapter_title=titles.get(fact.chapter_id, ""),
        paragraph=fact.paragraph,
        quote=fact.quote or fact.text,
    )
