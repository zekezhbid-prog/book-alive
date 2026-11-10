from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import SessionDep
from app.llm.calls import BadModelOutput, ModelNotConfigured, TextModel
from app.models import MODE_WRITER, ChatMessage, ChatThread, Project
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


def _thread(session: SessionDep, project_id: str, thread_id: str) -> ChatThread:
    thread = session.get(ChatThread, thread_id)
    if thread is None or thread.project_id != project_id:
        raise HTTPException(404, "chat_not_found")
    return thread


class ThreadOut(BaseModel):
    id: str
    title: str
    # Chapters the conversation searches and reads; empty means the whole book.
    chapter_ids: list[str]
    created_at: datetime
    updated_at: datetime


class ThreadIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    chapter_ids: list[str] | None = None


def _thread_out(project: Project, thread: ChatThread) -> ThreadOut:
    return ThreadOut(
        id=thread.id,
        title=thread.title,
        chapter_ids=chat.scope(project, thread),
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


def _apply(project: Project, thread: ChatThread, body: ThreadIn) -> None:
    if body.title is not None:
        thread.title = " ".join(body.title.split())
    if body.chapter_ids is not None:
        known = {c.id for c in project.chapters}
        thread.chapter_ids = [i for i in dict.fromkeys(body.chapter_ids) if i in known]


@router.get("/projects/{project_id}/chats")
def threads(project_id: str, session: SessionDep) -> list[ThreadOut]:
    project = _project(session, project_id)
    return [_thread_out(project, t) for t in chat.threads(session, project.id)]


@router.post("/projects/{project_id}/chats")
def create_thread(project_id: str, body: ThreadIn, session: SessionDep) -> ThreadOut:
    project = _project(session, project_id)
    thread = chat.new_thread(project)
    _apply(project, thread, body)
    session.add(thread)
    session.commit()
    return _thread_out(project, thread)


@router.patch("/projects/{project_id}/chats/{thread_id}")
def update_thread(
    project_id: str, thread_id: str, body: ThreadIn, session: SessionDep
) -> ThreadOut:
    project = _project(session, project_id)
    thread = _thread(session, project.id, thread_id)
    _apply(project, thread, body)
    session.commit()
    return _thread_out(project, thread)


@router.delete("/projects/{project_id}/chats/{thread_id}", status_code=204)
def delete_thread(project_id: str, thread_id: str, session: SessionDep) -> None:
    session.delete(_thread(session, project_id, thread_id))
    session.commit()


@router.get("/projects/{project_id}/chats/{thread_id}/messages")
def messages(project_id: str, thread_id: str, session: SessionDep) -> list[MessageOut]:
    thread = _thread(session, project_id, thread_id)
    return [_out(m) for m in chat.history(session, thread.id)]


def _model(session: SessionDep, project_id: str) -> TextModel:
    try:
        return TextModel(session, project_id, "chat")
    except ModelNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/projects/{project_id}/chats/{thread_id}/ask")
def ask(project_id: str, thread_id: str, body: Question, session: SessionDep) -> list[MessageOut]:
    project = _project(session, project_id)
    thread = _thread(session, project.id, thread_id)
    model = _model(session, project.id)
    try:
        asked, reply = chat.ask(
            session, project, model, body.question.strip(), body.chapter_id, thread
        )
    except BadModelOutput as exc:
        raise HTTPException(502, f"bad_model_output: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return [_out(asked), _out(reply)]


class StreamLine(BaseModel):
    """One line of `/stream`: a step the agent has started, the finished exchange,
    or an error that happened after the response had begun."""

    type: Literal["status", "done", "error"]
    code: str = ""  # status: index | search | read | think
    detail: str = ""
    messages: list[MessageOut] = Field(default_factory=list)


def _text_model(project_id: str, thread_id: str, session: SessionDep) -> TextModel:
    """Checked before the stream starts, so these failures still get a proper status code."""
    _project(session, project_id)
    _thread(session, project_id, thread_id)
    return _model(session, project_id)


TextModelDep = Annotated[TextModel, Depends(_text_model)]


@router.post("/projects/{project_id}/chats/{thread_id}/stream")
def ask_stream(
    project_id: str, thread_id: str, body: Question, session: SessionDep, model: TextModelDep
) -> Iterator[StreamLine]:
    """The same question as `/ask`, answered as JSON Lines: a `status` line for every
    step the agent takes, then one `done` line with both messages, or `error`."""
    project = _project(session, project_id)
    thread = _thread(session, project.id, thread_id)
    try:
        for event in chat.ask_events(
            session, project, model, body.question.strip(), body.chapter_id, thread
        ):
            if isinstance(event, chat.Reply):
                yield StreamLine(type="done", messages=[_out(event.asked), _out(event.reply)])
            else:
                yield StreamLine(type="status", code=event.code, detail=event.detail)
    except BadModelOutput as exc:
        yield StreamLine(type="error", detail=f"bad_model_output: {exc}")
    except Exception as exc:  # noqa: BLE001 - the response has started: report in it
        yield StreamLine(type="error", detail=f"provider_error: {str(exc)[:300]}")


@router.post("/projects/{project_id}/chats/{thread_id}/suggest")
def suggest(
    project_id: str, thread_id: str, body: Question, session: SessionDep
) -> list[MessageOut]:
    """Writer projects only: ideas for what happens next. `question` is the label the
    user sees in the conversation."""
    project = _project(session, project_id)
    if project.mode != MODE_WRITER:
        raise HTTPException(409, "reader_mode_readonly")
    thread = _thread(session, project.id, thread_id)
    model = _model(session, project.id)
    try:
        asked, reply = chat.suggest(
            session, project, model, body.question.strip(), body.chapter_id, thread
        )
    except BadModelOutput as exc:
        raise HTTPException(502, f"bad_model_output: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"provider_error: {str(exc)[:300]}") from exc
    return [_out(asked), _out(reply)]
