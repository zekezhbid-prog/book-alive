import logging
import threading
import time
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import datetime
from typing import Annotated, ClassVar

from fastapi import Depends
from sqlalchemy import DateTime, create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BACKEND_DIR, settings


class Base(DeclarativeBase):
    type_annotation_map: ClassVar = {datetime: DateTime(timezone=True)}


_log = logging.getLogger(__name__)
_engine: Engine | None = None
_embedded_server = None  # keeps the embedded PostgreSQL alive for the process lifetime


def _database_url() -> str:
    if settings.database_url:
        return settings.database_url
    global _embedded_server
    try:
        import pgserver
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_URL is not set and the embedded PostgreSQL is not installed. "
            "Set DATABASE_URL or install with `uv sync --extra embedded`."
        ) from exc
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _embedded_server = pgserver.get_server(settings.data_dir / "pg")
    return _embedded_server.get_uri()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = _database_url().replace("postgresql://", "postgresql+psycopg://", 1)
        options: dict = {}
        if settings.db_schema:
            # Tables are created in, and looked up in, the first schema of the path. `extensions`
            # is where Supabase keeps pgvector; `public` stays last for plain servers.
            options["connect_args"] = {
                "options": f"-csearch_path={settings.db_schema},extensions,public"
            }
            options["pool_size"] = settings.db_pool_size
            options["max_overflow"] = 0
            # A busy pool answers with an error quickly instead of keeping a request waiting.
            options["pool_timeout"] = settings.db_pool_timeout
        _engine = create_engine(url, pool_pre_ping=True, **options)
        event.listen(_engine, "checkout", _on_checkout)
        event.listen(_engine, "checkin", _on_checkin)
    return _engine


# ---------- who holds the pool: written to the log ----------
#
# With a handful of pooled connections one long holder makes every other request wait
# for a free one (up to `db_pool_timeout`). A connection kept longer than this is
# reported with whoever took it: the request ("GET /api/...") or the background thread.

HOLD_WARN_SECONDS = 3.0
current_holder: ContextVar[str | None] = ContextVar("lorebook_db_holder", default=None)
_TAKEN = "lorebook_taken"


def _on_checkout(_dbapi_connection, record, _proxy) -> None:
    holder = current_holder.get() or f"thread {threading.current_thread().name}"
    record.info[_TAKEN] = (time.monotonic(), holder)


def _on_checkin(_dbapi_connection, record) -> None:
    taken = record.info.pop(_TAKEN, None) if record is not None else None
    if taken is None:
        return
    started, holder = taken
    held = time.monotonic() - started
    if held >= HOLD_WARN_SECONDS:
        _log.warning("db connection held %.1f s by %s", held, holder)


def pool_state() -> str:
    """One line for the log: how many pooled connections are taken right now."""
    pool = get_engine().pool
    try:
        return f"pool {pool.checkedout()}/{pool.size()} taken"
    except AttributeError:  # a pool without a fixed size
        return "pool " + pool.status()


# ---------- giving the connection back while waiting for someone else ----------
#
# A session keeps its connection from the first query until commit or rollback. A request
# that then waits half a minute for a model would keep one of a handful of pooled
# connections all that time. `release_connection` ends a transaction that has only read,
# so nothing is held while the model answers; objects already loaded stay usable (sessions
# here do not expire on commit) and anything loaded later simply takes a connection again.
# A transaction that has written is left alone: committing it early would change what the
# caller meant to be atomic.

_WROTE = "lorebook_wrote"


@event.listens_for(Session, "after_flush")
def _remember_flush(session: Session, _flush_context) -> None:
    session.info[_WROTE] = True


@event.listens_for(Session, "do_orm_execute")
def _remember_statement(state) -> None:
    if not state.is_select:
        state.session.info[_WROTE] = True


@event.listens_for(Session, "after_transaction_end")
def _forget_writes(session: Session, transaction) -> None:
    if transaction.parent is None:
        session.info.pop(_WROTE, None)


def release_connection(session: Session) -> None:
    """Return the session's connection to the pool if its transaction has only read."""
    if not session.in_transaction():
        return
    if session.new or session.dirty or session.deleted or session.info.get(_WROTE):
        # Not an error, but the connection stays taken for the whole wait: worth seeing
        # in the logs, since writing only after the model has answered avoids it.
        _log.warning("a connection is held while waiting: the transaction has written")
        return
    session.commit()


BASELINE = "0001"  # the schema as it was when migrations were introduced


def init_db() -> None:
    """Bring the database to the current schema with Alembic."""
    from alembic import command
    from alembic.config import Config

    engine = get_engine()
    with engine.begin() as conn:
        # A limited role on a shared server cannot create extensions; it is enough that
        # the administrator has already installed it.
        if not conn.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")):
            conn.execute(text("CREATE EXTENSION vector"))
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    tables = set(inspect(engine).get_table_names())
    if "projects" in tables and "alembic_version" not in tables:
        # A database made by `create_all` before migrations existed already has
        # the baseline schema: record that instead of creating the tables again.
        command.stamp(config, BASELINE)
    command.upgrade(config, "head")


def get_session() -> Iterator[Session]:
    with sessionmaker(get_engine(), expire_on_commit=False)() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
