from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, ClassVar

from fastapi import Depends
from sqlalchemy import DateTime, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BACKEND_DIR, settings


class Base(DeclarativeBase):
    type_annotation_map: ClassVar = {datetime: DateTime(timezone=True)}


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
        _engine = create_engine(url, pool_pre_ping=True, **options)
    return _engine


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
