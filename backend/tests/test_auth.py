import pytest

from app.config import settings


@pytest.fixture
def password(monkeypatch):
    monkeypatch.setattr(settings, "app_password", "open sesame")


def test_no_password_means_no_login(client):
    assert client.get("/api/session").json() == {"password_required": False, "authenticated": True}
    assert client.get("/api/projects").status_code == 200


def test_api_is_closed_until_the_password_is_given(client, password):
    client.cookies.clear()
    assert client.get("/api/session").json() == {"password_required": True, "authenticated": False}
    blocked = client.get("/api/projects")
    assert (blocked.status_code, blocked.json()["detail"]) == (401, "login_required")
    assert client.put("/api/settings", json={}).status_code == 401

    wrong = client.post("/api/login", json={"password": "guess"})
    assert (wrong.status_code, wrong.json()["detail"]) == (401, "wrong_password")
    assert client.get("/api/projects").status_code == 401

    assert client.post("/api/login", json={"password": "open sesame"}).status_code == 200
    assert client.get("/api/projects").status_code == 200
    assert client.get("/api/session").json()["authenticated"] is True

    client.post("/api/logout")
    assert client.get("/api/projects").status_code == 401


def test_changing_the_password_ends_old_sessions(client, password, monkeypatch):
    client.cookies.clear()
    client.post("/api/login", json={"password": "open sesame"})
    assert client.get("/api/projects").status_code == 200
    monkeypatch.setattr(settings, "app_password", "new one")
    assert client.get("/api/projects").status_code == 401
    client.cookies.clear()


def test_forged_and_expired_cookies_are_rejected(client, password):
    client.cookies.clear()
    client.cookies.set("book_alive_session", "9999999999.deadbeef")
    assert client.get("/api/projects").status_code == 401
    client.cookies.set("book_alive_session", "1.whatever")
    assert client.get("/api/projects").status_code == 401
    client.cookies.clear()
