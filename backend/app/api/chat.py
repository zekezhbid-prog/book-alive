from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete

from app.db import SessionDep
from app.llm.calls import BadModelOutput, ModelNotConfigured, TextModel
from app.models import ChatMessage, Project
from app.rag import chat

router = APIRouter(prefix="/api", tags=["chat"])


class CitationOut(BaseModel):
    n: int
    chapter_id: str
    chapter_title: str
    paragraph: int
    quote: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: list[CitationOut]
    created_at: datetime


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    # The chapter open in the reader, so "here" and "this chapter" can be understood.
    chapter_id: str = ""


def _out(message: ChatMessage) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        citations=message.citations,
        created_at=message.created_at,
    )


def _project(session: SessionDep, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project_not_found")
    return project


@router.get("/projects/{project_id}/chat")
def messages(project_id: str, session: SessionDep) -> list[MessageOut]:
    return [_out(m) for m in chat.history(session, _project(session, project_id).id)]


@router.post("/projects/{project_id}/chat")
def ask(project_id: str, body: Question, session: SessionDep) -> list[MessageOut]:
    project = _project(session, project_id)
    try:
        model = TextModel(session, project.id)
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        asked, reply = chat.ask(session, project, model, body.question.strip(), body.chapter_id)
    except BadModelOutput as exc:
        raise HTTPException(502, f"bad_model_output: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return [_out(asked), _out(reply)]


@router.delete("/projects/{project_id}/chat", status_code=204)
def clear(project_id: str, session: SessionDep) -> None:
    session.execute(delete(ChatMessage).where(ChatMessage.project_id == project_id))
    session.commit()
