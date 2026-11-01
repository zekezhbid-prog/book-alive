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


# ---------- what holds the pool: visible in the logs ----------


def test_a_long_held_connection_is_logged_with_its_holder(monkeypatch, caplog):
    from app import db

    monkeypatch.setattr(db, "HOLD_WARN_SECONDS", 0)
    token = db.current_holder.set("GET /api/test-holder")
    try:
        with caplog.at_level("WARNING", logger="app.db"), get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        db.current_holder.reset(token)
    held = [r.getMessage() for r in caplog.records if "held" in r.getMessage()]
    assert held, "a connection held past the limit was not reported"
    assert "GET /api/test-holder" in held[-1]


def test_a_short_hold_is_not_logged(caplog):
    with caplog.at_level("WARNING", logger="app.db"), get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    assert not [r for r in caplog.records if "held" in r.getMessage()]


def test_a_slow_request_is_logged_with_the_pool_state(client, monkeypatch, caplog):
    from app import slowlog

    monkeypatch.setattr(slowlog, "SLOW_REQUEST_SECONDS", 0)
    with caplog.at_level("WARNING", logger="app.slowlog"):
        assert client.get("/api/projects").status_code == 200
    slow = [r.getMessage() for r in caplog.records if r.name == "app.slowlog"]
    assert slow and "GET /api/projects" in slow[-1]
    assert "pool" in slow[-1]


def test_requests_name_the_connection_holder(client, monkeypatch, caplog):
    from app import db

    monkeypatch.setattr(db, "HOLD_WARN_SECONDS", 0)
    with caplog.at_level("WARNING", logger="app.db"):
        assert client.get("/api/projects").status_code == 200
    held = [r.getMessage() for r in caplog.records if "held" in r.getMessage()]
    assert any("GET /api/projects" in m for m in held)


def _loop_in_thread():
    import threading

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop, thread


def test_watchdog_measures_a_free_loop():
    from app import slowlog

    loop, thread = _loop_in_thread()
    try:
        lag, busy = slowlog.sample(loop, timeout=5)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
    assert lag is not None and lag < 1
    assert busy is not None and busy >= 0


def test_watchdog_reports_a_blocked_loop(caplog):
    import time as _time

    from app import slowlog

    loop, thread = _loop_in_thread()
    loop.call_soon_threadsafe(_time.sleep, 1.5)  # the loop is stuck in sync code
    try:
        with caplog.at_level("WARNING", logger="app.slowlog"):
            slowlog.check(loop, timeout=0.5)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
    messages = [r.getMessage() for r in caplog.records if r.name == "app.slowlog"]
    assert any("event loop" in m for m in messages)
