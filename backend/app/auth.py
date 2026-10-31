"""Accounts for a hosted instance: e-mail and password, registration only for listed
addresses, reset of a forgotten password by mail, and a guard that keeps every user inside
their own books. With `ALLOWED_EMAILS` empty, as on the owner's own machine, nothing here
is active and the app opens without a login.
"""

import base64
import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import mail
from app.config import settings
from app.crypto import signing_key
from app.db import SessionDep, get_engine
from app.models import AnalysisRun, Chapter, Entity, Image, PasswordReset, Project, Scene, User

COOKIE = "lorebook_session"
SESSION_SECONDS = 30 * 24 * 3600
RESET_SECONDS = 3600
RESET_COOLDOWN = 60  # one reset mail per address per minute
PASSWORD_MIN = 8
PASSWORD_MAX = 200
# Wrong passwords are counted per address and client: after MAX_FAILURES in WINDOW_SECONDS
# that pair is refused until the window passes.
MAX_FAILURES = 8
WINDOW_SECONDS = 300
_failures: dict[str, deque[float]] = defaultdict(deque)
_last_reset_mail: dict[str, float] = {}
OPEN_PATHS = {
    "/api/session",
    "/api/login",
    "/api/logout",
    "/api/register",
    "/api/password/forgot",
    "/api/password/reset",
}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(prefix="/api", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str


class Forgot(BaseModel):
    email: str


class Reset(BaseModel):
    token: str
    password: str


class Change(BaseModel):
    current_password: str
    new_password: str


class SessionInfo(BaseModel):
    accounts: bool  # false: no login at all (the owner's own machine)
    authenticated: bool
    email: str = ""
    is_admin: bool = False


def accounts_enabled() -> bool:
    return bool(settings.allowed_email_list)


# ---------- passwords and sessions ----------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=2**14, r=8, p=1, dklen=32
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_HASH = hash_password("not a real password")


def _sign(user: User, expires: int) -> str:
    # The end of the password hash is part of the message: a new password ends every session.
    message = f"{user.id}:{expires}:{user.password_hash[-16:]}".encode()
    return hmac.new(signing_key(), message, hashlib.sha256).hexdigest()


def _token(user: User) -> str:
    expires = int(time.time()) + SESSION_SECONDS
    return f"{user.id}.{expires}.{_sign(user, expires)}"


def _set_cookie(request: Request, response: Response, user: User) -> None:
    behind_https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        COOKIE,
        _token(user),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=behind_https,
    )


def _user_from_cookie(request: Request, db: Session) -> User | None:
    user_id, _, rest = request.cookies.get(COOKIE, "").partition(".")
    expires, _, signature = rest.partition(".")
    if not user_id or not expires.isdigit() or int(expires) < time.time():
        return None
    user = db.get(User, user_id)
    if user is None or not hmac.compare_digest(signature, _sign(user, int(expires))):
        return None
    return user


def is_admin(user: User) -> bool:
    return user.email in settings.owner_email_list


def _info(user: User | None) -> SessionInfo:
    if not accounts_enabled():
        return SessionInfo(accounts=False, authenticated=True, is_admin=True)
    if user is None:
        return SessionInfo(accounts=True, authenticated=False)
    return SessionInfo(accounts=True, authenticated=True, email=user.email, is_admin=is_admin(user))


def _throttle_key(request: Request, email: str) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    client = forwarded or (request.client.host if request.client else "")
    return f"{email}|{client}"


def _check_throttle(key: str) -> None:
    now = time.monotonic()
    attempts = _failures.get(key)
    if not attempts:
        return
    while attempts and now - attempts[0] > WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= MAX_FAILURES:
        raise HTTPException(429, "too_many_attempts")


def _email(raw: str) -> str:
    email = raw.strip().lower()
    if not EMAIL.match(email) or len(email) > 320:
        raise HTTPException(422, "bad_email")
    return email


def _password(raw: str) -> str:
    if not PASSWORD_MIN <= len(raw) <= PASSWORD_MAX:
        raise HTTPException(422, "weak_password")
    return raw


# ---------- the guard in front of every API call ----------

_OWNED = {"chapters": Chapter, "entities": Entity, "images": Image, "scenes": Scene}
_PATH = re.compile(r"^/api/(projects|chapters|entities|images|scenes|analysis)/([^/]+)")


def _owner_denied(db: Session, user: User, path: str) -> bool:
    """True when the path names something that belongs to another user's book."""
    match = _PATH.match(path)
    if match is None:
        return False
    kind, key = match.groups()
    if kind == "projects":
        project = db.get(Project, key)
    else:
        row = db.get(AnalysisRun if kind == "analysis" else _OWNED[kind], key)
        project = db.get(Project, row.project_id) if row is not None else None
    if project is None:
        return False  # the route answers "not found" itself
    if project.owner_id is None:
        return not is_admin(user)
    return project.owner_id != user.id


async def require_login(request: Request, call_next):
    """Middleware: every API call except the login ones needs a session, settings of the
    model connections are for administrators, and a book is open to its owner only."""
    path = request.url.path
    request.state.user_id = None
    request.state.is_admin = True  # without accounts there is one person
    if not path.startswith("/api/") or not accounts_enabled() or path in OPEN_PATHS:
        return await call_next(request)
    with Session(get_engine()) as db:
        user = _user_from_cookie(request, db)
        if user is None:
            return JSONResponse({"detail": "login_required"}, status_code=401)
        admin_only = path.startswith("/api/connections")
        if admin_only and request.method not in ("GET", "HEAD") and not is_admin(user):
            return JSONResponse({"detail": "admin_only"}, status_code=403)
        if _owner_denied(db, user, path):
            return JSONResponse({"detail": "project_not_found"}, status_code=404)
        request.state.user_id = user.id
        request.state.is_admin = is_admin(user)
    return await call_next(request)


# ---------- routes ----------


@router.get("/session")
def session_info(request: Request, session: SessionDep) -> SessionInfo:
    return _info(_user_from_cookie(request, session) if accounts_enabled() else None)


@router.post("/register")
def register(
    body: Credentials, request: Request, response: Response, session: SessionDep
) -> SessionInfo:
    email = _email(body.email)
    password = _password(body.password)
    if email not in settings.allowed_email_list:
        raise HTTPException(403, "registration_unavailable")
    if session.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(409, "already_registered")
    user = User(email=email, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    owners = settings.owner_email_list
    if owners and email == owners[0]:
        # The books made before accounts existed belong to the owner.
        session.execute(update(Project).where(Project.owner_id.is_(None)).values(owner_id=user.id))
    session.commit()
    _set_cookie(request, response, user)
    return _info(user)


@router.post("/login")
def login(
    body: Credentials, request: Request, response: Response, session: SessionDep
) -> SessionInfo:
    if not accounts_enabled():
        return _info(None)
    email = body.email.strip().lower()
    key = _throttle_key(request, email)
    _check_throttle(key)
    user = session.scalar(select(User).where(User.email == email))
    # Same work whether or not the address exists, so timing does not tell.
    valid = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not valid:
        _failures[key].append(time.monotonic())
        raise HTTPException(401, "wrong_credentials")
    _failures.pop(key, None)
    _set_cookie(request, response, user)
    return _info(user)


@router.post("/logout")
def logout(response: Response) -> SessionInfo:
    response.delete_cookie(COOKIE)
    return SessionInfo(accounts=accounts_enabled(), authenticated=not accounts_enabled())


def _site_url(request: Request) -> str:
    if settings.public_url:
        return settings.public_url.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return f"{scheme}://{host}"


@router.post("/password/forgot")
def forgot_password(
    body: Forgot, request: Request, tasks: BackgroundTasks, session: SessionDep
) -> dict[str, bool]:
    """Always answers the same, so it cannot be used to find out who has an account."""
    if not accounts_enabled():
        raise HTTPException(404, "accounts_disabled")
    email = body.email.strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    now = time.monotonic()
    if user is not None and now - _last_reset_mail.get(email, -RESET_COOLDOWN) >= RESET_COOLDOWN:
        _last_reset_mail[email] = now
        token = secrets.token_urlsafe(32)
        session.add(
            PasswordReset(
                user_id=user.id,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(seconds=RESET_SECONDS),
            )
        )
        session.commit()
        link = f"{_site_url(request)}/reset?token={token}"
        tasks.add_task(
            mail.send,
            user.email,
            "Lorebook: password reset",
            f"Open this link to choose a new password (valid for 1 hour):\n\n{link}\n\n"
            "If you did not ask for it, ignore this message.",
        )
    return {"ok": True}


@router.post("/password/reset")
def reset_password(
    body: Reset, request: Request, response: Response, session: SessionDep
) -> SessionInfo:
    password = _password(body.password)
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    reset = session.scalar(select(PasswordReset).where(PasswordReset.token_hash == token_hash))
    if reset is None or reset.expires_at < datetime.now(UTC):
        raise HTTPException(400, "reset_link_invalid")
    user = session.get(User, reset.user_id)
    user.password_hash = hash_password(password)
    for other in session.scalars(select(PasswordReset).where(PasswordReset.user_id == user.id)):
        session.delete(other)
    session.commit()
    _set_cookie(request, response, user)
    return _info(user)


@router.post("/password/change")
def change_password(
    body: Change, request: Request, response: Response, session: SessionDep
) -> SessionInfo:
    if not accounts_enabled():
        raise HTTPException(404, "accounts_disabled")
    user = session.get(User, request.state.user_id) if request.state.user_id else None
    if user is None:
        raise HTTPException(401, "login_required")
    if not verify_password(body.current_password, user.password_hash):
        # Not 401: that would make the page think the session ended.
        raise HTTPException(400, "wrong_password")
    user.password_hash = hash_password(_password(body.new_password))
    session.commit()
    _set_cookie(request, response, user)  # the old session ended with the old password
    return _info(user)
