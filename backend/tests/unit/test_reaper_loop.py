"""Unit tests for the reaper loop + one-shot sweep wiring layer.

These tests cover the loop/gating behaviour only — SQL correctness is already
covered by test_stale_run_reaper.py (Task 6).  We avoid the in-memory SQLite
cross-session trap by monkeypatching async_session_factory instead of
inserting real rows.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# 1. No-op when reaper_enabled = False
# ---------------------------------------------------------------------------


async def test_run_reaper_sweep_no_op_when_disabled(monkeypatch):
    """run_reaper_sweep must return immediately without touching the DB."""
    monkeypatch.setattr("app.core.reaper_loop.settings.reaper_enabled", False)

    spy = AsyncMock()
    monkeypatch.setattr("app.core.reaper_loop._reaper.reap_once", spy)

    from app.core.reaper_loop import run_reaper_sweep

    await run_reaper_sweep()

    spy.assert_not_awaited()


# ---------------------------------------------------------------------------
# 2. Calls reap_once with correct timeout and commits when enabled
# ---------------------------------------------------------------------------


async def test_run_reaper_sweep_calls_reap_once_and_commits(monkeypatch):
    """When enabled, sweep must call reap_once(timeout_seconds=…) and commit."""
    monkeypatch.setattr("app.core.reaper_loop.settings.reaper_enabled", True)
    monkeypatch.setattr(
        "app.core.reaper_loop.settings.stale_running_heartbeat_timeout_seconds", 999
    )

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_ctx)
    monkeypatch.setattr("app.core.reaper_loop.async_session_factory", mock_factory)

    reap_spy = AsyncMock(return_value={"db_index": 0, "sync": 0, "repo": 0})
    monkeypatch.setattr("app.core.reaper_loop._reaper.reap_once", reap_spy)

    from app.core.reaper_loop import run_reaper_sweep

    await run_reaper_sweep()

    reap_spy.assert_awaited_once_with(mock_session, timeout_seconds=999)
    mock_session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. Exceptions from reap_once are swallowed (must not propagate)
# ---------------------------------------------------------------------------


async def test_run_reaper_sweep_swallows_exceptions(monkeypatch):
    """A crashing reap_once must not escape run_reaper_sweep."""
    monkeypatch.setattr("app.core.reaper_loop.settings.reaper_enabled", True)

    mock_session = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_ctx)
    monkeypatch.setattr("app.core.reaper_loop.async_session_factory", mock_factory)

    boom = AsyncMock(side_effect=RuntimeError("db exploded"))
    monkeypatch.setattr("app.core.reaper_loop._reaper.reap_once", boom)

    from app.core.reaper_loop import run_reaper_sweep

    # Must not raise
    await run_reaper_sweep()


# ---------------------------------------------------------------------------
# 4. reaper_loop returns immediately when disabled (never enters the loop)
# ---------------------------------------------------------------------------


async def test_reaper_loop_returns_immediately_when_disabled(monkeypatch):
    """With reaper_enabled=False, reaper_loop must return before sweeping."""
    monkeypatch.setattr("app.core.reaper_loop.settings.reaper_enabled", False)

    sweep_spy = AsyncMock()
    monkeypatch.setattr("app.core.reaper_loop.run_reaper_sweep", sweep_spy)

    from app.core.reaper_loop import reaper_loop

    # Completes without blocking on the periodic sleep.
    await asyncio.wait_for(reaper_loop(), timeout=1)
    sweep_spy.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5. reaper_loop exits cleanly on CancelledError (no exception propagates)
# ---------------------------------------------------------------------------


async def test_reaper_loop_exits_cleanly_on_cancel(monkeypatch):
    """Cancelling the loop while it sleeps must end the task without raising."""
    monkeypatch.setattr("app.core.reaper_loop.settings.reaper_enabled", True)
    monkeypatch.setattr("app.core.reaper_loop.settings.reaper_interval_seconds", 5)

    sweep_spy = AsyncMock()
    monkeypatch.setattr("app.core.reaper_loop.run_reaper_sweep", sweep_spy)

    from app.core.reaper_loop import reaper_loop

    task = asyncio.create_task(reaper_loop())
    await asyncio.sleep(0.01)  # let it reach the interval sleep
    task.cancel()
    await task  # CancelledError is caught inside the loop → no raise

    assert task.done()
    assert not task.cancelled()
    assert task.exception() is None
