from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import SessionDep
from app.llm.calls import BadModelOutput, ModelNotConfigured, TextModel
from app.models import MODE_WRITER, Project
from app.review import service

router = APIRouter(prefix="/api", tags=["review"])


class ReviewRequest(BaseModel):
    kind: Literal["grammar", "editorial", "contradictions"]
    # Required for grammar and editorial; contradictions look at the whole book.
    chapter_id: str = ""


class ReviewOut(BaseModel):
    kind: str
    remarks: list[service.Remark]


@router.post("/projects/{project_id}/review")
def review(project_id: str, body: ReviewRequest, session: SessionDep) -> ReviewOut:
    """Writer projects only. Reads the book and returns remarks; changes and stores nothing."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project_not_found")
    if project.mode != MODE_WRITER:
        raise HTTPException(409, "reader_mode_readonly")
    chapter = None
    if body.kind != service.KIND_CONTRADICTIONS:
        chapter = next((c for c in project.chapters if c.id == body.chapter_id), None)
        if chapter is None:
            raise HTTPException(404, "chapter_not_found")
    try:
        model = TextModel(session, project.id)
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        if chapter is None:
            remarks = service.check_contradictions(session, model, project)
        else:
            remarks = service.check_text(model, chapter, body.kind)
    except BadModelOutput as exc:
        raise HTTPException(502, f"bad_model_output: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return ReviewOut(kind=body.kind, remarks=remarks)
