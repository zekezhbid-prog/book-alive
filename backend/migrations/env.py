"""Alembic environment: the database and the models come from the application."""

from alembic import context

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.db import Base, get_engine

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline mode is not supported: run against the database.")
run_migrations_online()
