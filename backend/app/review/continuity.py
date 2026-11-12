"""Contradictions across the whole book that the facts of the cards alone do not show:
name spellings, the timeline, ages through time, who knows what, the dead coming back,
characters who vanish.

Text items work in two steps. Every chapter is read once for short notes (time, who learns
what, deaths, losses), kept with the chapter's hash so an unchanged chapter is never paid for
twice; then the notes of the whole book are compared. Each note carries a quote verified
against the chapter, so every place shown exists in the text."""

import re

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.card import name_matcher
from app.analysis.entities import AGE_WORDS, chunks, locate_quote
from app.llm.calls import TextModel
from app.models import KIND_CHARACTER, Chapter, ChapterExtraction, Entity, EntityFact, Project
from app.review import prompts
from app.review.checks import LANG_BE, LANG_EN, Check
from app.review.remarks import Place, Remark

NOTES_KIND = "continuity"  # ChapterExtraction.kind of the chapter notes
NOTES_CHUNK = 12_000  # chapter text sent in one notes call
NOTES_CHARS = 20_000  # note lines sent in one comparison call
MAX_LATER_FACTS = 4  # facts of a dead character from later chapters shown to the model

# Note types each text item compares.
TYPES = {
    "timeline": {"time"},
    "age": {"time"},
    "knowledge": {"learn", "know"},
    "revived": {"death", "loss", "object"},
}

# A character counts as gone when it is missing this many chapters in a row (at least)...
MIN_GAP = 5
GAP_SHARE = 4  # ...or a quarter of the book, whichever is longer
MIN_SEEN = 3  # and it was in this many chapters before it went


class Note(BaseModel):
    paragraph: int = 0
    quote: str = ""
    type: str = ""
    who: str = ""
    note: str


class _Notes(BaseModel):
    notes: list[Note] = Field(default_factory=list)


class _Raw(BaseModel):
    check: str = ""
    facts: list[int]
    problem: str
    suggestion: str = ""


class _Answer(BaseModel):
    contradictions: list[_Raw] = Field(default_factory=list)


class _Variant(BaseModel):
    names: list[str]
    problem: str
    suggestion: str = ""


class _Variants(BaseModel):
    variants: list[_Variant] = Field(default_factory=list)


# ---------------------------------------------------------------- notes of the chapters


def _stored(session: Session, chapter: Chapter) -> ChapterExtraction | None:
    return session.scalars(
        select(ChapterExtraction).where(
            ChapterExtraction.chapter_id == chapter.id, ChapterExtraction.kind == NOTES_KIND
        )
    ).first()


def _fresh(row: ChapterExtraction | None, chapter: Chapter) -> bool:
    return (
        row is not None
        and row.chapter_hash == chapter.content_hash
        and row.payload.get("version") == prompts.NOTES_VERSION
    )


def read_notes(session: Session, model: TextModel, project: Project, chapter: Chapter) -> bool:
    """Take the notes of one chapter unless they are already there for its current text.
    Returns whether the model was asked."""
    if _fresh(_stored(session, chapter), chapter):
        return False
    paragraphs = chapter.text.split("\n\n") if chapter.text else []
    notes: list[dict] = []
    start = 0
    for part in chunks(chapter.text or "", NOTES_CHUNK):
        count = len(part.split("\n\n"))
        numbers = range(start, start + count)
        start += count
        body = "\n\n".join(f"[{i}] {paragraphs[i]}" for i in numbers if paragraphs[i].strip())
        if not body:
            continue
        answer = model.invoke_json(
            "review_notes",
            [SystemMessage(prompts.NOTES), HumanMessage(f'Chapter "{chapter.title}":\n\n{body}')],
            _Notes,
        )
        for note in answer.notes:
            # Only notes whose quote is really in this piece: the place shown must exist.
            found = locate_quote(note.quote, [paragraphs[i] for i in numbers])
            if found is None or not note.note.strip():
                continue
            note.paragraph = numbers[found]
            note.quote = note.quote.strip()
            notes.append(note.model_dump())
    session.execute(
        delete(ChapterExtraction).where(
            ChapterExtraction.chapter_id == chapter.id, ChapterExtraction.kind == NOTES_KIND
        )
    )
    session.add(
        ChapterExtraction(
            project_id=project.id,
            chapter_id=chapter.id,
            kind=NOTES_KIND,
            chapter_hash=chapter.content_hash,
            payload={"version": prompts.NOTES_VERSION, "notes": notes},
        )
    )
    session.commit()
    return True


def stored_notes(session: Session, project: Project) -> dict[str, list[Note]]:
    """Notes of the chapters read for their current text, by chapter id."""
    rows = session.scalars(
        select(ChapterExtraction).where(
            ChapterExtraction.project_id == project.id, ChapterExtraction.kind == NOTES_KIND
        )
    ).all()
    by_chapter = {r.chapter_id: r for r in rows}
    result: dict[str, list[Note]] = {}
    for chapter in project.chapters:
        row = by_chapter.get(chapter.id)
        if _fresh(row, chapter):
            result[chapter.id] = [Note.model_validate(n) for n in row.payload.get("notes", [])]
    return result


# ---------------------------------------------------------------- comparing the notes


def _named(entities: list[Entity], who: str) -> Entity | None:
    """The character card a note's "who" points at, by name or other name."""
    key = who.strip().casefold()
    if not key:
        return None
    for entity in entities:
        if key in {n.casefold() for n in (entity.name, *entity.aliases)}:
            return entity
    for entity in entities:
        if name_matcher(entity)(who):
            return entity
    return None


def check_notes(
    session: Session, model: TextModel, project: Project, items: list[Check]
) -> list[Remark]:
    """The text items (timeline, age, knowledge, revived) on the notes already taken."""
    items = [c for c in items if c.reads_text]
    if not items:
        return []
    chapters = [c for c in project.chapters]
    titles = {c.id: c.title for c in chapters}
    order = {c.id: c.position for c in chapters}
    notes = stored_notes(session, project)
    wanted = set().union(*(TYPES[c.id] for c in items))
    characters = list(
        session.scalars(
            select(Entity).where(Entity.project_id == project.id, Entity.kind == KIND_CHARACTER)
        ).all()
    )

    # (position, line, place) in the order of the book.
    lines: list[tuple[int, str, Place]] = []
    deaths: dict[str, int] = {}  # card id -> position of the chapter it died in
    for chapter in chapters:
        for note in notes.get(chapter.id, []):
            if note.type not in wanted:
                continue
            who = f" {note.who.strip()}:" if note.who.strip() else ""
            place = Place(
                chapter_id=chapter.id,
                chapter_title=chapter.title,
                paragraph=note.paragraph,
                quote=note.quote,
            )
            lines.append(
                (chapter.position, f"({chapter.title}) {note.type}:{who} {note.note}", place)
            )
            if note.type == "death":
                card = _named(characters, note.who)
                if card is not None and card.id not in deaths:
                    deaths[card.id] = chapter.position

    def fact_line(entity: Entity, fact: EntityFact, label: str) -> tuple[int, str, Place]:
        return (
            order[fact.chapter_id],
            f"({titles[fact.chapter_id]}) {label}: {entity.name}: {fact.text}",
            Place(
                chapter_id=fact.chapter_id,
                chapter_title=titles[fact.chapter_id],
                paragraph=fact.paragraph,
                quote=fact.quote or fact.text,
            ),
        )

    ids = {c.id for c in items}
    for entity in characters:
        facts = [f for f in entity.facts if f.chapter_id in titles]
        if "age" in ids:
            for fact in facts:
                if AGE_WORDS.search(fact.text) or AGE_WORDS.search(fact.quote or ""):
                    lines.append(fact_line(entity, fact, "age"))
        if "revived" in ids and entity.id in deaths:
            # What the card does in the chapters after it died: the model tells a memory
            # or a ghost from a mistake.
            later = sorted(
                (f for f in facts if order[f.chapter_id] > deaths[entity.id]),
                key=lambda f: order[f.chapter_id],
            )
            lines.extend(fact_line(entity, f, "later") for f in later[:MAX_LATER_FACTS])
    if not lines:
        return []
    lines.sort(key=lambda item: item[0])  # stable: notes of one chapter keep their order

    batches: list[list[tuple[str, Place]]] = []
    batch: list[tuple[str, Place]] = []
    size = 0
    for _, line, place in lines:
        if batch and size + len(line) > NOTES_CHARS:
            batches.append(batch)
            batch, size = [], 0
        batch.append((line, place))
        size += len(line) + 8
    if batch:
        batches.append(batch)

    system = prompts.continuity([c.instruction for c in items], [c.id for c in items])
    remarks: list[Remark] = []
    for batch in batches:
        listing = "\n".join(f"[{n}] {line}" for n, (line, _) in enumerate(batch, 1))
        answer = model.invoke_json(
            "review_continuity", [SystemMessage(system), HumanMessage(listing)], _Answer
        )
        for raw in answer.contradictions:
            check = raw.check if raw.check in ids else items[0].id
            numbers = [n for n in dict.fromkeys(raw.facts) if 1 <= n <= len(batch)]
            # Knowledge never learned is shown by one line; everything else needs two.
            if len(numbers) < (1 if check == "knowledge" else 2):
                continue
            remarks.append(
                Remark(
                    category=check,
                    problem=raw.problem,
                    suggestion=raw.suggestion,
                    places=[batch[n - 1][1] for n in numbers],
                )
            )
    return remarks


# ---------------------------------------------------------------- names


def _first_use(chapters: list[Chapter], name: str) -> Place | None:
    """Where the book first writes this exact name (any case ending is not enough: the
    spelling is the point)."""
    pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")
    for chapter in chapters:
        for index, paragraph in enumerate(chapter.text.split("\n\n")):
            match = pattern.search(paragraph)
            if match:
                start = max(0, match.start() - 50)
                quote = paragraph[start : match.end() + 50].strip()
                return Place(
                    chapter_id=chapter.id,
                    chapter_title=chapter.title,
                    paragraph=index,
                    quote=quote,
                )
    return None


def check_names(session: Session, model: TextModel, project: Project, item: Check) -> list[Remark]:
    """Names of one card (or of two cards) spelled differently for no reason."""
    entities = session.scalars(select(Entity).where(Entity.project_id == project.id)).all()
    cards = [
        f"- {e.name}" + (f" (also: {', '.join(e.aliases)})" if e.aliases else "")
        for e in sorted(entities, key=lambda e: e.name)
        if e.name[:1].isupper()
    ]
    if len(cards) < 1:
        return []
    remarks: list[Remark] = []
    for start in range(0, len(cards), 300):
        answer = model.invoke_json(
            "review_names",
            [
                SystemMessage(prompts.name_variants(item.instruction)),
                HumanMessage("\n".join(cards[start : start + 300])),
            ],
            _Variants,
        )
        for variant in answer.variants:
            places = [
                p
                for p in (
                    _first_use(project.chapters, n.strip()) for n in dict.fromkeys(variant.names)
                )
                if p is not None
            ]
            # Both spellings must really be in the text: a name only on a card proves nothing.
            if len(places) < 2:
                continue
            remarks.append(
                Remark(
                    category="name_variants",
                    problem=variant.problem,
                    suggestion=variant.suggestion,
                    places=places,
                )
            )
    return remarks


# ---------------------------------------------------------------- characters who vanish

_GONE = {
    "ru": (
        (
            "{name}: был в {seen} главах, после главы «{last}» не появляется до конца книги "
            "(глав без героя: {gap})"
        ),
        "{name}: был в {seen} главах, потом пропадает на {gap} глав (с «{last}» до «{back}»)",
        "Если пропажа не задумана — упомянуть, где герой и почему его нет.",
    ),
    "be": (
        (
            "{name}: быў у {seen} раздзелах, пасля раздзела «{last}» не з'яўляецца да канца кнігі "
            "(раздзелаў без героя: {gap})"
        ),
        "{name}: быў у {seen} раздзелах, потым знікае на {gap} раздзелаў (з «{last}» да «{back}»)",
        "Калі знікненне не задуманае — згадаць, дзе герой і чаму яго няма.",
    ),
    "en": (
        (
            "{name}: in {seen} chapters, then gone after «{last}» to the end of the book "
            "({gap} chapters without them)"
        ),
        "{name}: in {seen} chapters, then missing for {gap} chapters (from «{last}» to «{back}»)",
        "If the absence is not intended, mention where they are and why.",
    ),
}


def _mention(chapter: Chapter, names_it, facts: list[EntityFact]) -> Place:
    """A place in the chapter that shows the character: one of its facts, or the paragraph
    naming it."""
    for fact in facts:
        if fact.chapter_id == chapter.id and fact.quote:
            return Place(
                chapter_id=chapter.id,
                chapter_title=chapter.title,
                paragraph=fact.paragraph,
                quote=fact.quote,
            )
    paragraphs = chapter.text.split("\n\n")
    for index, paragraph in enumerate(paragraphs):
        if names_it(paragraph):
            return Place(
                chapter_id=chapter.id,
                chapter_title=chapter.title,
                paragraph=index,
                quote=paragraph[:150].strip(),
            )
    return Place(chapter_id=chapter.id, chapter_title=chapter.title, quote=chapter.title)


def check_missing(session: Session, project: Project, language: str) -> list[Remark]:
    """Characters who were in many chapters and then vanish for a long stretch, or for good.
    Counted without a model, by the facts of the cards and the names in the text."""
    chapters = [c for c in project.chapters if c.text.strip()]
    if len(chapters) < MIN_SEEN + MIN_GAP:
        return []
    gap_needed = max(MIN_GAP, len(chapters) // GAP_SHARE)
    text = _GONE.get(language if language in (LANG_BE, LANG_EN) else "ru")
    entities = session.scalars(
        select(Entity).where(Entity.project_id == project.id, Entity.kind == KIND_CHARACTER)
    ).all()
    remarks: list[Remark] = []
    for entity in sorted(entities, key=lambda e: e.name):
        names_it = name_matcher(entity)
        had = {f.chapter_id for f in entity.facts}
        seen = [i for i, c in enumerate(chapters) if c.id in had or names_it(c.text)]
        if len(seen) < MIN_SEEN:
            continue
        stops = [*seen[1:], len(chapters)]  # the next appearance, or the end of the book
        for number, (here, after) in enumerate(zip(seen, stops, strict=True), 1):
            gap = after - here - 1
            if gap < gap_needed or number < MIN_SEEN:
                continue
            last = chapters[here]
            places = [_mention(last, names_it, entity.facts)]
            if after < len(chapters):
                back = chapters[after]
                places.append(_mention(back, names_it, entity.facts))
                problem = text[1].format(
                    name=entity.name, seen=number, gap=gap, last=last.title, back=back.title
                )
            else:
                problem = text[0].format(name=entity.name, seen=number, gap=gap, last=last.title)
            remarks.append(
                Remark(category="missing", problem=problem, suggestion=text[2], places=places)
            )
    return remarks
