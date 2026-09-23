"""One hourly wave for every cron loop in `app.main` (PRJ-07: S-13 and the copy-paste).

The daily knowledge sync and the analytics collection each kept their own loop that slept
to `now.replace(minute=0) + timedelta(hours=1)`. On a zone-aware datetime Python does that
arithmetic on the WALL clock, so across spring-forward the loop slept to a 02:00 that does
not exist and the schedules of that hour never ran, and across fall-back the repeated hour
was mistaken for the next one (audit 2026-09-13 S-13).

`next_boundary` measures one real hour from the local top of the hour, and returns every
local hour the boundary completes — two on spring-forward night, so a schedule at 02:00
runs with 03:00 instead of vanishing. The repeated hour on fall-back night keeps its label
and the dispatcher's hour-scoped Redis lock refuses it, as it always did.

`run_hourly_wave` is the loop both call sites share. A dispatcher is handed the INTENDED
instant (`at=`), never left to re-read the clock — the 2026-09-08 fix, kept here once.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def next_boundary(now: datetime) -> tuple[datetime, list[int]]:
    """``(the next local top of the hour, the local hours it completes)``.

    *now* must be zone-aware. The boundary is one real hour after the current local top
    of the hour, so it is never a nonexistent or doubled wall-clock time.
    """
    tz = now.tzinfo
    top = now.replace(minute=0, second=0, microsecond=0)
    boundary = (top.astimezone(UTC) + timedelta(hours=1)).astimezone(tz)
    step = (boundary.hour - top.hour) % 24
    if step <= 1:
        return boundary, [boundary.hour]
    return boundary, [(top.hour + i) % 24 for i in range(1, step + 1)]


def seconds_between(earlier: datetime, later: datetime) -> float:
    """Real seconds from *earlier* to *later*, whatever wall clock they are written in."""
    return (later.astimezone(UTC) - earlier.astimezone(UTC)).total_seconds()


async def run_hourly_wave(
    name: str,
    timezone: str,
    dispatch: Callable[[datetime], Awaitable[None]],
    *,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> None:
    """Call ``dispatch(at)`` once per local hour, for ever, in *timezone*.

    ``at`` is the boundary instant with its hour set to each completed local hour — so on
    spring-forward night the skipped hour is dispatched too. A failed iteration logs and
    waits a minute; cancellation ends the loop.
    """
    # Looked up per call, not bound at definition: a test that patches `asyncio.sleep`
    # must reach this loop, or it waits a real hour.
    def _sleep(seconds: float) -> Awaitable[None]:
        return (sleep or asyncio.sleep)(seconds)

    while True:
        try:
            now = datetime.now(ZoneInfo(timezone))
            boundary, hours = next_boundary(now)
            # In UTC: subtracting two datetimes that share a `tzinfo` is ALSO wall-clock
            # arithmetic in Python (fold and offset are ignored), the same trap as above.
            wait_seconds = max(1.0, seconds_between(now, boundary))
            logger.info(
                "Cron: next %s wave in %.0f seconds (at %s)",
                name,
                wait_seconds,
                boundary.isoformat(),
            )
            await _sleep(wait_seconds)
            for hour in hours:
                at = boundary if hour == boundary.hour else boundary.replace(hour=hour)
                if hour != boundary.hour:
                    logger.info(
                        "Cron: %s dispatching hour %02d, skipped by the clock change", name, hour
                    )
                await dispatch(at)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Cron: %s loop iteration failed; will retry next cycle", name)
            await _sleep(60)
