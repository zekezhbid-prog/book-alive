import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import auth, mail
from app.config import settings
from app.db import get_engine
from app.main import app

OWNER = "owner@x.test"
GUEST = "guest@x.test"
PASSWORD = "correct horse"


@pytest.fixture
def accounts(monkeypatch):
    monkeypatch.setattr(settings, "allowed_emails", f"{OWNER}, {GUEST.upper()}")
    monkeypatch.setattr(settings, "owner_emails", OWNER)
    monkeypatch.setattr(settings, "public_url", "https://lore.test")
    auth._failures.clear()
    auth._last_reset_mail.clear()
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(mail, "send", lambda to, subject, body: sent.append((to, subject, body)))
    yield sent
    with Session(get_engine()) as db:
        db.execute(text("DELETE FROM projects WHERE title LIKE 'auth-test%'"))
        db.execute(text("DELETE FROM users"))
        db.commit()


@pytest.fixture
def owner(client, accounts):
    client.cookies.clear()
    registered = client.post("/api/register", json={"email": OWNER, "password": PASSWORD})
    assert registered.status_code == 200
    yield client
    client.cookies.clear()


@pytest.fixture
def guest(accounts):
    with TestClient(app) as other:
        yield other


def make_project(who, title="auth-test book"):
    response = who.post("/api/projects", data={"mode": "writer", "title": title})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_no_allowed_emails_means_no_login(client):
    assert client.get("/api/session").json() == {
        "accounts": False,
        "authenticated": True,
        "email": "",
        "is_admin": True,
    }
    assert client.get("/api/projects").status_code == 200


def test_api_is_closed_until_login(client, accounts):
    client.cookies.clear()
    assert client.get("/api/session").json()["authenticated"] is False
    blocked = client.get("/api/projects")
    assert (blocked.status_code, blocked.json()["detail"]) == (401, "login_required")
    assert client.put("/api/settings", json={}).status_code == 401
    assert client.get("/api/openapi.json").status_code == 401
    assert client.get("/api/docs").status_code == 401


def test_only_listed_addresses_register(client, accounts):
    client.cookies.clear()
    stranger = client.post("/api/register", json={"email": "who@x.test", "password": PASSWORD})
    assert (stranger.status_code, stranger.json()["detail"]) == (403, "registration_unavailable")
    bad = client.post("/api/register", json={"email": "bad", "password": PASSWORD})
    assert bad.status_code == 422
    short = client.post("/api/register", json={"email": GUEST, "password": "short"})
    assert (short.status_code, short.json()["detail"]) == (422, "weak_password")
    # The list ignores case and spaces.
    ok = client.post("/api/register", json={"email": f" {GUEST.upper()} ", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["email"] == GUEST
    again = client.post("/api/register", json={"email": GUEST, "password": PASSWORD})
    assert (again.status_code, again.json()["detail"]) == (409, "already_registered")
    client.cookies.clear()


def test_login_and_logout(owner):
    owner.cookies.clear()
    wrong = owner.post("/api/login", json={"email": OWNER, "password": "nope nope"})
    assert (wrong.status_code, wrong.json()["detail"]) == (401, "wrong_credentials")
    unknown = owner.post("/api/login", json={"email": "no@x.test", "password": PASSWORD})
    assert unknown.json()["detail"] == "wrong_credentials"  # same answer: no address leak
    assert owner.get("/api/projects").status_code == 401

    ok = owner.post("/api/login", json={"email": OWNER, "password": PASSWORD})
    assert ok.json() == {"accounts": True, "authenticated": True, "email": OWNER, "is_admin": True}
    assert owner.get("/api/projects").status_code == 200
    owner.post("/api/logout")
    assert owner.get("/api/projects").status_code == 401


def test_forged_and_expired_cookies_are_rejected(client, accounts):
    client.cookies.clear()
    client.cookies.set("lorebook_session", "someone.9999999999.deadbeef")
    assert client.get("/api/projects").status_code == 401
    client.cookies.set("lorebook_session", "someone.1.whatever")
    assert client.get("/api/projects").status_code == 401
    client.cookies.clear()


def test_guessing_is_cut_off(client, accounts):
    client.cookies.clear()
    for _ in range(auth.MAX_FAILURES):
        client.post("/api/login", json={"email": OWNER, "password": "guess guess"})
    blocked = client.post("/api/login", json={"email": OWNER, "password": "guess guess"})
    assert (blocked.status_code, blocked.json()["detail"]) == (429, "too_many_attempts")


def test_change_password_needs_the_old_one_and_ends_other_sessions(owner):
    change = "/api/password/change"
    with TestClient(app) as phone:
        phone.post("/api/login", json={"email": OWNER, "password": PASSWORD})
        assert phone.get("/api/projects").status_code == 200

        wrong = owner.post(
            change, json={"current_password": "x" * 9, "new_password": "new password"}
        )
        assert (wrong.status_code, wrong.json()["detail"]) == (400, "wrong_password")
        short = owner.post(change, json={"current_password": PASSWORD, "new_password": "short"})
        assert short.status_code == 422
        good = {"current_password": PASSWORD, "new_password": "new password"}
        assert owner.post(change, json=good).status_code == 200
        assert owner.get("/api/projects").status_code == 200  # this session got a fresh cookie
        assert phone.get("/api/projects").status_code == 401  # the other one ended
        phone.cookies.clear()
        relogin = phone.post("/api/login", json={"email": OWNER, "password": "new password"})
        assert relogin.status_code == 200


def test_forgotten_password_is_reset_by_a_mailed_link(owner, accounts):
    owner.cookies.clear()
    sent = accounts
    unknown = owner.post("/api/password/forgot", json={"email": "no@x.test"})
    assert unknown.json() == {"ok": True} and sent == []  # same answer, nothing sent

    assert owner.post("/api/password/forgot", json={"email": OWNER}).json() == {"ok": True}
    assert len(sent) == 1 and sent[0][0] == OWNER
    link = next(word for word in sent[0][2].split() if word.startswith("https://lore.test/reset"))
    token = link.split("token=")[1]

    # A second request within the cooldown sends nothing more.
    owner.post("/api/password/forgot", json={"email": OWNER})
    assert len(sent) == 1

    bad = owner.post("/api/password/reset", json={"token": "wrong", "password": "brand new one"})
    assert (bad.status_code, bad.json()["detail"]) == (400, "reset_link_invalid")
    done = owner.post("/api/password/reset", json={"token": token, "password": "brand new one"})
    assert done.status_code == 200 and done.json()["authenticated"] is True
    reused = owner.post("/api/password/reset", json={"token": token, "password": "another one!"})
    assert reused.status_code == 400  # a link works once

    owner.cookies.clear()
    old = owner.post("/api/login", json={"email": OWNER, "password": PASSWORD})
    assert old.status_code == 401
    new = owner.post("/api/login", json={"email": OWNER, "password": "brand new one"})
    assert new.status_code == 200


def test_every_user_sees_only_their_own_books(owner, guest):
    registered = guest.post("/api/register", json={"email": GUEST, "password": PASSWORD})
    assert registered.status_code == 200
    mine = make_project(owner, "auth-test mine")
    theirs = make_project(guest, "auth-test theirs")

    def titles(who):
        return {p["title"] for p in who.get("/api/projects").json()}

    assert titles(owner) == {"auth-test mine"}
    assert titles(guest) == {"auth-test theirs"}

    chapter = owner.post(f"/api/projects/{mine}/chapters", json={"title": "One"}).json()["id"]
    paths = (f"/api/projects/{mine}", f"/api/projects/{mine}/chat", f"/api/chapters/{chapter}")
    for path in paths:
        denied = guest.get(path)
        assert (denied.status_code, denied.json()["detail"]) == (404, "project_not_found"), path
        assert owner.get(path).status_code == 200, path
    assert guest.delete(f"/api/projects/{mine}").status_code == 404
    assert owner.get(f"/api/projects/{theirs}").status_code == 404
    assert guest.get(f"/api/projects/{theirs}").status_code == 200


def test_books_from_before_accounts_go_to_the_owner(client, accounts):
    client.cookies.clear()
    with Session(get_engine()) as db:
        db.execute(
            text(
                "INSERT INTO projects (id, title, author, mode, source_filename, split_method, "
                "style_id, style_text, created_at) VALUES ('legacy1', 'auth-test legacy', '', "
                "'writer', '', 'manual', '', '', now())"
            )
        )
        db.commit()
    with TestClient(app) as other:
        other.post("/api/register", json={"email": GUEST, "password": PASSWORD})
        assert other.get("/api/projects").json() == []  # nobody's book is not theirs
        assert other.get("/api/projects/legacy1").status_code == 404
    client.post("/api/register", json={"email": OWNER, "password": PASSWORD})
    assert [p["title"] for p in client.get("/api/projects").json()] == ["auth-test legacy"]
    client.cookies.clear()


def test_connections_are_for_administrators_but_everyone_picks_their_own_models(owner, guest):
    guest.post("/api/register", json={"email": GUEST, "password": PASSWORD})
    assert guest.post("/api/connections", json={"name": "x"}).status_code == 403
    made = owner.post(
        "/api/connections",
        json={"name": "Hub", "base_url": "https://api.example/v1", "api_key": "secret-1234"},
    ).json()
    # A guest sees the connection by name only: no address, no key hint.
    seen = guest.get("/api/connections").json()
    assert [(c["name"], c["base_url"], c["api_key_hint"]) for c in seen] == [("Hub", "", "")]
    assert owner.get("/api/connections").json()[0]["base_url"] == "https://api.example/v1"

    mine = {"text_connection_id": made["id"], "text_model": "model-a", "video_model": "clip-1"}
    assert guest.put("/api/settings", json=mine).status_code == 200
    # Their choice is theirs: the administrator's own settings are untouched.
    assert guest.get("/api/settings").json()["text_model"] == "model-a"
    assert guest.get("/api/settings").json()["video_model"] == "clip-1"
    assert owner.get("/api/settings").json()["text_model"] == ""
    # Deleting the connection clears everyone's choice that used it.
    assert owner.delete(f"/api/connections/{made['id']}").status_code == 204
    cleared = guest.get("/api/settings").json()
    assert (cleared["text_connection_id"], cleared["text_model"]) == ("", "")
