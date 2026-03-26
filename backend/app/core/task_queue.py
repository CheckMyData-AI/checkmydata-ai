"""Unified task queue abstraction: ARQ (Redis) when available, asyncio fallback.

Callers interact only with ``enqueue()`` and never import ARQ directly.
When ``REDIS_URL`` is not set, tasks run in-process via ``asyncio.create_task``.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_arq_pool: Any | None = None
_fallback_tasks: dict[str, asyncio.Task] = {}


async def init_task_queue(redis_url: str | None = None) -> None:
    """Initialise the task queue backend.  Call once during app startup."""
    global _arq_pool  # noqa: PLW0603

    if not redis_url:
        logger.info("Task queue: using in-process asyncio fallback (no REDIS_URL)")
        return

    try:
        arq_create_pool = importlib.import_module("arq.connections").create_pool
        RedisSettings = importlib.import_module("arq.connections").RedisSettings  # noqa: N806
        _arq_pool = await arq_create_pool(RedisSettings.from_dsn(redis_url))
        logger.info("Task queue: ARQ connected to Redis")
    except Exception:
        logger.warning(
            "Task queue: failed to connect to Redis, falling back to asyncio",
            exc_info=True,
        )
        _arq_pool = None


async def close_task_queue() -> None:
    """Shut down the task queue backend.  Call during app shutdown."""
    global _arq_pool  # noqa: PLW0603
    if _arq_pool is not None:
        try:
            await _arq_pool.close()
        except Exception:
            logger.debug("Error closing ARQ pool", exc_info=True)
        _arq_pool = None

    tasks = list(_fallback_tasks.values())
    for task in tasks:
        if not task.done():
            task.cancel()
    for task in tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    _fallback_tasks.clear()


async def enqueue(
    task_name: str,
    coro_factory: Callable[..., Coroutine] | None = None,
    *,
    task_id: str | None = None,
    _queue_name: str | None = None,
    **kwargs: Any,
) -> str | None:
    """Enqueue a background task.

    Parameters
    ----------
    task_name:
        Name registered in the ARQ worker (e.g. ``"run_db_index"``).
    coro_factory:
        Async callable used for the in-process fallback.  Ignored when ARQ
        is active (the worker discovers the function by *task_name*).
    task_id:
        Optional dedup key.  In fallback mode, prevents duplicate tasks.
    **kwargs:
        Keyword arguments forwarded to the task function.

    Returns
    -------
    The ARQ job id or the asyncio task name, or ``None`` on failure.
    """
    if _arq_pool is not None:
        try:
            job = await _arq_pool.enqueue_job(
                task_name,
                **kwargs,
                _job_id=task_id,
                _queue_name=_queue_name or "arq:queue",
            )
            jid = getattr(job, "job_id", None)
            logger.info("Task enqueued via ARQ: %s (job=%s)", task_name, jid)
            return jid
        except Exception:
            logger.warning(
                "ARQ enqueue failed for %s, falling to asyncio",
                task_name,
                exc_info=True,
            )

    if coro_factory is None:
        logger.error("No coro_factory for in-process fallback of task %s", task_name)
        return None

    key = task_id or task_name
    existing = _fallback_tasks.get(key)
    if existing and not existing.done():
        logger.debug("Task %s already running in-process", key)
        return key

    task = asyncio.create_task(coro_factory(**kwargs), name=key)
    _fallback_tasks[key] = task

    def _cleanup(t: asyncio.Task) -> None:
        _fallback_tasks.pop(key, None)
        if not t.cancelled() and t.exception():
            logger.error(
                "Background task %s failed: %s",
                key,
                t.exception(),
                exc_info=t.exception(),
            )

    task.add_done_callback(_cleanup)
    logger.info("Task started in-process: %s", key)
    return key


def is_task_running(task_id: str) -> bool:
    """Check whether a fallback task is still running (ARQ has its own status API)."""
    t = _fallback_tasks.get(task_id)
    return t is not None and not t.done()
