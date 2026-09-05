"""A heartbeat that cannot write is the one thing nothing reports (prod, 2026-09-05).

Production has 163 failed indexing runs and **every single one** carries the same
error: `stale run reaped`. Not one other cause. That uniformity is the finding —
a reaper killing runs is a symptom, and the thing that would name the cause is
the heartbeat writer, which fails like this:

    async def _beat(writer, interval_seconds):
        while True:
            try:
                await writer()
            except Exception:
                logger.debug("heartbeat writer failed", exc_info=True)
            await asyncio.sleep(interval_seconds)

`logger.debug`. Production runs at INFO, so a writer that fails every 30 seconds
for five minutes — long enough for the reaper to declare the run dead — leaves
**no trace at all**. The run then dies with "stale run reaped", which describes
what the reaper did and says nothing about why the beat stopped.

The writer opens its own session per beat (deliberately — a session driven from
two tasks is a race), so it needs a connection every 30 seconds. The app is
configured for `pool_size=5 + max_overflow=10` per process across two process
types, against a Supavisor session-mode limit of 15: 30 against 15. Whether that
is what starved the beat on any given day is exactly what nobody can tell,
because the failure was never logged.

Swallowing stays — a heartbeat failure must not crash the run it protects, and
that is stated in the module's own docstring. What changes is that it stops being
silent, and that consecutive failures are counted, because one missed beat is
noise and ten in a row is the run's cause of death.
"""

from __future__ import annotations

import asyncio
import logging
import re

from app.core.heartbeat import heartbeat


class TestAFailingWriterIsReported:
    async def test_the_first_failure_is_logged_at_warning(self, caplog):
        """DEBUG is invisible in production, which is where this matters."""

        async def _boom() -> None:
            raise RuntimeError("max clients reached in session mode")

        with caplog.at_level(logging.WARNING, logger="app.core.heartbeat"):
            async with heartbeat(_boom, interval_seconds=0.01):
                await asyncio.sleep(0.05)

        assert any(r.levelno >= logging.WARNING for r in caplog.records), (
            "a beat that cannot write leaves the run to be reaped; if that is not "
            "logged, the post-mortem shows only 'stale run reaped'"
        )

    async def test_the_reason_reaches_the_message(self, caplog):
        """`stale run reaped` names what the reaper did. The operator needs what
        stopped the beat."""

        async def _boom() -> None:
            raise RuntimeError("max clients reached in session mode")

        with caplog.at_level(logging.WARNING, logger="app.core.heartbeat"):
            async with heartbeat(_boom, interval_seconds=0.01):
                await asyncio.sleep(0.05)

        assert any("session mode" in r.getMessage() for r in caplog.records)

    async def test_consecutive_failures_are_counted(self, caplog):
        """One missed beat is noise; a run dies after ten. The count is what
        separates them, and it is what makes the log searchable afterwards."""

        async def _boom() -> None:
            raise RuntimeError("nope")

        with caplog.at_level(logging.WARNING, logger="app.core.heartbeat"):
            async with heartbeat(_boom, interval_seconds=0.01):
                await asyncio.sleep(0.08)

        assert any("consecutive" in r.getMessage().lower() for r in caplog.records)


class TestTheRunIsStillProtected:
    async def test_a_failing_writer_never_escapes(self):
        """The module's own contract: a heartbeat failure must not crash the run
        it monitors. Making the failure loud must not make it fatal."""
        ran = False

        async def _boom() -> None:
            raise RuntimeError("nope")

        async with heartbeat(_boom, interval_seconds=0.01):
            await asyncio.sleep(0.03)
            ran = True

        assert ran

    async def test_a_recovering_writer_resets_the_count(self, caplog):
        """A pool that frees up should not leave the log claiming a growing
        streak — the streak is the signal, so it has to be true."""
        calls = {"n": 0}

        async def _flaky() -> None:
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("nope")

        with caplog.at_level(logging.WARNING, logger="app.core.heartbeat"):
            async with heartbeat(_flaky, interval_seconds=0.01):
                await asyncio.sleep(0.08)

        # The count is parenthesised in the message — `"(1".isdigit()` is False,
        # which is what the first draft of this test tripped over.
        streaks = [
            int(m.group(1))
            for r in caplog.records
            for m in [re.search(r"\((\d+) consecutive\)", r.getMessage())]
            if m
        ]
        assert streaks and max(streaks) <= 2, (
            f"the streak must reset once a beat lands again; saw {streaks}"
        )
