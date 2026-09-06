"""Heartbeat context manager for long-running background jobs.

Spawns a background task that calls *writer* every ``interval_seconds`` for the
duration of the ``async with`` block. The writer updates ``heartbeat_at`` on the
run's status row so the stale-run reaper can tell a live run from a crashed one.
Writer errors are logged and swallowed — a heartbeat failure must never crash
the run it is monitoring. They are logged at WARNING with a consecutive-failure
count: at DEBUG they were invisible in production, which is how 163 runs came to
die with `stale run reaped` and no record of what stopped their beat.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

HeartbeatWriter = Callable[[], Awaitable[None]]


async def _beat(writer: HeartbeatWriter, interval_seconds: float) -> None:
    """Beat until cancelled, and say so when the beat cannot land.

    The failure stays swallowed — a heartbeat must never crash the run it
    protects — but it stopped being silent on 2026-09-05. Production held 163
    failed indexing runs and **every one** carried the same error, `stale run
    reaped`: the reaper's own account of what it did, with nothing about why the
    beat stopped. This log line is the missing half, and `logger.debug` was why
    it was missing: production runs at INFO.

    The streak matters more than the individual failure. One missed beat is
    noise; `stale_running_heartbeat_timeout_seconds / interval_seconds` of them
    in a row is a run's cause of death, and the count is what makes the two
    distinguishable in a log afterwards.
    """
    consecutive = 0
    while True:
        try:
            await writer()
            consecutive = 0
        except Exception as exc:
            consecutive += 1
            logger.warning(
                "heartbeat writer failed (%d consecutive): %s — the run will be reaped "
                "if this continues past the stale-run timeout",
                consecutive,
                exc,
                exc_info=consecutive == 1,
            )
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def heartbeat(
    writer: HeartbeatWriter,
    *,
    interval_seconds: float,
) -> AsyncIterator[None]:
    # float, not int: the body already does float math (`max(0.001, …)`), and a
    # caller that wants a sub-second beat — a test standing in for a 300 s timeout —
    # had its interval rounded to zero by the annotation's implied contract.
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
