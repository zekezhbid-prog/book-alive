"""Finding characters and locations, chapter by chapter, as a LangGraph loop.

    extract -> merge -+-> extract ...                       (next chapter)
                      +-> reconcile -> summarize -> END    (no chapters left)
                      +-> summarize -> END                 (cancelled)

`extract` asks the model about one chapter and stores the raw answer keyed by the
chapter's text hash. `merge` turns that answer into entities and facts without any
model call. Because the raw answers persist, a run that stops halfway costs nothing
to resume: chapters already read are served from the database.
"""

import re
from typing import Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis import prompts
from app.llm.calls import BadModelOutput, TextModel, estimate_tokens
from app.models import (
    FACT_PERMANENT,
    FACT_PROFILE,
    FACT_STATE,
    AnalysisRun,
    Chapter,
    ChapterExtraction,
    Entity,
    EntityFact,
)

FACT_MENTION = "mention"  # the entity takes part in the chapter; carries no detail
CHUNK_CHARS = 30_000
PROMPT_OVERHEAD_TOKENS = 500


# ---------- what the model returns ----------


class ExtractedFact(BaseModel):
    category: Literal["permanent", "state", "profile"] = FACT_STATE
    text: str
    quote: str = ""


class ExtractedEntity(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    # False when the text gives no proper name and "name" is a common word (the old man).
    named: bool = True
    # True for several beings or things taken together (the merchants, the guards).
    group: bool = False
    facts: list[ExtractedFact] = Field(default_factory=list)


class ChapterEntities(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)


class Groups(BaseModel):
    groups: list[list[int]] = Field(default_factory=list)


class CardSummary(BaseModel):
    number: int
    text: str = ""
    appearance: str = ""


class Summaries(BaseModel):
    summaries: list[CardSummary] = Field(default_factory=list)


# ---------- helpers ----------


def _is_proper(name: str) -> bool:
    return name.strip()[:1].isupper()


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.casefold().replace("ё", "е")).strip(" .,:;!?\"'«»")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().replace("ё", "е")).strip(" .…\"'«»“”—–-")


def locate_quote(quote: str, paragraphs: list[str]) -> int | None:
    """Paragraph that contains the quote, or None when the model made it up."""
    needle = _squash(quote)
    if len(needle) < 4:
        return None
    for index, paragraph in enumerate(paragraphs):
        if needle in _squash(paragraph):
            return index
    return None


def chunks(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    parts: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) > limit:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{paragraph}" if current else paragraph
    return [*parts, current] if current else parts


def _entities(session: Session, project_id: str, kind: str) -> list[Entity]:
    return list(
        session.scalars(
            select(Entity).where(Entity.project_id == project_id, Entity.kind == kind)
        ).all()
    )


def _cached(session: Session, chapter: Chapter, kind: str) -> ChapterExtraction | None:
    row = session.scalars(
        select(ChapterExtraction).where(
            ChapterExtraction.chapter_id == chapter.id, ChapterExtraction.kind == kind
        )
    ).first()
    fresh = (
        row is not None
        and row.chapter_hash == chapter.content_hash
        and row.payload.get("version") == prompts.PROMPT_VERSION
    )
    return row if fresh else None


def start_fresh(session: Session, project_id: str, chapters: list[Chapter], kind: str) -> None:
    """Before a run "from scratch": forget what earlier runs found, so the new one neither
    reuses their answers nor sees their names as already known. The chosen chapters lose
    their stored model answers. Cards are dropped, except those carrying the user's own work
    (pictures, hand merges or splits, cards made by hand): they only lose their facts and
    summary, and the run fills them again if it finds them."""
    session.execute(
        delete(ChapterExtraction).where(
            ChapterExtraction.chapter_id.in_([c.id for c in chapters]),
            ChapterExtraction.kind == kind,
        )
    )
    for entity in _entities(session, project_id, kind):
        if entity.images or entity.pinned_names or entity.standalone:
            entity.facts.clear()
            entity.summary = ""
            entity.appearance = ""
            entity.aliases = list(entity.pinned_names)
        else:
            session.delete(entity)


# ---------- estimate ----------


class Estimate(BaseModel):
    chapters: int
    cached: int  # already read with the same text: free
    requests: int
    input_tokens: int
    output_tokens: int


def estimate(
    session: Session,
    chapters: list[Chapter],
    kind: str,
    request_overhead: int = 0,
    fresh: bool = False,
) -> Estimate:
    """`request_overhead`: tokens the connection adds to every request on its own.
    `fresh`: the stored answers will be thrown away, so every chapter is read again."""
    system_tokens = (
        estimate_tokens(prompts.extract_system(kind)) + PROMPT_OVERHEAD_TOKENS + request_overhead
    )
    result = Estimate(chapters=len(chapters), cached=0, requests=0, input_tokens=0, output_tokens=0)
    for chapter in chapters:
        if not chapter.text.strip() or (not fresh and _cached(session, chapter, kind)):
            result.cached += 1
            continue
        for part in chunks(chapter.text):
            tokens = estimate_tokens(part)
            result.requests += 1
            result.input_tokens += tokens + system_tokens
            # Observed on prose: the answer runs to roughly a fifth of the chapter.
            result.output_tokens += max(300, tokens // 5)
    if result.requests:
        result.requests += 2  # the final passes: merging duplicate names, describing the cards
        result.input_tokens += 4000 + request_overhead
        result.output_tokens += 1500
    return result


# ---------- graph ----------


class State(TypedDict):
    run_id: str
    pending: list[str]


def _context(config: RunnableConfig) -> tuple[Session, TextModel, AnalysisRun]:
    session: Session = config["configurable"]["session"]
    run = session.get(AnalysisRun, config["configurable"]["run_id"])
    return session, config["configurable"]["model"], run


def _known_line(entity: Entity) -> str:
    """A known card for the model: its main name and a hint who it is, so a chapter that calls
    them "the girl" can be matched. Aliases stay out: an earlier mistake would come back."""
    hint = (entity.description or entity.summary).split(". ")[0]
    if not hint:
        hint = "; ".join(f.text for f in entity.facts if f.category == FACT_PERMANENT and f.text)
    hint = hint.strip()[:120]
    return f"- {entity.name}" + (f" - {hint}" if hint else "")


def extract(state: State, config: RunnableConfig) -> dict:
    session, model, run = _context(config)
    chapter = session.get(Chapter, state["pending"][0])
    if chapter is None or not chapter.text.strip() or _cached(session, chapter, run.kind):
        return {}
    known = _entities(session, run.project_id, run.kind)
    # Main names only: listing the aliases too would hand an earlier chapter's mistake
    # (someone's friend given as their nickname) back to the model as a fact.
    known_text = "\n".join(_known_line(e) for e in known if not e.uncertain)
    found: list[ExtractedEntity] = []
    for part in chunks(chapter.text):
        answer = model.invoke_json(
            f"find_{run.kind}s",
            [
                SystemMessage(prompts.extract_system(run.kind)),
                HumanMessage(
                    prompts.EXTRACT_USER.format(
                        known=known_text or "(none yet)", title=chapter.title, text=part
                    )
                ),
            ],
            ChapterEntities,
        )
        found.extend(answer.entities)
    session.execute(
        delete(ChapterExtraction).where(
            ChapterExtraction.chapter_id == chapter.id, ChapterExtraction.kind == run.kind
        )
    )
    session.add(
        ChapterExtraction(
            project_id=run.project_id,
            chapter_id=chapter.id,
            kind=run.kind,
            chapter_hash=chapter.content_hash,
            payload={
                "version": prompts.PROMPT_VERSION,
                "entities": [e.model_dump() for e in found],
            },
        )
    )
    session.commit()
    return {}


def merge(state: State, config: RunnableConfig) -> dict:
    session, _, run = _context(config)
    chapter_id, *rest = state["pending"]
    chapter = session.get(Chapter, chapter_id)
    if chapter is not None:
        apply_extraction(session, run.project_id, run.kind, chapter)
    run.done_chapter_ids = [*run.done_chapter_ids, chapter_id]
    session.commit()
    return {"pending": rest}


def apply_extraction(session: Session, project_id: str, kind: str, chapter: Chapter) -> None:
    """Rebuild this chapter's facts from its stored extraction. Safe to repeat."""
    existing = _entities(session, project_id, kind)
    ids = [e.id for e in existing]
    if ids:
        session.execute(
            delete(EntityFact).where(
                EntityFact.chapter_id == chapter.id, EntityFact.entity_id.in_(ids)
            )
        )
        for entity in existing:
            session.expire(entity, ["facts"])
    # A card is found only by its main name or a name the user merged into it by hand.
    # Aliases the model suggested are not trusted for that: one wrong alias (a friend's
    # name given as a nickname) would otherwise pull that friend into the card in every
    # later chapter. A missed match is only a duplicate, which the merge pass handles.
    by_key = {key: e for e in existing for key in {norm(e.name), *map(norm, e.pinned_names)}}
    cached = _cached(session, chapter, kind)
    paragraphs = chapter.text.split("\n\n")

    def fact(category: str, text: str = "", quote: str = "") -> EntityFact:
        paragraph = locate_quote(quote, paragraphs) if quote else None
        return EntityFact(
            chapter_id=chapter.id,
            chapter_hash=chapter.content_hash,
            category=category,
            text=text,
            # A quote that is not in the text is dropped rather than shown as a source.
            quote=quote if paragraph is not None else "",
            paragraph=paragraph,
        )

    items = ChapterEntities.model_validate(cached.payload).entities if cached else []
    # A name the model lists as an entry of its own is never also someone else's alias.
    own_names = {norm(i.name) for i in items if i.name.strip()}
    for item in items:
        name = item.name.strip()
        if not name:
            continue
        # Models still slip common nouns into aliases; proper names are capitalised.
        proper = [
            a.strip()
            for a in item.aliases
            if _is_proper(a) and norm(a) not in own_names - {norm(name)}
        ]
        # "The old man (also: Rykhtash)": the model put the word first and the name second.
        if proper and (not item.named or not _is_proper(name)):
            name, proper = proper[0], proper[1:]
        names = [name, *proper]
        # Lower case is never a proper name, whatever the model says.
        uncertain = item.group or not _is_proper(name) or (not item.named and name == item.name)
        entity = by_key.get(norm(name))
        if entity is None:
            # The chapter calls a known card by another word but names it among the aliases.
            entity = next((by_key[norm(a)] for a in proper if norm(a) in by_key), None)
        if entity is None:
            if uncertain and not any(f.text.strip() for f in item.facts):
                continue  # "a bird", mentioned once and never described: nothing to show
            entity = Entity(
                project_id=project_id, kind=kind, name=name, aliases=[], uncertain=uncertain
            )
            session.add(entity)
        elif not uncertain:
            entity.uncertain = False  # one chapter giving a proper name is enough
        taken = {norm(entity.name), *map(norm, entity.aliases)}
        new_aliases = [
            n
            for n in dict.fromkeys(names)
            if norm(n) not in taken and by_key.get(norm(n)) in (None, entity)
        ]
        entity.aliases = [*entity.aliases, *new_aliases]
        by_key.setdefault(norm(name), entity)
        entity.facts.append(fact(FACT_MENTION))
        seen = set()
        for found in item.facts:
            if found.text.strip() and norm(found.text) not in seen:
                seen.add(norm(found.text))
                entity.facts.append(fact(found.category, found.text.strip(), found.quote.strip()))
    session.flush()
    # An alias that is another card's main name was a mistake of an earlier chapter.
    cards = _entities(session, project_id, kind)
    main_names = {norm(e.name): e for e in cards}
    for entity in cards:
        kept = [
            a
            for a in entity.aliases
            if main_names.get(norm(a), entity) is entity or a in entity.pinned_names
        ]
        if kept != entity.aliases:
            entity.aliases = kept
    # An entity that existed only in the old version of this chapter is gone now.
    for entity in existing:
        session.refresh(entity, ["facts"])
        if not entity.facts and not entity.standalone and not entity.images:
            session.delete(entity)


def reconcile(state: State, config: RunnableConfig) -> dict:
    """One model call over the whole cast: merge the same entity under different names."""
    session, model, run = _context(config)
    # Cards the user split off by hand stay out of it.
    entities = sorted(
        (e for e in _entities(session, run.project_id, run.kind) if not e.standalone),
        key=lambda e: e.name,
    )
    if len(entities) < 2:
        return {}

    # Where each one appears and with whom: the book often calls a known one "the old man"
    # in a scene with the same people, and a nickname never shares a chapter with the name.
    positions = {
        c.id: c.position
        for c in session.scalars(select(Chapter).where(Chapter.project_id == run.project_id))
    }
    chapters_of = {
        e.id: {f.chapter_id for f in e.facts if f.chapter_id in positions} for e in entities
    }

    def companions(entity: Entity) -> list[str]:
        mine = chapters_of[entity.id]
        shared = [(len(mine & chapters_of[o.id]), o.name) for o in entities if o is not entity]
        return [name for count, name in sorted(shared, key=lambda s: -s[0]) if count][:4]

    def line(number: int, entity: Entity) -> str:
        also = f" (also: {', '.join(entity.aliases)})" if entity.aliases else ""
        mark = " [no proper name]" if entity.uncertain else ""
        role = [f.text for f in entity.facts if f.category == FACT_PROFILE][:2]
        looks = [f.text for f in entity.facts if f.category == FACT_PERMANENT][:3]
        where = sorted(positions[c] + 1 for c in chapters_of[entity.id])
        parts = [
            f"chapters {', '.join(map(str, where[:10]))}" if where else "",
            f"with {', '.join(companions(entity))}" if companions(entity) else "",
            "; ".join(role + looks),
        ]
        return f"{number}. {entity.name}{mark}{also}" + "".join(f" | {p}" for p in parts if p)

    listing = "\n".join(line(n, e) for n, e in enumerate(entities, 1))
    answer = model.invoke_json(
        f"merge_{run.kind}s",
        [SystemMessage(prompts.reconcile_system(run.kind)), HumanMessage(listing)],
        Groups,
    )
    merged: set[int] = set()
    for group in answer.groups:
        members = [n for n in dict.fromkeys(group) if 1 <= n <= len(entities) and n not in merged]
        if len(members) < 2:
            continue
        merged.update(members)
        # The entry with the most facts is the best known one: it keeps its name.
        # A card with a proper name wins over "the old man", then the best known one.
        main, *others = sorted(
            (entities[n - 1] for n in members), key=lambda e: (e.uncertain, -len(e.facts))
        )
        for other in others:
            absorb(session, main, other)
    session.commit()
    return {}


SUMMARY_BATCH = 4
SUMMARY_FACTS = 60
SUMMARY_MOMENTS = 20


def summarize(state: State, config: RunnableConfig) -> dict:
    """Last step of a run that finished or was cancelled: a coherent description per card."""
    session, model, run = _context(config)
    summarize_cards(session, model, run.project_id, run.kind)
    return {}


def _card_text(session: Session, number: int, entity: Entity) -> str:
    titles = {
        c.id: c.title or f"#{c.position + 1}"
        for c in session.scalars(select(Chapter).where(Chapter.project_id == entity.project_id))
    }
    positions = {
        c.id: c.position
        for c in session.scalars(select(Chapter).where(Chapter.project_id == entity.project_id))
    }
    chapters = sorted(
        {f.chapter_id for f in entity.facts if f.chapter_id in titles},
        key=lambda cid: positions[cid],
    )
    also = f" (also: {', '.join(entity.aliases)})" if entity.aliases else ""
    lines = [f"[{number}] {entity.name}{also}"]
    if chapters:
        lines.append(f"chapters ({len(chapters)}): " + ", ".join(titles[c] for c in chapters[:12]))
    if entity.summary.strip():
        lines.append(f"description so far: {entity.summary.strip()}")
    if entity.appearance.strip():
        lines.append(f"appearance so far: {entity.appearance.strip()}")
    # Facts are taken chapter by chapter in turn, so a main character's description covers
    # the whole book and not only the chapters read first. Looks come with their quote: the
    # model can tell a lasting trait from a moment ("looked with one eye" is not one-eyed).
    facts = [f for f in entity.facts if f.text.strip()]
    lasting = [f for f in facts if f.category in (FACT_PROFILE, FACT_PERMANENT)]
    moments = [f for f in facts if f.category == FACT_STATE]
    seen: set[str] = set()
    for fact in _spread(lasting or moments, positions, SUMMARY_FACTS, seen):
        lines.append(_fact_line(fact, "looks" if fact.category != FACT_PROFILE else "about"))
    # Looks of one moment (clothes, wounds) for the appearance: what repeats is the usual look.
    if lasting:
        for fact in _spread(moments, positions, SUMMARY_MOMENTS, seen):
            lines.append(_fact_line(fact, "in one chapter"))
    return "\n".join(lines)


def _spread(facts: list, positions: dict[str, int], limit: int, seen: set[str]) -> list:
    """Up to `limit` facts with different texts, one chapter after another in turn."""
    by_chapter: dict[str, list] = {}
    for fact in sorted(facts, key=lambda f: positions.get(f.chapter_id, 10**6)):
        by_chapter.setdefault(fact.chapter_id, []).append(fact)
    queues = list(by_chapter.values())
    picked = []
    while queues and len(picked) < limit:
        for queue in list(queues):
            if not queue:
                queues.remove(queue)
                continue
            fact = queue.pop(0)
            if norm(fact.text) in seen:
                continue
            seen.add(norm(fact.text))
            picked.append(fact)
            if len(picked) >= limit:
                break
    return picked


def _fact_line(fact, label: str) -> str:
    quote = " ".join(fact.quote.split())
    if label == "about" or not quote:
        return f"- {label}: {fact.text.strip()}"
    return f"- {label}: {fact.text.strip()} (text: «{quote[:140]}»)"


def summarize_cards(session: Session, model: TextModel, project_id: str, kind: str) -> None:
    """A card with no facts but its name is left as it is: there is nothing to tell.
    A batch whose answer cannot be read keeps the old text; the rest still gets written."""
    cards = [
        e
        for e in sorted(_entities(session, project_id, kind), key=lambda e: e.name)
        if any(f.text.strip() for f in e.facts)
    ]
    for start in range(0, len(cards), SUMMARY_BATCH):
        batch = cards[start : start + SUMMARY_BATCH]
        listing = "\n\n".join(_card_text(session, n, e) for n, e in enumerate(batch, 1))
        try:
            answer = model.invoke_json(
                f"summarize_{kind}s",
                [SystemMessage(prompts.summary_system(kind)), HumanMessage(listing)],
                Summaries,
            )
        except BadModelOutput:
            continue
        for item in answer.summaries:
            if not 1 <= item.number <= len(batch):
                continue
            card = batch[item.number - 1]
            if item.text.strip():
                card.summary = item.text.strip()
            if item.appearance.strip():
                card.appearance = item.appearance.strip()
        session.commit()


def absorb(session: Session, main: Entity, other: Entity) -> list[str]:
    """Fold `other` into `main`: its names become other names of `main`, its facts move.
    Returns the names that were added."""
    taken = {norm(main.name), *map(norm, main.aliases)}
    added = [n for n in dict.fromkeys([other.name, *other.aliases]) if norm(n) not in taken]
    main.aliases = [*main.aliases, *added]
    main.pinned_names = [*main.pinned_names, *other.pinned_names]
    main.uncertain = main.uncertain and other.uncertain
    for item in list(other.facts):
        item.entity = main
    for image in list(other.images):
        image.entity = main
        image.is_main = False  # the card that stays keeps its own main picture
    session.flush()
    session.delete(other)
    # One mention per chapter is enough after a merge.
    seen: set[str] = set()
    for item in list(main.facts):
        if item.category == FACT_MENTION:
            if item.chapter_id in seen:
                main.facts.remove(item)
            seen.add(item.chapter_id)
    return added


def merge_by_hand(session: Session, main: Entity, other: Entity) -> None:
    """The user says these two cards are one. Remembered across later runs."""
    added = absorb(session, main, other)
    main.pinned_names = list(dict.fromkeys([*main.pinned_names, *added]))


def split_by_hand(session: Session, entity: Entity, name: str) -> Entity:
    """The user says `name` is someone else. The new card takes the facts of the
    chapters where the book calls them by that name; stored answers are re-applied,
    so no model is called."""
    entity.aliases = [a for a in entity.aliases if norm(a) != norm(name)]
    entity.pinned_names = [a for a in entity.pinned_names if norm(a) != norm(name)]
    separate = Entity(
        project_id=entity.project_id, kind=entity.kind, name=name, aliases=[], standalone=True
    )
    session.add(separate)
    session.flush()
    for chapter_id in {f.chapter_id for f in entity.facts}:
        chapter = session.get(Chapter, chapter_id)
        if chapter is not None and _cached(session, chapter, entity.kind):
            apply_extraction(session, entity.project_id, entity.kind, chapter)
    return separate


def _next(state: State, config: RunnableConfig) -> str:
    session, _, run = _context(config)
    session.refresh(run)
    if run.cancel_requested:
        # Stopped by the user: describe what has been found so far.
        return "summarize"
    return "extract" if state["pending"] else "reconcile"


def build_graph():
    graph = StateGraph(State)
    graph.add_node("extract", extract)
    graph.add_node("merge", merge)
    graph.add_node("reconcile", reconcile)
    graph.add_node("summarize", summarize)
    graph.add_conditional_edges(START, _next, ["extract", "reconcile", "summarize"])
    graph.add_edge("extract", "merge")
    graph.add_conditional_edges("merge", _next, ["extract", "reconcile", "summarize"])
    graph.add_edge("reconcile", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile()


GRAPH = build_graph()

__all__ = ["FACT_MENTION", "FACT_PERMANENT", "FACT_STATE", "GRAPH", "Estimate", "estimate"]
