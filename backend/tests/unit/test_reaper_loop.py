"""Unit tests for the reaper loop + one-shot sweep wiring layer.

These tests cover the loop/gating behaviour only — SQL correctness is already
covered by test_stale_run_reaper.py (Task 6).  We avoid the in-memory SQLite
cross-session trap by monkeypatching async_session_factory instead of
inserting real rows.
"""

from __future__ import annotations

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
