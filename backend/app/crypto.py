"""Encryption of API keys at rest."""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


@lru_cache
def _fernet() -> Fernet:
    if settings.secret_key:
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
        return Fernet(key)
    key_file = settings.data_dir / "secret.key"
    if not key_file.exists():
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(Fernet.generate_key())
    return Fernet(key_file.read_bytes().strip())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


class KeyUnreadable(RuntimeError):
    """The stored value was encrypted with a different secret."""


def decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise KeyUnreadable("key_unreadable") from exc


def mask(value: str) -> str:
    """What the UI is allowed to see of a stored key."""
    if not value:
        return ""
    return "…" + value[-4:] if len(value) > 8 else "…"
