"""A cron that sleeps for an hour must act for THAT hour, not for whatever the clock
says when it wakes.

Measured on production, 2026-09-07/08. The hourly wave logged this sequence of hours
over eight consecutive wall-clock hours:

    20, 21, 21, 23, 23, 1, 2, 3

Two hours were processed twice and two were never processed at all — and one of the
missing ones was **hour 0**, which is exactly when this deployment's nightly sync is
scheduled (`daily_knowledge_sync_hour` defaults to 0). The last completed `daily_sync`
was 2026-09-06 22:00 UTC; nothing since.

The cause is structural rather than a bad value. The loop computes the boundary it
intends to wake at, sleeps until then, and the dispatcher it calls **reads the clock
again**:

    next_hour = now.replace(minute=0, ...) + timedelta(hours=1)
    await asyncio.sleep(wait_seconds)
    await _dispatch_daily_knowledge_sync_wave()      # takes no argument

Two independent clock reads with nothing carrying the intent between them. Any drift —
an early wake, a slow start, a restart re-phasing the loop — makes the dispatcher act
for a different hour than the one it was woken for. And when it reads the *previous*
hour, that hour runs a second time while the intended one is skipped entirely: the
Redis lock is keyed on `{run_date}:{hour}`, so the repeat is a no-op and the miss is
silent.

The fix is to pass the intention. These tests hold that.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

import app.main as main


@pytest.fixture
def berlin():
    return ZoneInfo("Europe/Berlin")


class TestTheDispatcherCanBeToldWhichHour:
    def test_the_knowledge_wave_accepts_the_instant_it_was_woken_for(self) -> None:
        import inspect

        sig = inspect.signature(main._dispatch_daily_knowledge_sync_wave)
        assert "at" in sig.parameters, (
            "the dispatcher must accept the instant the loop intended, or it is guessing"
        )
        assert sig.parameters["at"].default is None, (
            "a standalone caller (a test, a manual trigger) must still work with no argument"
        )

    def test_the_analytics_wave_accepts_it_too(self) -> None:
        import inspect

        sig = inspect.signature(main._dispatch_analytics_collect_wave)
        assert "at" in sig.parameters
        assert sig.parameters["at"].default is None

    async def test_it_uses_the_given_instant_and_not_the_clock(self, berlin) -> None:
        """The whole point: an hour handed in wins over the one the clock reports."""
        intended = datetime(2026, 9, 8, 0, 0, 0, tzinfo=berlin)
        seen: dict[str, str] = {}

        class _Lock:
            async def __aenter__(self):
                return False  # not acquired: stop before any real work

            async def __aexit__(self, *a):
                return False

        def _capture(key, ttl_seconds=None):
            seen["key"] = key
            return _Lock()

        with patch.object(main, "redis_lock", _capture):
            await main._dispatch_daily_knowledge_sync_wave(at=intended)

        # The lock key carries `{run_date}:{hour}`, so it is the honest witness to which
        # hour the dispatcher believed it was acting for.
        assert seen["key"].endswith("2026-09-08:0"), seen["key"]

    async def test_the_analytics_wave_uses_it_too(self, berlin) -> None:
        intended = datetime(2026, 9, 8, 0, 0, 0, tzinfo=berlin)
        seen: dict[str, str] = {}

        class _Lock:
            async def __aenter__(self):
                return False

            async def __aexit__(self, *a):
                return False

        def _capture(key, ttl_seconds=None):
            seen["key"] = key
            return _Lock()

        with patch.object(main, "redis_lock", _capture):
            await main._dispatch_analytics_collect_wave(at=intended)

        assert seen["key"].endswith("2026-09-08:0"), seen["key"]


class TestTheLoopPassesWhatItSleptFor:
    async def test_the_knowledge_loop_hands_over_its_boundary(self, berlin) -> None:
        """A wake that lands a moment EARLY is the production failure, reproduced: the
        clock still reads the previous hour, and without the handover the dispatcher
        would act for it — running that hour twice and skipping this one forever."""
        boundary = datetime(2026, 9, 8, 0, 0, 0, tzinfo=berlin)
        just_before = boundary - timedelta(milliseconds=5)
        clock = iter([just_before, just_before])
        dispatched: list = []

        # BaseException, not Exception: the loop wraps its body in `except Exception`
        # and would swallow the signal that ends this test, then spin forever.
        class _Stop(BaseException):
            pass

        async def _fake_dispatch(at=None):
            dispatched.append(at)

        with (
            patch.object(main.settings, "daily_knowledge_sync_enabled", True),
            patch.object(main.settings, "daily_knowledge_sync_timezone", "Europe/Berlin"),
            patch.object(main, "_dispatch_daily_knowledge_sync_wave", _fake_dispatch),
            patch("app.main.datetime") as dt,
            patch("asyncio.sleep", AsyncMock(side_effect=[None, _Stop()])),
        ):
            dt.now.side_effect = lambda tz=None: next(clock)
            with pytest.raises(_Stop):
                await main._daily_knowledge_sync_cron_loop()

        assert dispatched, "the loop never dispatched"
        handed = dispatched[0]
        assert handed is not None, "the loop must hand over the hour it slept for"
        assert handed.hour == 0, (
            f"woken for hour 0, handed over hour {handed.hour} — this is the production "
            "defect: the intended hour is never processed and the previous one runs twice"
        )
