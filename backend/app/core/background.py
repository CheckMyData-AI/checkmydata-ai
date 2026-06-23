"""Helper for fire-and-forget background coroutines.

`asyncio.create_task` returns a task that is only weakly referenced by the
event loop, so an unreferenced task can be garbage-collected mid-flight and
its exception silently discarded. `spawn_tracked` keeps a strong reference
until completion and logs any exception instead of dropping it.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task] = set()


def spawn_tracked(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task:
    """Schedule ``coro`` as a tracked background task.

    The task is held in a module-level set (strong reference) until it
    finishes, then removed; any non-cancellation exception it raises is logged.
    """
    task = asyncio.create_task(coro, name=name)
    _BACKGROUND_TASKS.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _BACKGROUND_TASKS.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("Background task %s failed: %r", t.get_name(), exc, exc_info=exc)

    task.add_done_callback(_on_done)
    return task
