import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.crypto import decrypt
from app.db import get_engine
from app.llm.provision import HUBRIS_NAME, ensure_hubris
from app.models import AppSetting, Connection


@pytest.fixture
def session(client):
    with Session(get_engine(), expire_on_commit=False) as db:
        yield db
        db.rollback()
        db.execute(text("DELETE FROM connections WHERE name = :n"), {"n": HUBRIS_NAME})
        db.execute(text("DELETE FROM app_settings WHERE key = 'text_connection_id'"))
        db.commit()


def test_no_key_creates_nothing(session, monkeypatch):
    monkeypatch.setattr(settings, "hubris_api_key", "")
    ensure_hubris(session)
    assert session.scalar(select(Connection).where(Connection.name == HUBRIS_NAME)) is None


def test_key_creates_the_connection_once_and_keeps_it_current(session, monkeypatch):
    monkeypatch.setattr(settings, "hubris_api_key", "key-one")
    ensure_hubris(session)
    monkeypatch.setattr(settings, "hubris_api_key", "key-two")
    ensure_hubris(session)
    rows = session.scalars(select(Connection).where(Connection.name == HUBRIS_NAME)).all()
    assert len(rows) == 1
    assert decrypt(rows[0].api_key_encrypted) == "key-two"
    assert rows[0].base_url == "https://api.hubris.pw/v1"
    assert session.get(AppSetting, "text_connection_id").value == rows[0].id


def test_a_text_connection_chosen_by_hand_is_kept(session, monkeypatch):
    session.merge(AppSetting(key="text_connection_id", value="mine"))
    session.commit()
    monkeypatch.setattr(settings, "hubris_api_key", "key-one")
    ensure_hubris(session)
    assert session.get(AppSetting, "text_connection_id").value == "mine"


def test_subscription_connections_are_gone(client):
    response = client.post("/api/connections", json={"name": "Claude", "kind": "claude_cli"})
    assert response.status_code == 422
    assert client.get("/api/system").status_code in (404, 405)


def test_migration_removes_the_subscription_connection(session):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module("migrations.versions.0004_drop_subscription_connection")
    session.execute(
        text(
            "INSERT INTO connections (id, name, kind, base_url, api_key_encrypted, created_at) "
            "VALUES ('cli1', 'Claude', 'claude_cli', '', '', now()), "
            "('api1', 'Other', 'openai', 'https://x.test', '', now())"
        )
    )
    session.execute(
        text(
            "INSERT INTO app_settings (key, value) VALUES ('text_connection_id', 'cli1'), "
            "('text_model', 'sonnet'), ('image_connection_id', 'api1'), ('image_model', 'm')"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )
    )
    session.commit()
    connection = session.connection()
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    session.commit()
    ids = set(session.scalars(text("SELECT id FROM connections WHERE id IN ('cli1','api1')")))
    values = dict(session.execute(text("SELECT key, value FROM app_settings")).all())
    session.execute(text("DELETE FROM connections WHERE id = 'api1'"))
    session.execute(text("DELETE FROM app_settings WHERE key LIKE 'image_%'"))
    session.commit()
    assert ids == {"api1"}
    assert values["text_connection_id"] == "" and values["text_model"] == ""
    assert values["image_connection_id"] == "api1" and values["image_model"] == "m"
