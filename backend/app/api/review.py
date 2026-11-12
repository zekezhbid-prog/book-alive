from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db import SessionDep
from app.llm.calls import BadModelOutput, ModelNotConfigured, TextModel
from app.models import MODE_WRITER, BetaReview, Project, text_hash
from app.review import beta, checks, continuity, service, typography
from app.services import versions

router = APIRouter(prefix="/api", tags=["review"])

Kind = Literal["grammar", "editorial", "contradictions"]
# Label of the version saved right before "Fix all"; the frontend translates it.
FIX_LABEL = "typography"


class CheckOut(BaseModel):
    id: str
    kind: str
    engine: str
    default: bool
    # Needs every chapter read for notes first (one request per chapter, see `review`).
    reads_text: bool = False


class ChecksOut(BaseModel):
    language: str
    checks: list[CheckOut]


class ReviewRequest(BaseModel):
    kind: Kind
    # Required for grammar and editorial. For contradictions: empty compares the whole book;
    # a chapter only takes its notes for the text items (nothing is returned), so the client
    # can show progress and no single request runs for minutes.
    chapter_id: str = ""
    # The ticked items; missing means the section's defaults.
    checks: list[str] | None = None


class ReviewOut(BaseModel):
    kind: str
    remarks: list[service.Remark]


class FixRequest(BaseModel):
    chapter_ids: list[str]


class FixOut(BaseModel):
    changed: list[str]  # ids of the chapters whose text changed
    version: int | None = None  # the version saved before the fix, if one was needed


def _writer_project(session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project_not_found")
    if project.mode != MODE_WRITER:
        raise HTTPException(409, "reader_mode_readonly")
    return project


def _language(project: Project) -> str:
    return checks.detect_language("\n\n".join(c.text for c in project.chapters[:20]))


@router.get("/projects/{project_id}/review/checks")
def list_checks(project_id: str, session: SessionDep) -> ChecksOut:
    """The ticks the check dialogs offer for this book, by the language of its text."""
    project = _writer_project(session, project_id)
    language = _language(project)
    return ChecksOut(
        language=language,
        checks=[
            CheckOut(
                id=c.id, kind=c.kind, engine=c.engine, default=c.default, reads_text=c.reads_text
            )
            for c in checks.offered(language)
        ],
    )


@router.post("/projects/{project_id}/review")
def review(project_id: str, body: ReviewRequest, session: SessionDep) -> ReviewOut:
    """Writer projects only. Reads the book and returns remarks; changes and stores nothing.
    Items computed without a model cost nothing and need no model configured."""
    project = _writer_project(session, project_id)
    language = _language(project)
    items = checks.chosen(body.kind, language, body.checks)
    chapter = None
    if body.kind != service.KIND_CONTRADICTIONS or body.chapter_id:
        chapter = next((c for c in project.chapters if c.id == body.chapter_id), None)
        if chapter is None:
            raise HTTPException(404, "chapter_not_found")
    notes_only = body.kind == service.KIND_CONTRADICTIONS and chapter is not None
    if notes_only and not any(c.reads_text for c in items):
        return ReviewOut(kind=body.kind, remarks=[])
    model = None
    if any(c.engine == checks.AI for c in items):
        try:
            model = TextModel(session, project.id, "chat")
        except ModelNotConfigured as exc:
            raise HTTPException(409, str(exc)) from exc
    yo: dict[str, str] = {}
    if any(c.id == "yo_ru" for c in items):
        yo = typography.yo_words([c.text for c in project.chapters])
    try:
        if notes_only:
            continuity.read_notes(session, model, project, chapter)
            remarks = []
        elif chapter is None:
            remarks = service.check_contradictions(session, model, project, items, language)
        else:
            remarks = service.check_text(model, chapter, body.kind, items, language, yo)
    except BadModelOutput as exc:
        raise HTTPException(502, f"bad_model_output: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return ReviewOut(kind=body.kind, remarks=remarks)


@router.post("/projects/{project_id}/review/fix")
def fix(project_id: str, body: FixRequest, session: SessionDep) -> FixOut:
    """Apply the typesetting rules to the chosen chapters of a Russian book. Unsaved work is
    saved as a version first, so the text before the fix can always be rolled back to."""
    project = _writer_project(session, project_id)
    if _language(project) != checks.LANG_RU:
        raise HTTPException(409, "fix_language_unsupported")
    wanted = set(body.chapter_ids)
    targets = [c for c in project.chapters if c.id in wanted]
    fixed = {c.id: typography.fix_typography(c.text) for c in targets}
    changed = [c for c in targets if fixed[c.id] != c.text]
    if not changed:
        return FixOut(changed=[])
    saved = None
    if versions.changes_since(project, versions.latest_version(session, project.id)).dirty:
        saved = versions.commit(session, project, FIX_LABEL).number
    for chapter in changed:
        chapter.text = fixed[chapter.id]
        chapter.content_hash = text_hash(chapter.text)
    session.commit()
    return FixOut(changed=[c.id for c in changed], version=saved)


# ---------------------------------------------------------------- beta reader


class BetaRequest(BaseModel):
    chapter_id: str
    reader: str = "casual"
    tone: str = "soft"
    asks: list[str] | None = None


class BetaOut(BaseModel):
    id: str
    chapter_id: str
    reader: str
    tone: str
    asks: list[str]
    text: str
    created_at: datetime
    # The chapter text changed after the review was written.
    outdated: bool = False


def _beta_out(review: BetaReview, chapters: dict[str, str]) -> BetaOut:
    return BetaOut(
        id=review.id,
        chapter_id=review.chapter_id,
        reader=review.reader,
        tone=review.tone,
        asks=review.asks,
        text=review.text,
        created_at=review.created_at,
        outdated=chapters.get(review.chapter_id, review.chapter_hash) != review.chapter_hash,
    )


@router.post("/projects/{project_id}/beta")
def beta_review(project_id: str, body: BetaRequest, session: SessionDep) -> BetaOut:
    """A beta reader's review of one chapter, kept with the chapter."""
    project = _writer_project(session, project_id)
    chapter = next((c for c in project.chapters if c.id == body.chapter_id), None)
    if chapter is None:
        raise HTTPException(404, "chapter_not_found")
    if not chapter.text.strip():
        raise HTTPException(409, "chapter_empty")
    try:
        model = TextModel(session, project.id, "chat")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        review = beta.review_chapter(
            session, model, project, chapter, body.reader, body.tone, body.asks or beta.DEFAULT_ASKS
        )
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return _beta_out(review, {chapter.id: chapter.content_hash})


@router.get("/projects/{project_id}/beta")
def beta_reviews(project_id: str, session: SessionDep) -> list[BetaOut]:
    """Every kept review of the book, newest first."""
    project = _writer_project(session, project_id)
    hashes = {c.id: c.content_hash for c in project.chapters}
    rows = session.scalars(
        select(BetaReview)
        .where(BetaReview.project_id == project.id)
        .order_by(BetaReview.created_at.desc())
    ).all()
    return [_beta_out(r, hashes) for r in rows if r.chapter_id in hashes]


@router.delete("/projects/{project_id}/beta/{review_id}", status_code=204)
def delete_beta_review(project_id: str, review_id: str, session: SessionDep) -> None:
    review = session.get(BetaReview, review_id)
    if review is None or review.project_id != project_id:
        raise HTTPException(404, "review_not_found")
    session.delete(review)
    session.commit()
