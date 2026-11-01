"""The server must not freeze when the database pool is busy: the login middleware never
waits for a connection on the event loop, and no connection is held while a model or a
provider is answering."""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import auth
from app.db import get_engine, release_connection
from app.llm.calls import TextModel
from app.models import Project

from .test_auth import accounts, owner  # noqa: F401 - fixtures


def test_health_needs_no_database(client, monkeypatch, accounts):  # noqa: F811
    def no_database():
        raise RuntimeError("database is down")

    monkeypatch.setattr(auth, "get_engine", no_database)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_login_check_runs_off_the_event_loop(owner, monkeypatch):  # noqa: F811
    seen: list[bool] = []
    real = auth._user_from_cookie

    def spy(request, db):
        try:
            asyncio.get_running_loop()
            seen.append(True)
        except RuntimeError:
            seen.append(False)
        return real(request, db)

    monkeypatch.setattr(auth, "_user_from_cookie", spy)
    assert owner.get("/api/projects").status_code == 200
    assert seen == [False], "the middleware touched the database on the event loop"


def test_release_returns_a_read_only_connection():
    with Session(get_engine(), expire_on_commit=False) as session:
        session.scalars(select(Project)).all()
        assert session.in_transaction()
        release_connection(session)
        assert not session.in_transaction()


def test_release_keeps_a_transaction_that_wrote():
    with Session(get_engine()) as session:
        session.add(Project(title="pool-test", mode="reader"))
        release_connection(session)  # pending, not flushed yet
        assert session.new
        session.flush()
        release_connection(session)  # flushed, not committed
        assert session.in_transaction()
        session.rollback()


def test_release_keeps_a_transaction_after_raw_sql_write():
    with Session(get_engine()) as session:
        session.execute(text("DELETE FROM projects WHERE title = 'pool-test-none'"))
        release_connection(session)
        assert session.in_transaction()
        session.rollback()


def test_after_a_write_is_committed_the_next_read_can_be_released():
    with Session(get_engine()) as session:
        session.execute(text("DELETE FROM projects WHERE title = 'pool-test-none'"))
        session.commit()
        session.scalars(select(Project)).all()
        release_connection(session)
        assert not session.in_transaction()


class _Recorder:
    def __init__(self, session):
        self.session = session
        self.held: list[bool] = []

    def invoke(self, messages):
        self.held.append(self.session.in_transaction())
        return AIMessage("ok")


def test_text_model_does_not_hold_a_connection_while_the_model_answers():
    with Session(get_engine(), expire_on_commit=False) as session:
        session.scalars(select(Project)).all()
        model = object.__new__(TextModel)
        model.session = session
        model.engine = session.get_bind()
        model.project_id = None
        model.connection_name = "test"
        model.model_name = "test"
        model.llm = _Recorder(session)
        assert model.invoke("test", [HumanMessage("hi")]) == "ok"
        assert model.llm.held == [False]


def test_a_write_inside_a_savepoint_still_counts():
    with Session(get_engine()) as session:
        with session.begin_nested():
            session.add(Project(title="pool-test-savepoint", mode="reader"))
        release_connection(session)
        assert session.in_transaction()
        session.rollback()
