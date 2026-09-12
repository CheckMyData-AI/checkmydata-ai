"""Unified task queue abstraction: ARQ (Redis) when available, asyncio fallback.

Callers interact only with ``enqueue()`` and never import ARQ directly.
When ``REDIS_URL`` is not set, tasks run in-process via ``asyncio.create_task``.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_arq_pool: Any | None = None
_fallback_tasks: dict[str, asyncio.Task] = {}

#: The URL a successful or failed connect was made against, so a later `enqueue` can
#: retry without being told it again (OPS-15).
_arq_url: str | None = None
_next_pool_attempt: float = 0.0
_pool_lock: asyncio.Lock | None = None

#: How long a failed connect suppresses the next attempt. A retry with no backoff
#: turns one Redis outage into a connect storm on every enqueue; 30 s is short enough
#: that a dyno recovers within a request or two of Redis coming back.
POOL_RETRY_BACKOFF_SECONDS = 30.0


def _reset_pool_backoff() -> None:
    """Forget the last attempt's timestamp. For tests and for an explicit re-init."""
    global _next_pool_attempt  # noqa: PLW0603
    _next_pool_attempt = 0.0


async def _ensure_pool(
    redis_url: str | None = None,
    *,
    create: Callable[[Any], Coroutine[Any, Any, Any]] | None = None,
) -> Any | None:
    """Return the ARQ pool, connecting or re-connecting if it is time to try (OPS-15).

    `init_task_queue` used to catch the connect exception, log one WARNING, leave
    `_arq_pool` at `None` and let nothing retry — so `is_arq_active()` returned False
    for the process's whole life. On `web` that means `repos.py` takes the deliberate
    in-process branch and the full repo index, measured above 1 GiB, runs inside the
    dyno serving user requests: exactly what `allow_in_process=False` exists to
    forbid, and that guard covers only enqueue-time failure with a LIVE pool. In the
    worker the same boot failure silently restores the state where the orphan sweep
    and the reaper's requeue return `None`.

    Backed off rather than retried per call: a dead Redis must not become a connect
    attempt on every enqueue.
    """
    global _arq_pool, _arq_url, _next_pool_attempt, _pool_lock  # noqa: PLW0603

    if _arq_pool is not None:
        return _arq_pool
    url = redis_url or _arq_url
    if not url:
        # Fallback mode is a configuration, not a fault. Nothing to retry.
        return None
    _arq_url = url

    now = time.monotonic()
    if now < _next_pool_attempt:
        return None
    _next_pool_attempt = now + POOL_RETRY_BACKOFF_SECONDS

    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    async with _pool_lock:
        if _arq_pool is not None:
            return _arq_pool
        try:
            factory = create or importlib.import_module("arq.connections").create_pool
            from app.core.redis_tls import arq_redis_settings

            _arq_pool = await factory(arq_redis_settings(url))
            _next_pool_attempt = 0.0
            logger.info("Task queue: ARQ connected to Redis")
        except Exception:
            logger.warning(
                "Task queue: could not connect to Redis; this process will run tasks "
                "in-process until the next attempt in %.0fs. Heavy jobs "
                "(allow_in_process=False) are refused rather than run here.",
                POOL_RETRY_BACKOFF_SECONDS,
                exc_info=True,
            )
            _arq_pool = None
    return _arq_pool


async def init_task_queue(redis_url: str | None = None) -> None:
    """Initialise the task queue backend.  Call once during app startup."""
    if not redis_url:
        logger.info("Task queue: using in-process asyncio fallback (no REDIS_URL)")
        return
    _reset_pool_backoff()
    await _ensure_pool(redis_url)


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
    allow_in_process: bool = True,
    _queue_name: str | None = None,
    _job_timeout: int | None = None,
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
    allow_in_process:
        Whether running here is an acceptable substitute for the worker when Redis is
        configured but the enqueue fails (F-SCHED-04). ``True`` for light work, where a
        Redis blip should not lose the job. ``False`` for the heavy pipelines: the repo
        index peaks near 1 GB, and running that inside the dyno serving user requests is
        not a degraded version of running it in the worker — it is an outage with extra
        steps. Ignored when no Redis is configured at all, because then in-process is the
        intended mode and refusing would leave the feature simply broken.
    **kwargs:
        Keyword arguments forwarded to the task function.

    Returns
    -------
    The ARQ job id or the asyncio task name, or ``None`` on failure.
    """
    # OPS-15: a boot-time connect failure is not a permanent verdict. This retries at
    # most once per `POOL_RETRY_BACKOFF_SECONDS`, and returns the live pool otherwise.
    pool = await _ensure_pool()
    if pool is not None:
        try:
            # NOTE: arq's ``enqueue_job`` forwards unknown kwargs to the task
            # coroutine — there is no per-job timeout parameter at enqueue
            # time (verified against arq 0.28). ``_job_timeout`` is therefore
            # intentionally NOT forwarded; per-function timeouts are set on
            # the WorkerSettings registration (see ``app.worker``).
            arq_kwargs: dict[str, Any] = {
                "_job_id": task_id,
                "_queue_name": _queue_name or "arq:queue",
            }
            if _job_timeout is not None:
                logger.debug(
                    "Task %s: _job_timeout=%s is enforced via WorkerSettings "
                    "function registration, not at enqueue time",
                    task_name,
                    _job_timeout,
                )
            job = await pool.enqueue_job(
                task_name,
                **kwargs,
                **arq_kwargs,
            )
            jid = getattr(job, "job_id", None)
            logger.info("Task enqueued via ARQ: %s (job=%s)", task_name, jid)
            return jid
        except Exception:
            # F-SCHED-04. Two situations were collapsed into one warning. With no Redis
            # configured, in-process IS the mode. With Redis configured, an enqueue that
            # throws means something is wrong with Redis — and a warning is where that
            # goes to die: nothing hides it, and nothing alerts on it either.
            if not allow_in_process:
                logger.error(
                    "ARQ enqueue failed for %s and in-process execution is not an "
                    "acceptable substitute for it (it would run inside the web dyno). "
                    "The task was NOT started; the caller should surface a retryable "
                    "failure.",
                    task_name,
                    exc_info=True,
                )
                return None
            logger.error(
                "ARQ enqueue failed for %s; falling back to in-process execution in "
                "this dyno. Redis is configured, so this is a fault worth chasing, not "
                "the dev-mode path.",
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
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                logger.error(
                    "Background task %s failed: %s",
                    key,
                    exc,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

    task.add_done_callback(_cleanup)
    logger.info("Task started in-process: %s", key)
    return key


def is_task_running(task_id: str) -> bool:
    """Check whether a fallback task is still running (ARQ has its own status API)."""
    t = _fallback_tasks.get(task_id)
    return t is not None and not t.done()


def is_arq_active() -> bool:
    """Return ``True`` when tasks are dispatched to the ARQ/Redis worker.

    Callers use this to decide whether an in-process asyncio task handle will
    exist locally (fallback mode) or whether the work runs out-of-process in
    the worker (ARQ mode). In ARQ mode the persisted DB status — not an
    in-memory task handle — is the authoritative signal of progress.

    Reads the pool rather than reconnecting: this is called from synchronous code and
    from hot paths. The reconnection happens in `enqueue`, which is where a stale
    `False` actually costs something (OPS-15).
    """
    return _arq_pool is not None


class EnqueueFailedError(RuntimeError):
    """The task was not started, and the caller must say so rather than answer "queued".

    `enqueue` returns ``None`` on failure rather than raising — deliberately, because some
    callers legitimately continue without the job. Five HTTP handlers, two cron dispatchers
    and a scan did not: each had already minted a run row set to `running`, and each
    answered `202 {"status": "queued"}` over an enqueue that never happened (API-03,
    OPS-05). The run row then blocks the single-active-run guard until the reaper times it
    out, and the user waits for something nobody is doing.
    """


async def enqueue_or_fail(task_name: str, **kwargs) -> str:
    """`enqueue`, but a failure is an exception rather than a ``None`` nobody reads.

    Returns the job id. Raises :class:`EnqueueFailedError` when the task was not started,
    so a caller that forgets to check gets a 500 instead of a false 202 — the failure mode
    that at least tells the truth.
    """
    job_id = await enqueue(task_name, **kwargs)
    if not job_id:
        raise EnqueueFailedError(
            f"{task_name} was not enqueued: the queue refused it and in-process execution "
            "is not an acceptable substitute here"
        )
    return job_id
