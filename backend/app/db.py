from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, ClassVar

from fastapi import Depends
from sqlalchemy import DateTime, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


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
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def init_db() -> None:
    from app import models  # noqa: F401  (registers tables)

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with sessionmaker(get_engine(), expire_on_commit=False)() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
