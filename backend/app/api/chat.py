from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete

from app.db import SessionDep
from app.llm.calls import BadModelOutput, ModelNotConfigured, TextModel
from app.models import MODE_WRITER, ChatMessage, Project
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
        model = TextModel(session, project.id, "chat")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        asked, reply = chat.ask(session, project, model, body.question.strip(), body.chapter_id)
    except BadModelOutput as exc:
        raise HTTPException(502, f"bad_model_output: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return [_out(asked), _out(reply)]


class StreamLine(BaseModel):
    """One line of `/chat/stream`: a step the agent has started, the finished exchange,
    or an error that happened after the response had begun."""

    type: Literal["status", "done", "error"]
    code: str = ""  # status: index | search | read | think
    detail: str = ""
    messages: list[MessageOut] = Field(default_factory=list)


def _text_model(project_id: str, session: SessionDep) -> TextModel:
    """Checked before the stream starts, so these failures still get a proper status code."""
    _project(session, project_id)
    try:
        return TextModel(session, project_id, "chat")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc


TextModelDep = Annotated[TextModel, Depends(_text_model)]


@router.post("/projects/{project_id}/chat/stream")
def ask_stream(
    project_id: str, body: Question, session: SessionDep, model: TextModelDep
) -> Iterator[StreamLine]:
    """The same question as `/chat`, answered as JSON Lines: a `status` line for every
    step the agent takes, then one `done` line with both messages, or `error`."""
    project = _project(session, project_id)
    try:
        for event in chat.ask_events(
            session, project, model, body.question.strip(), body.chapter_id
        ):
            if isinstance(event, chat.Reply):
                yield StreamLine(type="done", messages=[_out(event.asked), _out(event.reply)])
            else:
                yield StreamLine(type="status", code=event.code, detail=event.detail)
    except BadModelOutput as exc:
        yield StreamLine(type="error", detail=f"bad_model_output: {exc}")
    except Exception as exc:  # noqa: BLE001 - the response has started: report in it
        yield StreamLine(type="error", detail=f"provider_error: {str(exc)[:300]}")


@router.post("/projects/{project_id}/chat/suggest")
def suggest(project_id: str, body: Question, session: SessionDep) -> list[MessageOut]:
    """Writer projects only: ideas for what happens next. `question` is the label the
    user sees in the conversation."""
    project = _project(session, project_id)
    if project.mode != MODE_WRITER:
        raise HTTPException(409, "reader_mode_readonly")
    try:
        model = TextModel(session, project.id, "chat")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        asked, reply = chat.suggest(session, project, model, body.question.strip(), body.chapter_id)
    except BadModelOutput as exc:
        raise HTTPException(502, f"bad_model_output: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return [_out(asked), _out(reply)]


@router.delete("/projects/{project_id}/chat", status_code=204)
def clear(project_id: str, session: SessionDep) -> None:
    session.execute(delete(ChatMessage).where(ChatMessage.project_id == project_id))
    session.commit()
