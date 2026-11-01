"""Middleware: names the request on the database connections it takes and writes the
slow ones to the log with the state of the pool, so a hang can be traced to its cause."""

import asyncio
import logging
import threading
import time

import anyio.to_thread
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


# ---------- watchdog: is the whole process stuck, and on what ----------
#
# A slow request is logged only when it ends. When the site stops answering altogether
# (even /api/health, which needs no database) the cause is the process itself: the event
# loop stuck in sync code, every worker thread taken, or memory running out. A thread
# outside the loop looks every few seconds and writes down which of these it is.

WATCH_SECONDS = 5.0
LAG_WARN_SECONDS = 1.0
BUSY_WARN_SHARE = 0.75  # of the worker threads that run sync endpoints


def sample(loop: asyncio.AbstractEventLoop, timeout: float) -> tuple[float | None, int | None]:
    """How long the loop took to run a callback, and how many worker threads were taken
    at that moment. (None, None) if it did not get to it within `timeout`."""
    asked = time.monotonic()
    answered = threading.Event()
    result: list = [None, None]

    def probe() -> None:
        result[0] = time.monotonic() - asked
        try:
            result[1] = anyio.to_thread.current_default_thread_limiter().borrowed_tokens
        except Exception:  # noqa: BLE001 - outside anyio there is nothing to count
            result[1] = 0
        answered.set()

    loop.call_soon_threadsafe(probe)
    if not answered.wait(timeout):
        return None, None
    return result[0], result[1]


def _threads_total(loop: asyncio.AbstractEventLoop) -> int:
    try:
        return int(anyio.to_thread.current_default_thread_limiter().total_tokens)
    except Exception:  # noqa: BLE001
        return 40


def memory_mb() -> int | None:
    """Resident memory of the process (Linux), for the log line."""
    try:
        with open("/proc/self/status", encoding="ascii") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def check(loop: asyncio.AbstractEventLoop, timeout: float = 30.0, total: int = 40) -> None:
    lag, busy = sample(loop, timeout)
    if lag is None:
        _log.warning(
            "event loop did not answer for %.0f s; %s, memory %s MB",
            timeout,
            pool_state(),
            memory_mb(),
        )
        return
    if lag >= LAG_WARN_SECONDS or (busy or 0) >= total * BUSY_WARN_SHARE:
        _log.warning(
            "event loop lag %.1f s, worker threads %s/%s taken; %s, memory %s MB",
            lag,
            busy,
            total,
            pool_state(),
            memory_mb(),
        )


def start_watchdog(loop: asyncio.AbstractEventLoop) -> None:
    total = 40

    def grab_total() -> None:
        nonlocal total
        total = _threads_total(loop)

    loop.call_soon_threadsafe(grab_total)

    def watch() -> None:
        while not loop.is_closed():
            time.sleep(WATCH_SECONDS)
            try:
                check(loop, total=total)
            except Exception:  # noqa: BLE001 - the watchdog must never take the app down
                _log.exception("watchdog failed")

    threading.Thread(target=watch, daemon=True, name="watchdog").start()
