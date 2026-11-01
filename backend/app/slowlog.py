"""Middleware: names the request on the database connections it takes and writes the
slow ones to the log with the state of the pool, so a hang can be traced to its cause."""

import logging
import time

from fastapi import Request

from app.db import current_holder, pool_state

SLOW_REQUEST_SECONDS = 2.0
_log = logging.getLogger(__name__)


async def log_slow_requests(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    name = f"{request.method} {request.url.path}"
    token = current_holder.set(name)
    started = time.monotonic()
    try:
        return await call_next(request)
    finally:
        took = time.monotonic() - started
        current_holder.reset(token)
        if took >= SLOW_REQUEST_SECONDS:
            _log.warning("slow request %s: %.1f s, %s", name, took, pool_state())
