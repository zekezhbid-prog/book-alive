"""Chat answers are worked out in a thread of their own, not inside the request: the
reader may leave the page while the agent reads, and the answer must still be finished
and saved. While it runs, the question and the agent's current step can be looked up
by the chat thread, so a page opened again shows that an answer is on its way.

One process serves the app (see the Dockerfile), so a dictionary is enough. A restart
loses answers in progress; the question then is simply not in the history.
"""

import logging
import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db import get_engine
from app.rag.chat import Reply, Status

log = logging.getLogger(__name__)

# Put on the queue when the job is over, after its Reply or its exception.
END = None


@dataclass
class Job:
    question: str
    status: Status | None = None
    # Status, then Reply or an exception, then END: read by the request that started it.
    events: queue.Queue = field(default_factory=queue.Queue)


class Busy(RuntimeError):
    """The thread is still answering its previous question."""


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def running(thread_id: str) -> Job | None:
    return _jobs.get(thread_id)


def start(
    thread_id: str, question: str, work: Callable[[Session], Iterator[Status | Reply]]
) -> Job:
    """Starts `work` with a session of its own; its events go to the job's queue."""
    with _lock:
        if thread_id in _jobs:
            raise Busy(thread_id)
        job = _jobs[thread_id] = Job(question)
    threading.Thread(
        target=_run, args=(thread_id, job, work), daemon=True, name=f"chat-{thread_id}"
    ).start()
    return job


def _run(thread_id: str, job: Job, work: Callable[[Session], Iterator[Status | Reply]]) -> None:
    try:
        with Session(get_engine(), expire_on_commit=False) as session:
            for event in work(session):
                if isinstance(event, Status):
                    job.status = event
                job.events.put(event)
    except Exception as exc:
        log.exception("chat answer failed in thread %s", thread_id)
        job.events.put(exc)
    finally:
        # The reply is already saved: a page that sees the job gone finds it in the history.
        with _lock:
            _jobs.pop(thread_id, None)
        job.events.put(END)
