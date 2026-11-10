from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.analysis import entities as analysis
from app.analysis import prompts, runner
from app.db import SessionDep
from app.llm.calls import ModelNotConfigured, TextModel
from app.models import (
    FACT_PERMANENT,
    FACT_PROFILE,
    FACT_STATE,
    KIND_CHARACTER,
    KIND_LOCATION,
    AnalysisRun,
    Chapter,
    ChapterExtraction,
    Entity,
    Project,
    UsageEvent,
)

router = APIRouter(prefix="/api", tags=["analysis"])


class RunRequest(BaseModel):
    kind: str
    # Empty means the whole book.
    chapter_ids: list[str] = []
    # Start from scratch: earlier answers and cards are forgotten (see start_fresh).
    fresh: bool = False


class RunOut(BaseModel):
    id: str
    kind: str
    status: str
    total: int
    done: int
    error: str
    created_at: datetime


class EntityBrief(BaseModel):
    id: str
    name: str
    aliases: list[str]
    chapters: int
    facts: int
    stale: bool
    # No proper name or a group: shown apart, "in question".
    uncertain: bool = False


class FactOut(BaseModel):
    text: str
    quote: str
    chapter_id: str
    paragraph: int | None
    stale: bool


class ChapterFacts(BaseModel):
    chapter_id: str
    chapter_title: str
    position: int
    stale: bool
    facts: list[FactOut]


class EntityOut(BaseModel):
    id: str
    kind: str
    name: str
    aliases: list[str]
    description: str
    summary: str
    profile: list[FactOut]
    permanent: list[FactOut]
    timeline: list[ChapterFacts]


class MergeRequest(BaseModel):
    other_id: str


class DescriptionPatch(BaseModel):
    text: str = Field(max_length=6000)


class SplitRequest(BaseModel):
    name: str


class UsageRow(BaseModel):
    operation: str
    connection_name: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int


class UsageOut(BaseModel):
    rows: list[UsageRow]
    input_tokens: int
    output_tokens: int


def _project(session: SessionDep, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project_not_found")
    return project


def _kind(kind: str) -> str:
    if kind not in (KIND_CHARACTER, KIND_LOCATION):
        raise HTTPException(422, "bad_kind")
    return kind


def _chapters(project: Project, chapter_ids: list[str]) -> list[Chapter]:
    ordered = sorted(project.chapters, key=lambda c: c.position)
    if not chapter_ids:
        return ordered
    wanted = set(chapter_ids)
    return [c for c in ordered if c.id in wanted]


def _run_out(run: AnalysisRun) -> RunOut:
    return RunOut(
        id=run.id,
        kind=run.kind,
        status=run.status,
        total=len(run.chapter_ids),
        done=len(run.done_chapter_ids),
        error=run.error,
        created_at=run.created_at,
    )


@router.post("/projects/{project_id}/analysis/estimate")
def estimate(project_id: str, body: RunRequest, session: SessionDep) -> analysis.Estimate:
    project = _project(session, project_id)
    try:
        overhead = TextModel(session, project.id).request_overhead
    except ModelNotConfigured:
        overhead = 0  # the estimate is still useful before a model is chosen
    return analysis.estimate(
        session, _chapters(project, body.chapter_ids), _kind(body.kind), overhead, body.fresh
    )


@router.post("/projects/{project_id}/analysis")
def start_run(project_id: str, body: RunRequest, session: SessionDep) -> RunOut:
    project = _project(session, project_id)
    chapters = _chapters(project, body.chapter_ids)
    if not chapters:
        raise HTTPException(422, "no_chapters_selected")
    # One run per project at a time: free models have tight rate limits.
    if runner.active_run(session, project.id):
        raise HTTPException(409, "analysis_already_running")
    try:
        TextModel(session, project.id)
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    if body.fresh:
        analysis.start_fresh(session, project.id, chapters, _kind(body.kind))
    run = AnalysisRun(
        project_id=project.id, kind=_kind(body.kind), chapter_ids=[c.id for c in chapters]
    )
    session.add(run)
    session.commit()
    runner.start(run.id)
    return _run_out(run)


@router.get("/projects/{project_id}/analysis")
def latest_run(project_id: str, kind: str, session: SessionDep) -> RunOut | None:
    run = session.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == project_id, AnalysisRun.kind == _kind(kind))
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    ).first()
    return _run_out(run) if run else None


@router.post("/analysis/{run_id}/cancel")
def cancel_run(run_id: str, session: SessionDep) -> RunOut:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "run_not_found")
    # The worker stops after the chapter it is reading.
    run.cancel_requested = True
    session.commit()
    return _run_out(run)


@router.get("/projects/{project_id}/entities")
def list_entities(project_id: str, kind: str, session: SessionDep) -> list[EntityBrief]:
    project = _project(session, project_id)
    hashes = {c.id: c.content_hash for c in project.chapters}
    rows = session.scalars(
        select(Entity).where(Entity.project_id == project_id, Entity.kind == _kind(kind))
    ).all()
    briefs = [
        EntityBrief(
            id=e.id,
            name=e.name,
            aliases=e.aliases,
            chapters=len({f.chapter_id for f in e.facts}),
            facts=sum(f.category != analysis.FACT_MENTION for f in e.facts),
            stale=any(hashes.get(f.chapter_id) != f.chapter_hash for f in e.facts),
            uncertain=e.uncertain,
        )
        for e in rows
    ]
    # Main characters first: they appear in the most chapters.
    return sorted(briefs, key=lambda b: (-b.chapters, b.name))


class ChapterStatus(BaseModel):
    # Read with the same text and prompt: running them again costs nothing.
    read: list[str]
    # Read before, but their text has changed since: worth reading again.
    changed: list[str]


@router.get("/projects/{project_id}/analysis/chapters")
def chapter_status(project_id: str, kind: str, session: SessionDep) -> ChapterStatus:
    project = _project(session, project_id)
    stored = {
        row.chapter_id: row
        for row in session.scalars(
            select(ChapterExtraction).where(
                ChapterExtraction.project_id == project.id,
                ChapterExtraction.kind == _kind(kind),
            )
        )
    }
    read, changed = [], []
    for chapter in project.chapters:
        row = stored.get(chapter.id)
        if row is None:
            continue
        if row.chapter_hash != chapter.content_hash:
            changed.append(chapter.id)
        elif row.payload.get("version") == prompts.PROMPT_VERSION:
            read.append(chapter.id)
    return ChapterStatus(read=read, changed=changed)


class StaleOut(BaseModel):
    # Chapters read before their text changed: reading them again refreshes the cards.
    chapter_ids: list[str]
    # Facts left from chapters that were deleted; the next run drops them.
    orphaned_facts: int


@router.get("/projects/{project_id}/stale")
def stale(project_id: str, kind: str, session: SessionDep) -> StaleOut:
    project = _project(session, project_id)
    hashes = {c.id: c.content_hash for c in project.chapters}
    changed: set[str] = set()
    orphaned = 0
    for entity in session.scalars(
        select(Entity).where(Entity.project_id == project_id, Entity.kind == _kind(kind))
    ):
        for fact in entity.facts:
            if fact.chapter_id not in hashes:
                orphaned += 1
            elif hashes[fact.chapter_id] != fact.chapter_hash:
                changed.add(fact.chapter_id)
    ordered = sorted(
        changed, key=lambda cid: next(c.position for c in project.chapters if c.id == cid)
    )
    return StaleOut(chapter_ids=ordered, orphaned_facts=orphaned)


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str, session: SessionDep) -> EntityOut:
    entity = session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(404, "entity_not_found")
    chapters = {c.id: c for c in _project(session, entity.project_id).chapters}

    def stale(fact) -> bool:
        chapter = chapters.get(fact.chapter_id)
        return chapter is None or chapter.content_hash != fact.chapter_hash

    def out(fact) -> FactOut:
        return FactOut(
            text=fact.text,
            quote=fact.quote,
            chapter_id=fact.chapter_id,
            paragraph=fact.paragraph,
            stale=stale(fact),
        )

    def position(fact) -> int:
        chapter = chapters.get(fact.chapter_id)
        return chapter.position if chapter else len(chapters)

    facts = sorted(entity.facts, key=position)
    timeline: dict[str, ChapterFacts] = {}
    for fact in facts:
        chapter = chapters.get(fact.chapter_id)
        entry = timeline.setdefault(
            fact.chapter_id,
            ChapterFacts(
                chapter_id=fact.chapter_id,
                chapter_title=chapter.title if chapter else "",
                position=position(fact),
                stale=stale(fact),
                facts=[],
            ),
        )
        if fact.category == FACT_STATE:
            entry.facts.append(out(fact))
    return EntityOut(
        id=entity.id,
        kind=entity.kind,
        name=entity.name,
        aliases=entity.aliases,
        description=entity.description,
        summary=entity.summary,
        profile=[out(f) for f in facts if f.category == FACT_PROFILE],
        permanent=[out(f) for f in facts if f.category == FACT_PERMANENT],
        timeline=list(timeline.values()),
    )


@router.put("/entities/{entity_id}/description")
def save_description(entity_id: str, body: DescriptionPatch, session: SessionDep) -> EntityOut:
    """The author's own description of a card; searches never touch it."""
    entity = session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(404, "entity_not_found")
    entity.description = body.text.strip()
    session.commit()
    return get_entity(entity_id, session)


@router.post("/entities/{entity_id}/merge")
def merge_entities(entity_id: str, body: MergeRequest, session: SessionDep) -> EntityOut:
    """Cards are read-only, but who is who is the user's call: models get names wrong."""
    main = session.get(Entity, entity_id)
    other = session.get(Entity, body.other_id)
    if main is None or other is None:
        raise HTTPException(404, "entity_not_found")
    if main.id == other.id or (main.project_id, main.kind) != (other.project_id, other.kind):
        raise HTTPException(422, "bad_merge")
    analysis.merge_by_hand(session, main, other)
    session.commit()
    return get_entity(main.id, session)


@router.post("/entities/{entity_id}/split")
def split_entity(entity_id: str, body: SplitRequest, session: SessionDep) -> EntityOut:
    entity = session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(404, "entity_not_found")
    if analysis.norm(body.name) not in map(analysis.norm, entity.aliases):
        raise HTTPException(422, "bad_split")
    separate = analysis.split_by_hand(session, entity, body.name)
    session.commit()
    return get_entity(separate.id, session)


@router.get("/projects/{project_id}/usage")
def usage(project_id: str, session: SessionDep) -> UsageOut:
    grouped = session.execute(
        select(
            UsageEvent.operation,
            UsageEvent.connection_name,
            UsageEvent.model,
            func.count(),
            func.sum(UsageEvent.input_tokens),
            func.sum(UsageEvent.output_tokens),
        )
        .where(UsageEvent.project_id == project_id)
        .group_by(UsageEvent.operation, UsageEvent.connection_name, UsageEvent.model)
        .order_by(UsageEvent.operation)
    ).all()
    rows = [
        UsageRow(
            operation=operation,
            connection_name=connection,
            model=model,
            calls=calls,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
        )
        for operation, connection, model, calls, tokens_in, tokens_out in grouped
    ]
    return UsageOut(
        rows=rows,
        input_tokens=sum(r.input_tokens for r in rows),
        output_tokens=sum(r.output_tokens for r in rows),
    )
