"""Rebuilding or improving one card across the whole book: its facts, description and
appearance, without touching any other card.

Improve (the default) keeps what the card has and only adds what a chapter says and the card
lacks, drops facts the author's notes contradict, and turns a note the text confirms into a
fact. Rebuild from scratch reads every chapter anew and replaces its facts."""

import re
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import prompts
from app.analysis.entities import (
    FACT_MENTION,
    ExtractedFact,
    chunks,
    describe_looks,
    keep_general,
    locate_quote,
    norm,
    supported,
    write_summaries,
)
from app.llm.calls import BadModelOutput, TextModel
from app.models import AnalysisRun, Chapter, Entity, EntityFact

PART_FACTS, PART_SUMMARY, PART_APPEARANCE = "facts", "summary", "appearance"
PARTS = (PART_FACTS, PART_SUMMARY, PART_APPEARANCE)
MODE_IMPROVE = "improve"


class CardFacts(BaseModel):
    present: bool = True
    facts: list[ExtractedFact] = Field(default_factory=list)


class Improvement(CardFacts):
    # Numbers of the known facts that are wrong, and of the author's notes the chapter states.
    wrong: list[int] = Field(default_factory=list)
    confirmed: list[int] = Field(default_factory=list)


class WishNote(BaseModel):
    # What the author states about the card itself; empty when the wish only asks for something.
    note: str = ""


def wish_note(model: TextModel, entity: Entity, wishes: str) -> str:
    """The part of the wishes worth keeping as a note: what the author says about the card
    ("she is one year old"), not what they ask for ("this is Anya", "add her looks").
    A broken answer keeps the whole wish: better a long note than a lost one."""
    try:
        answer = model.invoke_json(
            "wish_note",
            [
                SystemMessage(prompts.WISH_NOTE_SYSTEM),
                HumanMessage(f'Card: "{entity.name}"\n\nWishes: {wishes}'),
            ],
            WishNote,
        )
    except BadModelOutput:
        return wishes
    return answer.note.strip()


def _stems(name: str) -> list[str]:
    """The words of a name cut to a stem, so "Тараса" and "Тарасу" match "Тарас"."""
    words = [w for w in re.findall(r"\w+", name.casefold()) if len(w) >= 3]
    return [w[:-2] if len(w) > 5 else w[:-1] if len(w) > 3 else w for w in words]


def name_matcher(entity: Entity) -> Callable[[str], bool]:
    """Tells whether a text names the card by any of its proper names (in any case form).
    A card known only by a common word ("the old man") never matches."""
    names = [n for n in {entity.name, *entity.aliases, *entity.pinned_names} if n[:1].isupper()]
    stems = [s for s in (_stems(n) for n in names) if s]

    def names_it(text: str) -> bool:
        low = text.casefold()
        return any(all(stem in low for stem in name) for name in stems)

    return names_it


def card_chapters(session: Session, entity: Entity) -> list[Chapter]:
    """Chapters where the card already has facts, and those that name it: the rest of the
    book is not worth paying for. A card known only by a common word ("the old man") is
    looked for where it was found before."""
    chapters = session.scalars(
        select(Chapter).where(Chapter.project_id == entity.project_id).order_by(Chapter.position)
    ).all()
    had = {f.chapter_id for f in entity.facts}
    names_it = name_matcher(entity)
    return [
        c
        for c in chapters
        if not c.private and c.text.strip() and (c.id in had or names_it(c.text))
    ]


def _target(entity: Entity) -> str:
    also = f" (also called: {', '.join(entity.aliases)})" if entity.aliases else ""
    hint = (entity.description or entity.summary).split(". ")[0].strip()[:200]
    notes = "; ".join(" ".join(n.split()) for n in entity.author_notes or [] if n.strip())
    return (
        f'"{entity.name}"{also}'
        + (f" - {hint}" if hint else "")
        + (f" (the author says: {notes[:600]})" if notes else "")
    )


def rebuild_card(session: Session, model: TextModel, run: AnalysisRun) -> None:
    entity = session.get(Entity, run.entity_id)
    if entity is None:
        return
    improve = run.mode == MODE_IMPROVE
    note = wish_note(model, entity, run.wishes.strip()) if run.wishes.strip() else ""
    if note:
        # Kept as a note on the card: every later run hears it, until the text confirms it.
        entity.author_notes = [*(entity.author_notes or []), note]
        session.commit()
    parts = set(run.parts) or set(PARTS)
    if PART_FACTS in parts:
        if improve:
            _improve_facts(session, model, run, entity)
        else:
            _rebuild_facts(session, model, run, entity)
        if run.cancel_requested:
            return
    session.refresh(entity)
    if not any(f.text.strip() for f in entity.facts) and not entity.author_notes:
        return
    if PART_SUMMARY in parts:
        if not improve:
            entity.summary = ""  # written anew from the facts, not patched from old mistakes
        session.commit()
        write_summaries(session, model, [entity], entity.kind, run)
        keep_general(session, model, [entity], entity.kind, run)
    if PART_APPEARANCE in parts:
        describe_looks(session, model, [entity], entity.kind, run)


def _rebuild_facts(session: Session, model: TextModel, run: AnalysisRun, entity: Entity) -> None:
    chapters = card_chapters(session, entity)
    run.chapter_ids = [c.id for c in chapters]
    run.done_chapter_ids = []
    session.commit()
    system = prompts.card_facts_system(entity.kind, _target(entity))
    for chapter in chapters:
        session.refresh(run)
        if run.cancel_requested:
            return
        found: list[ExtractedFact] = []
        present = False
        for part in chunks(chapter.text):
            try:
                answer = model.invoke_json(
                    f"rebuild_{entity.kind}s",
                    [SystemMessage(system), HumanMessage(f'Chapter "{chapter.title}":\n\n{part}')],
                    CardFacts,
                )
            except BadModelOutput:
                continue
            present = present or answer.present or bool(answer.facts)
            found.extend(answer.facts)
        old = [f for f in entity.facts if f.chapter_id == chapter.id]
        # "Not here" for a chapter it was found in before keeps the old facts: the card may
        # be there under a common word the model missed this time.
        if present or not old:
            for fact in old:
                entity.facts.remove(fact)
            if present:
                _add_facts(entity, chapter, found)
        run.done_chapter_ids = [*run.done_chapter_ids, chapter.id]
        session.commit()


def _improve_facts(session: Session, model: TextModel, run: AnalysisRun, entity: Entity) -> None:
    chapters = card_chapters(session, entity)
    run.chapter_ids = [c.id for c in chapters]
    run.done_chapter_ids = []
    session.commit()
    notes = list(entity.author_notes or [])
    confirmed: set[int] = set()
    system = prompts.improve_system(entity.kind, _target(entity))
    for chapter in chapters:
        session.refresh(run)
        if run.cancel_requested:
            return
        known = [f for f in entity.facts if f.chapter_id == chapter.id and f.text.strip()]
        head = "\n".join(
            [
                "Known facts:",
                *(
                    f"[{n}] ({f.category}) {f.text}" + (f" «{f.quote[:150]}»" if f.quote else "")
                    for n, f in enumerate(known, 1)
                ),
                "",
                "Author's notes:",
                *(f"[{n}] {note}" for n, note in enumerate(notes, 1)),
                "",
                f"Wishes: {run.wishes.strip()}",
            ]
        )
        found: list[ExtractedFact] = []
        wrong: set[int] = set()
        present = False
        for part in chunks(chapter.text):
            try:
                answer = model.invoke_json(
                    f"improve_{entity.kind}s",
                    [
                        SystemMessage(system),
                        HumanMessage(f'{head}\n\nChapter "{chapter.title}":\n\n{part}'),
                    ],
                    Improvement,
                )
            except BadModelOutput:
                continue
            if not (answer.present or answer.facts):
                continue
            present = True
            found.extend(answer.facts)
            wrong.update(n for n in answer.wrong if 1 <= n <= len(known))
            confirmed.update(n for n in answer.confirmed if 1 <= n <= len(notes))
        if present:
            for number in wrong:
                entity.facts.remove(known[number - 1])
            have = {norm(f.text) for f in entity.facts if f.chapter_id == chapter.id}
            mentioned = any(f.chapter_id == chapter.id for f in entity.facts)
            _add_facts(entity, chapter, [f for f in found if norm(f.text) not in have], mentioned)
        run.done_chapter_ids = [*run.done_chapter_ids, chapter.id]
        session.commit()
    # A note the book itself states is now a fact with its quote: no longer a note.
    entity.author_notes = [n for i, n in enumerate(notes, 1) if i not in confirmed]
    session.commit()


def _add_facts(
    entity: Entity, chapter: Chapter, found: list[ExtractedFact], mentioned: bool = False
) -> None:
    paragraphs = chapter.text.split("\n\n")

    def fact(category: str, text: str = "", quote: str = "") -> EntityFact:
        paragraph = locate_quote(quote, paragraphs) if quote else None
        return EntityFact(
            chapter_id=chapter.id,
            chapter_hash=chapter.content_hash,
            category=category,
            text=text,
            quote=quote if paragraph is not None else "",
            paragraph=paragraph,
        )

    if not mentioned:
        entity.facts.append(fact(FACT_MENTION))
    seen: set[str] = set()
    for item in found:
        if not supported(item.quote, paragraphs):
            continue
        if item.text.strip() and norm(item.text) not in seen:
            seen.add(norm(item.text))
            entity.facts.append(fact(item.category, item.text.strip(), item.quote.strip()))
