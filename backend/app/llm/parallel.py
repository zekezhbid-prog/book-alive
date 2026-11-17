"""Model calls side by side.

A run spends its time waiting for the model to write its answers; the server itself hardly
works meanwhile. So the independent calls of a run go out together, a few at a time. The
limit is shared by the whole app (`LLM_PARALLEL`), so two runs at once still send no more
than that many requests together and stay within the provider's rate limits and the
database pool. Only the model calls run in the other threads: whatever touches the
database stays in the caller's thread.
"""

import threading
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import settings

LIMIT = max(1, settings.llm_parallel)
# Taken by every model call (see TextModel.invoke), from any thread or run.
slots = threading.BoundedSemaphore(LIMIT)


def each[T, R](items: Iterable[T], work: Callable[[T], R]) -> Iterator[tuple[T, R]]:
    """(item, work(item)) as the answers come, not in the order given. An error in `work`
    is raised here, in the caller's thread; the calls not started yet are then dropped,
    as they are when the caller stops reading (a cancelled run)."""
    items = list(items)
    if not items:
        return
    with ThreadPoolExecutor(min(LIMIT, len(items)), thread_name_prefix="model") as pool:
        futures = {pool.submit(work, item): item for item in items}
        try:
            for future in as_completed(futures):
                yield futures[future], future.result()
        finally:
            for future in futures:
                future.cancel()
