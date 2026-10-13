"""Finding characters and locations, chapter by chapter, as a LangGraph loop.

    extract -> merge -+-> extract ...      (next chapter)
                      +-> reconcile -> END (no chapters left)
                      +-> END              (cancelled)

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
from app.llm.calls import TextModel, estimate_tokens
from app.models import (
    FACT_PERMANENT,
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
    category: Literal["permanent", "state"] = FACT_STATE
    text: str
    quote: str = ""


class ExtractedEntity(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)


class ChapterEntities(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)


class Groups(BaseModel):
    groups: list[list[int]] = Field(default_factory=list)


# ---------- helpers ----------


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


# ---------- estimate ----------


class Estimate(BaseModel):
    chapters: int
    cached: int  # already read with the same text: free
    requests: int
    input_tokens: int
    output_tokens: int


def estimate(
    session: Session, chapters: list[Chapter], kind: str, request_overhead: int = 0
) -> Estimate:
    """`request_overhead`: tokens the connection adds to every request on its own."""
    system_tokens = (
        estimate_tokens(prompts.extract_system(kind)) + PROMPT_OVERHEAD_TOKENS + request_overhead
    )
    result = Estimate(chapters=len(chapters), cached=0, requests=0, input_tokens=0, output_tokens=0)
    for chapter in chapters:
        if not chapter.text.strip() or _cached(session, chapter, kind):
            result.cached += 1
            continue
        for part in chunks(chapter.text):
            tokens = estimate_tokens(part)
            result.requests += 1
            result.input_tokens += tokens + system_tokens
            # Observed on prose: the answer runs to roughly a fifth of the chapter.
            result.output_tokens += max(300, tokens // 5)
    if result.requests:
        result.requests += 1  # the final pass that merges duplicate names
        result.input_tokens += 1500 + request_overhead
        result.output_tokens += 200
    return result


# ---------- graph ----------


class State(TypedDict):
    run_id: str
    pending: list[str]


def _context(config: RunnableConfig) -> tuple[Session, TextModel, AnalysisRun]:
    session: Session = config["configurable"]["session"]
    run = session.get(AnalysisRun, config["configurable"]["run_id"])
    return session, config["configurable"]["model"], run


def extract(state: State, config: RunnableConfig) -> dict:
    session, model, run = _context(config)
    chapter = session.get(Chapter, state["pending"][0])
    if chapter is None or not chapter.text.strip() or _cached(session, chapter, run.kind):
        return {}
    known = _entities(session, run.project_id, run.kind)
    known_text = "\n".join(
        f"- {e.name}" + (f" (also: {', '.join(e.aliases)})" if e.aliases else "") for e in known
    )
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
    by_key = {key: e for e in existing for key in {norm(e.name), *map(norm, e.aliases)}}
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

    for item in ChapterEntities.model_validate(cached.payload).entities if cached else []:
        name = item.name.strip()
        if not name:
            continue
        # Models still slip common nouns into aliases; proper names are capitalised.
        names = [name, *(a.strip() for a in item.aliases if a.strip()[:1].isupper())]
        # Only the entry's own name identifies it. Matching on aliases too would glue
        # different characters together through one shared nickname.
        entity = by_key.get(norm(name))
        if entity is None:
            entity = Entity(project_id=project_id, kind=kind, name=names[0], aliases=[])
            session.add(entity)
        taken = {norm(entity.name), *map(norm, entity.aliases)}
        new_aliases = [n for n in dict.fromkeys(names) if norm(n) not in taken]
        entity.aliases = [*entity.aliases, *new_aliases]
        for known_name in names:
            by_key.setdefault(norm(known_name), entity)
        entity.facts.append(fact(FACT_MENTION))
        seen = set()
        for found in item.facts:
            if found.text.strip() and norm(found.text) not in seen:
                seen.add(norm(found.text))
                entity.facts.append(fact(found.category, found.text.strip(), found.quote.strip()))
    session.flush()
    # An entity that existed only in the old version of this chapter is gone now.
    for entity in existing:
        session.refresh(entity, ["facts"])
        if not entity.facts:
            session.delete(entity)


def reconcile(state: State, config: RunnableConfig) -> dict:
    """One model call over the whole cast: merge the same entity under different names."""
    session, model, run = _context(config)
    entities = sorted(_entities(session, run.project_id, run.kind), key=lambda e: e.name)
    if len(entities) < 2:
        return {}

    def line(number: int, entity: Entity) -> str:
        also = f" (also: {', '.join(entity.aliases)})" if entity.aliases else ""
        details = [f.text for f in entity.facts if f.category == FACT_PERMANENT][:3]
        return f"{number}. {entity.name}{also}" + (f" - {'; '.join(details)}" if details else "")

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
        main, *others = sorted((entities[n - 1] for n in members), key=lambda e: -len(e.facts))
        for other in others:
            taken = {norm(main.name), *map(norm, main.aliases)}
            extra = [n for n in [other.name, *other.aliases] if norm(n) not in taken]
            main.aliases = [*main.aliases, *dict.fromkeys(extra)]
            for item in list(other.facts):
                item.entity = main
            session.flush()
            session.delete(other)
    # One mention per chapter is enough after a merge.
    for entity in entities:
        seen: set[str] = set()
        for item in list(entity.facts):
            if item.category == FACT_MENTION:
                if item.chapter_id in seen:
                    entity.facts.remove(item)
                seen.add(item.chapter_id)
    session.commit()
    return {}


def _next(state: State, config: RunnableConfig) -> str:
    session, _, run = _context(config)
    session.refresh(run)
    if run.cancel_requested:
        return END
    return "extract" if state["pending"] else "reconcile"


def build_graph():
    graph = StateGraph(State)
    graph.add_node("extract", extract)
    graph.add_node("merge", merge)
    graph.add_node("reconcile", reconcile)
    graph.add_conditional_edges(START, _next, ["extract", "reconcile", END])
    graph.add_edge("extract", "merge")
    graph.add_conditional_edges("merge", _next, ["extract", "reconcile", END])
    graph.add_edge("reconcile", END)
    return graph.compile()


GRAPH = build_graph()

__all__ = ["FACT_MENTION", "FACT_PERMANENT", "FACT_STATE", "GRAPH", "Estimate", "estimate"]
