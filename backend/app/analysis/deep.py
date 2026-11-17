"""Deep search for characters: a light model indexes, a strong one decides and writes.

    index (light, per chapter)  ->  cast (strong, once)  ->  cards (strong for the main
    characters, light for the rest)  ->  check (light)  ->  summaries and looks

The ordinary search asks one model to do everything chapter by chapter, so it never sees
the whole story: a lie told in one chapter, a grandfather who is only called "grandad", a
mermaid in someone's mother's shape all end up in the cards as facts. Here the cheap model
only marks who is mentioned in which paragraphs. The strong model then sees the whole cast
once (who is the same being under another name or form, who are two beings under one name,
which names are only lies) and writes each main character's card from every paragraph about
them across the book. Every fact still needs a quote that is really in its chapter.
"""

import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis import prompts
from app.analysis.entities import (
    CHUNK_CHARS,
    FACT_MENTION,
    _is_proper,
    describe_looks,
    keep_general,
    locate_quote,
    norm,
    show_stage,
    write_summaries,
)
from app.llm.calls import BadModelOutput, TextModel
from app.models import (
    FACT_PERMANENT,
    FACT_PROFILE,
    FACT_STATE,
    AnalysisRun,
    Chapter,
    ChapterExtraction,
    Entity,
    EntityFact,
    Project,
)

MODE_DEEP = "deep"
INDEX_VERSION = 1
# A main character is written by the strong model: seen in this many chapters at least,
# and no more than this many of them (the strong model costs several times more).
MAIN_MIN_CHAPTERS = 5
MAIN_LIMIT = 8
DOSSIER_CHARS = 120_000
SAMPLE_CHARS = 350
CATEGORIES = {FACT_PERMANENT, FACT_STATE, FACT_PROFILE}


# ---------- what the models return ----------


class Mention(BaseModel):
    name: str
    named: bool = True
    paragraphs: list[int] = []


class ChapterMentions(BaseModel):
    mentions: list[Mention] = []


class Source(BaseModel):
    name: str
    # Chapter numbers (1-based) where this name means this being; empty means everywhere.
    chapters: list[int] = []


class Being(BaseModel):
    name: str
    sources: list[Source] = []
    forms: list[str] = []


class FalseName(BaseModel):
    name: str
    belongs_to: str = ""
    reason: str = ""


class Cast(BaseModel):
    beings: list[Being] = []
    false_names: list[FalseName] = []


class DeepFact(BaseModel):
    category: str
    text: str
    quote: str = ""
    chapter: int = 0
    doubtful: bool = False


class CardDraft(BaseModel):
    aliases: list[str] = []
    age: str = ""
    facts: list[DeepFact] = []


class Wrong(BaseModel):
    wrong: list[int] = []


# ---------- the book as numbered paragraphs ----------


@dataclass
class Book:
    chapters: list[Chapter]
    paragraphs: list[list[str]] = field(default_factory=list)

    def __post_init__(self):
        self.paragraphs = [c.text.split("\n\n") for c in self.chapters]


def numbered_parts(paragraphs: list[str], limit: int = CHUNK_CHARS) -> list[str]:
    """A chapter as "[n] paragraph" lines, cut into requests of about `limit` characters;
    the numbers run across the parts so every answer points into the same chapter."""
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for index, paragraph in enumerate(paragraphs):
        line = f"[{index}] {paragraph}"
        if current and size + len(line) > limit:
            parts.append("\n\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        parts.append("\n\n".join(current))
    return parts


# ---------- step A: who is mentioned where ----------


INDEX_KIND = "character_index"


def index_chapter(
    session: Session, model: TextModel, run: AnalysisRun, chapter: Chapter
) -> list[Mention]:
    """The mentions of one chapter, read once and kept with the chapter's hash."""
    stored = session.scalars(
        select(ChapterExtraction).where(
            ChapterExtraction.chapter_id == chapter.id, ChapterExtraction.kind == INDEX_KIND
        )
    ).first()
    if (
        stored is not None
        and stored.chapter_hash == chapter.content_hash
        and stored.payload.get("version") == INDEX_VERSION
    ):
        return ChapterMentions.model_validate(stored.payload).mentions
    paragraphs = chapter.text.split("\n\n")
    found: list[Mention] = []
    for part in numbered_parts(paragraphs):
        answer = model.invoke_json(
            "index_characters",
            [
                SystemMessage(prompts.INDEX_SYSTEM),
                HumanMessage(f'Chapter "{chapter.title}":\n\n{part}'),
            ],
            ChapterMentions,
        )
        found.extend(answer.mentions)
    mentions = clean_mentions(found, len(paragraphs))
    session.execute(
        delete(ChapterExtraction).where(
            ChapterExtraction.chapter_id == chapter.id, ChapterExtraction.kind == INDEX_KIND
        )
    )
    session.add(
        ChapterExtraction(
            project_id=run.project_id,
            chapter_id=chapter.id,
            kind=INDEX_KIND,
            chapter_hash=chapter.content_hash,
            payload={
                "version": INDEX_VERSION,
                "mentions": [m.model_dump() for m in mentions],
            },
        )
    )
    session.commit()
    return mentions


def clean_mentions(found: list[Mention], count: int) -> list[Mention]:
    """One entry per name, paragraphs that exist, nothing empty."""
    merged: dict[str, Mention] = {}
    for item in found:
        name = item.name.strip()
        places = sorted({p for p in item.paragraphs if 0 <= p < count})
        if not name or not places:
            continue
        key = norm(name)
        if key in merged:
            merged[key].paragraphs = sorted({*merged[key].paragraphs, *places})
            merged[key].named = merged[key].named or item.named
        else:
            merged[key] = Mention(
                name=name, named=item.named and _is_proper(name), paragraphs=places
            )
    return list(merged.values())


@dataclass
class Name:
    """One name across the book: where it occurs, chapter index -> paragraph numbers."""

    name: str
    named: bool
    places: dict[int, list[int]] = field(default_factory=dict)


def gather(index: list[list[Mention]]) -> dict[str, Name]:
    names: dict[str, Name] = {}
    for chapter, mentions in enumerate(index):
        for mention in mentions:
            entry = names.setdefault(norm(mention.name), Name(mention.name, mention.named))
            entry.named = entry.named or mention.named
            entry.places[chapter] = sorted({*entry.places.get(chapter, []), *mention.paragraphs})
    return names


# ---------- step B: who is who ----------


def cast_listing(book: Book, names: dict[str, Name], pinned: list[list[str]]) -> str:
    """Every name with its chapters and its first appearances, for one look at the cast."""
    lines = []
    for entry in sorted(names.values(), key=lambda n: (-len(n.places), n.name)):
        chapters = sorted(entry.places)
        lines.append(
            f"## {entry.name} — chapters {', '.join(str(c + 1) for c in chapters)}"
            + ("" if entry.named else " (not a proper name)")
        )
        samples = 3 if len(chapters) >= 3 else 1
        # The first appearances and the last one: a namesake or a new form shows up late.
        picks = chapters[:samples] + ([chapters[-1]] if len(chapters) > samples else [])
        for chapter in picks:
            paragraph = entry.places[chapter][0]
            text = " ".join(book.paragraphs[chapter][paragraph].split())[:SAMPLE_CHARS]
            lines.append(f"- ch. {chapter + 1} ¶{paragraph}: {text}")
    if pinned:
        lines.append("\n## Decided by the user (always keep)")
        lines.extend(f"- the same being: {', '.join(group)}" for group in pinned)
    return "\n".join(lines)


def decide_cast(
    session: Session, model: TextModel, book: Book, names: dict[str, Name], pinned: list[list[str]]
) -> Cast:
    try:
        return model.invoke_json(
            "cast_characters",
            [
                SystemMessage(prompts.CAST_SYSTEM),
                HumanMessage(cast_listing(book, names, pinned)),
            ],
            Cast,
        )
    except BadModelOutput:
        return Cast()  # every name stays its own card: no worse than the ordinary search


@dataclass
class Plan:
    """One card to write: its name, other names and where the book speaks of it."""

    name: str
    aliases: list[str]
    places: dict[int, set[int]]
    named: bool
    forms: list[str] = field(default_factory=list)

    @property
    def chapter_count(self) -> int:
        return len(self.places)


def plan_cards(names: dict[str, Name], cast: Cast) -> list[Plan]:
    """Cards from the model's cast; a name it left out is a card of its own. A false name
    is no card and no alias, but its paragraphs go to the being it was said about."""
    false = {norm(f.name): f for f in cast.false_names}
    used: set[str] = set()
    plans: list[Plan] = []
    for being in cast.beings:
        if not being.name.strip() or any(norm(p.name) == norm(being.name) for p in plans):
            continue
        places: dict[int, set[int]] = {}
        aliases: list[str] = []
        named = False
        for source in being.sources:
            entry = names.get(norm(source.name))
            if entry is None:
                continue
            wanted = {c - 1 for c in source.chapters}
            for chapter, paragraphs in entry.places.items():
                if wanted and chapter not in wanted:
                    continue
                places.setdefault(chapter, set()).update(paragraphs)
            if not wanted:
                used.add(norm(source.name))
            named = named or entry.named
            # Only real names become other names: "the old man" is no name.
            if (
                entry.named
                and norm(source.name) != norm(being.name)
                and norm(source.name) not in false
            ):
                aliases.append(entry.name)
        if not places:
            continue
        plans.append(
            Plan(being.name.strip(), list(dict.fromkeys(aliases)), places, named, being.forms)
        )
    by_name = {norm(p.name): p for p in plans}
    for key, wrong in false.items():
        entry, owner = names.get(key), by_name.get(norm(wrong.belongs_to))
        used.add(key)
        if entry is not None and owner is not None:
            for chapter, paragraphs in entry.places.items():
                owner.places.setdefault(chapter, set()).update(paragraphs)
    for key, entry in names.items():
        if key in used or key in by_name:
            continue
        # "a bird" seen in one chapter: nothing worth a card.
        if not entry.named and len(entry.places) < 2:
            continue
        plan = Plan(entry.name, [], {c: set(p) for c, p in entry.places.items()}, entry.named)
        plans.append(plan)
        by_name[key] = plan
    return plans


def pick_main(plans: list[Plan]) -> set[str]:
    ranked = sorted(
        (p for p in plans if p.named and p.chapter_count >= MAIN_MIN_CHAPTERS),
        key=lambda p: -p.chapter_count,
    )
    return {norm(p.name) for p in ranked[:MAIN_LIMIT]}


# ---------- step C: the card from every paragraph about it ----------


def dossier(book: Book, plan: Plan, limit: int = DOSSIER_CHARS) -> str:
    """Every paragraph about the being in story order, with its neighbours for context;
    without the neighbours when that is too long, and thinned evenly if still too long."""

    def build(spread: int) -> list[tuple[int, str]]:
        blocks = []
        for chapter in sorted(plan.places):
            paragraphs = book.paragraphs[chapter]
            wanted = sorted(
                {
                    j
                    for p in plan.places[chapter]
                    for j in range(p - spread, p + spread + 1)
                    if 0 <= j < len(paragraphs)
                }
            )
            lines = [f"[{j}] {paragraphs[j]}" for j in wanted]
            title = book.chapters[chapter].title or f"#{chapter + 1}"
            blocks.append(
                (chapter, f"=== Chapter {chapter + 1} «{title}» ===\n" + "\n\n".join(lines))
            )
        return blocks

    blocks = build(1)
    if sum(len(b) for _, b in blocks) > limit:
        blocks = build(0)
    total = sum(len(b) for _, b in blocks)
    if total > limit:
        step = total / limit
        blocks = [b for i, b in enumerate(blocks) if int(i % step) == 0] or blocks[:1]
    return "\n\n".join(b for _, b in blocks)


def write_card(model: TextModel, book: Book, plan: Plan, known_ages: dict[str, str]) -> CardDraft:
    others = "\n".join(f"- {name}: {age}" for name, age in known_ages.items() if name != plan.name)
    head = [f"Character: {plan.name}"]
    if plan.aliases:
        head.append(f"Also called: {', '.join(plan.aliases)}")
    if plan.forms:
        head.append(f"Forms: {', '.join(plan.forms)}")
    if others:
        head.append(f"Ages already worked out for others:\n{others}")
    try:
        return model.invoke_json(
            "card_characters",
            [
                SystemMessage(prompts.DOSSIER_SYSTEM),
                HumanMessage("\n".join(head) + "\n\n" + dossier(book, plan)),
            ],
            CardDraft,
        )
    except BadModelOutput:
        return CardDraft()


def store_card(book: Book, entity: Entity, plan: Plan, draft: CardDraft) -> None:
    """Facts with a quote that is in the chapter it names; doubtful ones are left out."""
    for chapter in sorted(plan.places):
        entity.facts.append(_fact(book, chapter, FACT_MENTION))
    seen: set[str] = set()
    for item in draft.facts:
        chapter = item.chapter - 1
        if item.doubtful or item.category not in CATEGORIES or not item.text.strip():
            continue
        if not 0 <= chapter < len(book.chapters):
            continue
        paragraph = (
            locate_quote(item.quote.strip(), book.paragraphs[chapter]) if item.quote else None
        )
        if paragraph is None:
            continue
        key = norm(item.text)
        if key in seen:
            continue
        seen.add(key)
        entity.facts.append(
            _fact(book, chapter, item.category, item.text.strip(), item.quote.strip(), paragraph)
        )


def _fact(
    book: Book, chapter: int, category: str, text: str = "", quote: str = "", paragraph=None
) -> EntityFact:
    source = book.chapters[chapter]
    return EntityFact(
        chapter_id=source.id,
        chapter_hash=source.content_hash,
        category=category,
        text=text,
        quote=quote,
        paragraph=paragraph,
    )


# ---------- step D: does each quote speak of this character ----------


def check_card(model: TextModel, book: Book, entity: Entity) -> None:
    facts = [f for f in entity.facts if f.text.strip()]
    if not facts:
        return
    positions = {c.id: i for i, c in enumerate(book.chapters)}
    lines = [
        f"Character: {entity.name}"
        + (f" (also: {', '.join(entity.aliases)})" if entity.aliases else "")
    ]
    for number, fact in enumerate(facts, 1):
        chapter = positions.get(fact.chapter_id)
        context = ""
        if chapter is not None and fact.paragraph is not None:
            context = " ".join(book.paragraphs[chapter][fact.paragraph].split())[:600]
        lines.append(f"[{number}] {fact.text}\n    quote: «{fact.quote}»\n    paragraph: {context}")
    try:
        answer = model.invoke_json(
            "check_characters",
            [SystemMessage(prompts.CHECK_SYSTEM), HumanMessage("\n".join(lines))],
            Wrong,
        )
    except BadModelOutput:
        return
    for number in set(answer.wrong):
        if 1 <= number <= len(facts):
            entity.facts.remove(facts[number - 1])


# ---------- the whole run ----------


AGE_FACT = re.compile(r"\d")


def execute(session: Session, run: AnalysisRun, light: TextModel, strong: TextModel) -> None:
    """Steps A-D and the descriptions. Chapters indexed before a failure are kept."""
    project = session.get(Project, run.project_id)
    book = Book(sorted(project.chapters, key=lambda c: c.position))
    index: list[list[Mention]] = []
    for number, chapter in enumerate(book.chapters):
        if _cancelled(session, run):
            return
        index.append(index_chapter(session, light, run, chapter))
        if chapter.id not in run.done_chapter_ids:
            run.done_chapter_ids = [*run.done_chapter_ids, chapter.id]
            session.commit()
    names = gather(index)
    existing = list(
        session.scalars(
            select(Entity).where(Entity.project_id == project.id, Entity.kind == run.kind)
        )
    )
    pinned = [[e.name, *e.pinned_names] for e in existing if e.pinned_names]
    show_stage(session, run, "reconcile", 0, 1)
    if _cancelled(session, run):
        return
    cast = decide_cast(session, strong, book, names, pinned)
    plans = plan_cards(names, cast)
    main = pick_main(plans)
    entities = _bind(session, project.id, run.kind, existing, plans)
    run.report = {
        "merged": [[a, p.name] for p in plans for a in p.aliases],
        "adopted": [],
    }
    session.commit()
    # Main characters first: their ages help to work out the others' ("as old as Uts").
    order = sorted(plans, key=lambda p: (norm(p.name) not in main, -p.chapter_count))
    known_ages: dict[str, str] = {}
    for number, plan in enumerate(order):
        if _cancelled(session, run):
            return
        show_stage(session, run, "cards", number, len(order))
        model = strong if norm(plan.name) in main else light
        draft = write_card(model, book, plan, known_ages)
        if draft.age.strip() and AGE_FACT.search(draft.age):
            known_ages[plan.name] = draft.age.strip()
        entity = entities[norm(plan.name)]
        store_card(book, entity, plan, draft)
        session.flush()
        show_stage(session, run, "check", number, len(order))
        check_card(light, book, entity)
        session.commit()
    cards = [
        entities[norm(p.name)]
        for p in order
        if any(f.text.strip() for f in entities[norm(p.name)].facts)
    ]
    main_cards = [c for c in cards if norm(c.name) in main]
    rest = [c for c in cards if norm(c.name) not in main]
    write_summaries(session, strong, main_cards, run.kind, run)
    write_summaries(session, light, rest, run.kind, run)
    keep_general(session, light, cards, run.kind, run)
    describe_looks(session, strong, main_cards, run.kind, run)
    describe_looks(session, light, rest, run.kind, run)


def _bind(
    session: Session, project_id: str, kind: str, existing: list[Entity], plans: list[Plan]
) -> dict[str, Entity]:
    """A card for every plan, reusing the old one of the same name (its pictures, the
    user's own texts stay). Old facts go; old cards nothing points to are removed unless
    the user made or illustrated them."""
    by_key: dict[str, Entity] = {}
    for entity in existing:
        for key in {norm(entity.name), *map(norm, entity.pinned_names)}:
            by_key.setdefault(key, entity)
    bound: dict[str, Entity] = {}
    for plan in plans:
        free = [
            by_key[norm(n)]
            for n in (plan.name, *plan.aliases)
            if norm(n) in by_key and by_key[norm(n)] not in bound.values()
        ]
        entity = free[0] if free else None
        if entity is None:
            entity = Entity(project_id=project_id, kind=kind, name=plan.name)
            session.add(entity)
        entity.name = plan.name
        entity.aliases = list(dict.fromkeys([*plan.aliases, *(entity.pinned_names or [])]))
        entity.uncertain = not plan.named
        entity.facts.clear()
        bound[norm(plan.name)] = entity
    for entity in existing:
        if entity not in bound.values() and not entity.standalone and not entity.images:
            session.delete(entity)
    session.flush()
    return bound


def _cancelled(session: Session, run: AnalysisRun) -> bool:
    session.refresh(run)
    return run.cancel_requested
