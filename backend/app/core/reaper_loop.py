"""Background reaper loop + one-shot sweep, runnable in web and worker processes."""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.models.base import async_session_factory
from app.services.stale_run_reaper import StaleRunReaper

logger = logging.getLogger(__name__)

_reaper = StaleRunReaper()


async def run_reaper_sweep() -> None:
    """One idempotent reaper pass. No-op when reaper disabled."""
    if not settings.reaper_enabled:
        return
    try:
        async with async_session_factory() as session:
            await _reaper.reap_once(
                session,
                timeout_seconds=settings.stale_running_heartbeat_timeout_seconds,
            )
            await session.commit()
    except Exception:
        logger.warning("Reaper sweep failed", exc_info=True)


async def reaper_loop() -> None:
    """Periodic reaper. Gated by settings.reaper_enabled."""
    if not settings.reaper_enabled:
        return
    interval = max(5, settings.reaper_interval_seconds)
    while True:
        try:
            await asyncio.sleep(interval)
            await run_reaper_sweep()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Reaper loop iteration failed; will retry")
