"""C6 — vision §5 #4: insights live with TTL+confirmation semantics.

These tests confirm that ``_periodic_insight_maintenance`` calls both
``expire_old_insights`` and ``decay_stale_insights`` on every cron tick,
and that failures in either pass do not abort the other."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_periodic_runs_both_passes():
    """Both expire_old_insights AND decay_stale_insights must fire."""
    from app.main import _periodic_insight_maintenance

    mock_mem = MagicMock()
    mock_mem.expire_old_insights = AsyncMock(return_value=3)
    mock_mem.decay_stale_insights = AsyncMock(return_value=7)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    with (
        patch("app.core.insight_memory.InsightMemoryService", return_value=mock_mem),
        patch("app.main.async_session_factory") as mock_sf,
    ):
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        await _periodic_insight_maintenance()

    mock_mem.expire_old_insights.assert_awaited_once_with(mock_session)
    mock_mem.decay_stale_insights.assert_awaited_once_with(mock_session)
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_periodic_swallows_exceptions():
    """Failures in maintenance must NOT abort the surrounding cron loop."""
    from app.main import _periodic_insight_maintenance

    mock_mem = MagicMock()
    mock_mem.expire_old_insights = AsyncMock(side_effect=RuntimeError("DB down"))
    mock_mem.decay_stale_insights = AsyncMock(return_value=0)

    mock_session = AsyncMock()

    with (
        patch("app.core.insight_memory.InsightMemoryService", return_value=mock_mem),
        patch("app.main.async_session_factory") as mock_sf,
    ):
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        # Must NOT raise — surrounding cron loop must keep running
        await _periodic_insight_maintenance()


@pytest.mark.asyncio
async def test_periodic_logs_when_work_done(caplog):
    """When the maintenance affected rows, log an INFO line so an operator
    can see the loop is alive (silent loops are a known anti-pattern)."""
    import logging

    from app.main import _periodic_insight_maintenance

    mock_mem = MagicMock()
    mock_mem.expire_old_insights = AsyncMock(return_value=2)
    mock_mem.decay_stale_insights = AsyncMock(return_value=5)

    mock_session = AsyncMock()

    with (
        patch("app.core.insight_memory.InsightMemoryService", return_value=mock_mem),
        patch("app.main.async_session_factory") as mock_sf,
        caplog.at_level(logging.INFO, logger="app.main"),
    ):
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        await _periodic_insight_maintenance()

    assert any("insight maintenance" in r.message for r in caplog.records)
    assert any("expired=2" in r.message for r in caplog.records)
    assert any("decayed=5" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_periodic_silent_when_nothing_to_do():
    """No-op case: don't spam logs with "0 affected" — only log when work
    was actually done."""
    from app.main import _periodic_insight_maintenance

    mock_mem = MagicMock()
    mock_mem.expire_old_insights = AsyncMock(return_value=0)
    mock_mem.decay_stale_insights = AsyncMock(return_value=0)

    mock_session = AsyncMock()

    with (
        patch("app.core.insight_memory.InsightMemoryService", return_value=mock_mem),
        patch("app.main.async_session_factory") as mock_sf,
        patch("app.main.logger") as mock_logger,
    ):
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        await _periodic_insight_maintenance()

    # No INFO log emitted when both counters are zero
    info_calls = [c for c in mock_logger.info.call_args_list if c]
    insight_info_calls = [c for c in info_calls if "insight maintenance" in str(c)]
    assert not insight_info_calls
