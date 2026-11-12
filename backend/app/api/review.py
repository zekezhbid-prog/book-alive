from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import SessionDep
from app.llm.calls import BadModelOutput, ModelNotConfigured, TextModel
from app.models import MODE_WRITER, Project, text_hash
from app.review import checks, service, typography
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


class ChecksOut(BaseModel):
    language: str
    checks: list[CheckOut]


class ReviewRequest(BaseModel):
    kind: Kind
    # Required for grammar and editorial; contradictions look at the whole book.
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
            CheckOut(id=c.id, kind=c.kind, engine=c.engine, default=c.default)
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
    if body.kind != service.KIND_CONTRADICTIONS:
        chapter = next((c for c in project.chapters if c.id == body.chapter_id), None)
        if chapter is None:
            raise HTTPException(404, "chapter_not_found")
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
        if chapter is None:
            remarks = service.check_contradictions(session, model, project, items) if model else []
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
