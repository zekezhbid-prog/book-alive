import os
import tempfile

import pytest

# A throwaway data directory (and embedded PostgreSQL cluster) for the test run.
# Must be set before `app.config` is imported.
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = _tmp.name
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
os.environ["EMBEDDING_MODEL"] = "hash"  # no model download in tests

from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def make_book(chapters: int = 3, paragraphs: int = 4) -> bytes:
    lines = []
    for n in range(1, chapters + 1):
        lines.append(f"Глава {n}")
        for p in range(paragraphs):
            lines.append(f"Абзац {p} главы {n}. " + "Текст идёт дальше и дальше. " * 8)
    return "\n\n".join(lines).encode("utf-8")
