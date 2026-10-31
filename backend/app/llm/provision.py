"""The model connection that comes from the environment rather than from the interface."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.crypto import encrypt
from app.models import KIND_OPENAI, AppSetting, Connection

HUBRIS_NAME = "Hubris"


def ensure_hubris(session: Session) -> None:
    """Create or refresh the Hubris connection from HUBRIS_API_KEY. With no key set nothing
    happens, so a connection typed in by hand is never overwritten. If no text connection
    is chosen yet it becomes the one, so only the model is left to choose."""
    key = settings.hubris_api_key.strip()
    if not key:
        return
    connection = session.scalar(select(Connection).where(Connection.name == HUBRIS_NAME))
    if connection is None:
        connection = Connection(name=HUBRIS_NAME, kind=KIND_OPENAI)
        session.add(connection)
    connection.base_url = settings.hubris_base_url.strip()
    connection.api_key_encrypted = encrypt(key)
    session.flush()
    chosen = session.get(AppSetting, "text_connection_id")
    if chosen is None or not chosen.value:
        session.merge(AppSetting(key="text_connection_id", value=connection.id))
    session.commit()
