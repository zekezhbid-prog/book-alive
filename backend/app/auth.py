"""One shared password for a hosted instance.

There are no user accounts: the app is single-user. The password only keeps strangers
from spending the owner's tokens. With `APP_PASSWORD` empty, as on the owner's own
machine, nothing here is active.
"""

import hashlib
import hmac
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.crypto import signing_key

COOKIE = "book_alive_session"
SESSION_SECONDS = 30 * 24 * 3600
OPEN_PATHS = {"/api/session", "/api/login", "/api/logout"}

router = APIRouter(prefix="/api", tags=["auth"])


class Login(BaseModel):
    password: str


class SessionInfo(BaseModel):
    password_required: bool
    authenticated: bool


def _sign(expires: int) -> str:
    # The password is part of the signed message: changing it ends every session.
    message = f"{expires}:{settings.app_password}".encode()
    return hmac.new(signing_key(), message, hashlib.sha256).hexdigest()


def _token() -> str:
    expires = int(time.time()) + SESSION_SECONDS
    return f"{expires}.{_sign(expires)}"


def is_authenticated(request: Request) -> bool:
    if not settings.app_password:
        return True
    expires, _, signature = request.cookies.get(COOKIE, "").partition(".")
    if not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(signature, _sign(int(expires)))


async def require_login(request: Request, call_next):
    """Middleware: every API call except the login endpoints needs the session cookie."""
    path = request.url.path
    if path.startswith("/api/") and path not in OPEN_PATHS and not is_authenticated(request):
        return JSONResponse({"detail": "login_required"}, status_code=401)
    return await call_next(request)


@router.get("/session")
def session_info(request: Request) -> SessionInfo:
    return SessionInfo(
        password_required=bool(settings.app_password), authenticated=is_authenticated(request)
    )


@router.post("/login")
def login(body: Login, request: Request, response: Response) -> SessionInfo:
    if not settings.app_password:
        return SessionInfo(password_required=False, authenticated=True)
    if not hmac.compare_digest(body.password.encode(), settings.app_password.encode()):
        time.sleep(1)  # a shared password has no lockout: at least make guessing slow
        raise HTTPException(401, "wrong_password")
    behind_https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        COOKIE,
        _token(),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=behind_https,
    )
    return SessionInfo(password_required=True, authenticated=True)


@router.post("/logout")
def logout(response: Response) -> SessionInfo:
    response.delete_cookie(COOKIE)
    return SessionInfo(password_required=bool(settings.app_password), authenticated=False)
