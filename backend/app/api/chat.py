import logging
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionDep
from app.llm.calls import ModelNotConfigured, TextModel
from app.models import MODE_WRITER, ChatMessage, ChatThread, Project
from app.rag import chat, jobs

router = APIRouter(prefix="/api", tags=["chat"])
log = logging.getLogger(__name__)
# What the reader sees when the agent fails: the details go to the server log only.
CHAT_FAILED = "chat_failed"
CHAT_BUSY = "chat_busy"  # the thread is still answering the previous question


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


class StatusOut(BaseModel):
    code: str
    detail: str


class ThreadOut(BaseModel):
    id: str
    title: str
    # Chapters the conversation searches and reads; empty means the whole book.
    chapter_ids: list[str]
    created_at: datetime
    updated_at: datetime
    # A question still being answered (see `rag.jobs`), and the agent's current step.
    pending_question: str = ""
    status: StatusOut | None = None


class ThreadIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    chapter_ids: list[str] | None = None


def _thread_out(project: Project, thread: ChatThread) -> ThreadOut:
    job = jobs.running(thread.id)
    status = job.status if job else None
    return ThreadOut(
        id=thread.id,
        title=thread.title,
        chapter_ids=chat.scope(project, thread),
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        pending_question=job.question if job else "",
        status=StatusOut(code=status.code, detail=status.detail) if status else None,
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


@router.get("/projects/{project_id}/chats/{thread_id}")
def get_thread(project_id: str, thread_id: str, session: SessionDep) -> ThreadOut:
    project = _project(session, project_id)
    return _thread_out(project, _thread(session, project.id, thread_id))


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
    except Exception as exc:
        log.exception("chat failed: project %s, thread %s", project_id, thread_id)
        raise HTTPException(502, CHAT_FAILED) from exc
    return [_out(asked), _out(reply)]


class StreamLine(BaseModel):
    """One line of `/stream`: a step the agent has started, the finished exchange,
    or an error that happened after the response had begun."""

    type: Literal["status", "done", "error"]
    code: str = ""  # status: index | search | read | think
    detail: str = ""
    messages: list[MessageOut] = Field(default_factory=list)
    # done: names asked about that have no card yet (see `chat.cardless_names`).
    missing_cards: list[str] = Field(default_factory=list)


ModelFactory = Callable[[Session], TextModel]


def _model_factory(project_id: str, thread_id: str, session: SessionDep) -> ModelFactory:
    """Checked before the stream starts, so these failures still get a proper status code.
    The answer runs with a session of its own, so the model is made there."""
    _project(session, project_id)
    _thread(session, project_id, thread_id)
    _model(session, project_id)
    return lambda own: TextModel(own, project_id, "chat")


ModelFactoryDep = Annotated[ModelFactory, Depends(_model_factory)]


@router.post("/projects/{project_id}/chats/{thread_id}/stream")
def ask_stream(
    project_id: str, thread_id: str, body: Question, make_model: ModelFactoryDep
) -> Iterator[StreamLine]:
    """The same question as `/ask`, answered as JSON Lines: a `status` line for every
    step the agent takes, then one `done` line with both messages, or `error`. The
    answer is worked out apart from this request (see `rag.jobs`): if the reader leaves,
    it is still finished and saved."""
    question = body.question.strip()

    def work(own: Session) -> Iterator[chat.Status | chat.Reply]:
        project = own.get(Project, project_id)
        thread = own.get(ChatThread, thread_id)
        yield from chat.ask_events(own, project, make_model(own), question, body.chapter_id, thread)

    try:
        job = jobs.start(thread_id, question, work)
    except jobs.Busy:
        yield StreamLine(type="error", detail=CHAT_BUSY)
        return
    while (event := job.events.get()) is not jobs.END:
        if isinstance(event, chat.Reply):
            yield StreamLine(
                type="done",
                messages=[_out(event.asked), _out(event.reply)],
                missing_cards=event.missing_cards,
            )
        elif isinstance(event, chat.Status):
            yield StreamLine(type="status", code=event.code, detail=event.detail)
        else:  # the job has logged it
            yield StreamLine(type="error", detail=CHAT_FAILED)


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
    except Exception as exc:
        log.exception("plot suggestions failed: project %s, thread %s", project_id, thread_id)
        raise HTTPException(502, CHAT_FAILED) from exc
    return [_out(asked), _out(reply)]
