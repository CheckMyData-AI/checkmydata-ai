"""Heartbeat context manager for long-running background jobs.

Spawns a background task that calls *writer* every ``interval_seconds`` for the
duration of the ``async with`` block. The writer updates ``heartbeat_at`` on the
run's status row so the stale-run reaper can tell a live run from a crashed one.
Writer errors are logged and swallowed — a heartbeat failure must never crash
the run it is monitoring.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

HeartbeatWriter = Callable[[], Awaitable[None]]


async def _beat(writer: HeartbeatWriter, interval_seconds: float) -> None:
    while True:
        try:
            await writer()
        except Exception:
            logger.debug("heartbeat writer failed", exc_info=True)
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def heartbeat(
    writer: HeartbeatWriter,
    *,
    interval_seconds: int,
) -> AsyncIterator[None]:
    # Immediate first beat so a just-started row gets heartbeat_at before the
    # first interval elapses.
    try:
        await writer()
    except Exception:
        logger.debug("initial heartbeat writer failed", exc_info=True)

    task = asyncio.create_task(_beat(writer, max(0.001, interval_seconds)))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
