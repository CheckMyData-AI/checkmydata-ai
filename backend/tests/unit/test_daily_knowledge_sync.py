"""Unit tests for daily knowledge sync cron."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services.daily_knowledge_sync_service import (
    DailyKnowledgeSyncService,
    KnowledgeSyncRunResult,
    compute_next_scheduled_run,
)


def test_next_run_midnight_cet_winter():
    """00:00 Europe/Berlin in winter (CET, UTC+1)."""
    tz = ZoneInfo("Europe/Berlin")
    # 2026-01-15 23:30 CET
    now = datetime(2026, 1, 15, 23, 30, tzinfo=tz)
    nxt = compute_next_scheduled_run(now, hour=0, timezone_name="Europe/Berlin")
    assert nxt == datetime(2026, 1, 16, 0, 0, tzinfo=tz)


def test_next_run_midnight_cet_summer():
    """00:00 Europe/Berlin in summer (CEST, UTC+2)."""
    tz = ZoneInfo("Europe/Berlin")
    # 2026-06-19 22:30 CEST
    now = datetime(2026, 6, 19, 22, 30, tzinfo=tz)
    nxt = compute_next_scheduled_run(now, hour=0, timezone_name="Europe/Berlin")
    assert nxt == datetime(2026, 6, 20, 0, 0, tzinfo=tz)


def test_next_run_already_past_today():
    tz = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 6, 19, 1, 0, tzinfo=tz)
    nxt = compute_next_scheduled_run(now, hour=0, timezone_name="Europe/Berlin")
    assert nxt == datetime(2026, 6, 20, 0, 0, tzinfo=tz)


@pytest.mark.asyncio
async def test_eligible_project_skips_no_repo():
    svc = DailyKnowledgeSyncService()
    project = MagicMock()
    project.id = "proj-1"
    project.repo_url = None

    with patch.object(svc, "_project_svc") as mock_proj:
        mock_proj.get = AsyncMock(return_value=project)
        with patch("app.services.daily_knowledge_sync_service.async_session_factory") as mock_sf:
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await svc.run_for_project("proj-1")

    assert result.status == "skipped"
    assert result.steps_json.get("reason") == "no_repo"


@pytest.mark.asyncio
async def test_run_for_project_sequential_order():
    svc = DailyKnowledgeSyncService()
    call_order: list[str] = []

    project = MagicMock()
    project.id = "proj-seq"
    project.repo_url = "https://github.com/org/repo.git"

    conn = MagicMock()
    conn.id = "conn-1"
    conn.is_active = True
    conn.created_at = datetime(2026, 1, 1)

    async def _repo(project_id):
        call_order.append("repo")
        return ("completed", None)

    async def _db(connection_id, project_id):
        call_order.append("db")
        return ("completed", None)

    async def _sync(connection_id, project_id):
        call_order.append("sync")
        return ("completed", None)

    with (
        patch.object(svc, "_project_svc") as mock_proj,
        patch.object(svc, "_active_connections", AsyncMock(return_value=[conn])),
        patch.object(svc, "_run_repo_index", AsyncMock(side_effect=_repo)),
        patch.object(svc, "_run_db_index", AsyncMock(side_effect=_db)),
        patch.object(svc, "_run_code_db_sync", AsyncMock(side_effect=_sync)),
        patch("app.services.daily_knowledge_sync_service.async_session_factory") as mock_sf,
    ):
        mock_proj.get = AsyncMock(return_value=project)
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await svc.run_for_project("proj-seq")

    assert call_order == ["repo", "db", "sync"]
    assert result.status == "success"


@pytest.mark.asyncio
async def test_run_for_project_all_active_connections():
    svc = DailyKnowledgeSyncService()
    db_calls: list[str] = []

    project = MagicMock()
    project.id = "proj-multi"
    project.repo_url = "https://github.com/org/repo.git"

    conn_active_1 = MagicMock(id="c1", is_active=True, created_at=datetime(2026, 1, 1))
    conn_active_2 = MagicMock(id="c2", is_active=True, created_at=datetime(2026, 1, 2))
    conn_inactive = MagicMock(id="c3", is_active=False, created_at=datetime(2026, 1, 3))

    async def _db(connection_id, project_id):
        db_calls.append(connection_id)
        return ("completed", None)

    with (
        patch.object(svc, "_project_svc") as mock_proj,
        patch.object(
            svc,
            "_active_connections",
            AsyncMock(return_value=[conn_active_1, conn_active_2]),
        ),
        patch.object(svc, "_run_repo_index", AsyncMock(return_value=("completed", None))),
        patch.object(svc, "_run_db_index", AsyncMock(side_effect=_db)),
        patch.object(svc, "_run_code_db_sync", AsyncMock(return_value=("completed", None))),
        patch("app.services.daily_knowledge_sync_service.async_session_factory") as mock_sf,
    ):
        mock_proj.get = AsyncMock(return_value=project)
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await svc.run_for_project("proj-multi")

    assert db_calls == ["c1", "c2"]
    assert len(result.steps_json["connections"]) == 2
    assert conn_inactive.id not in db_calls


@pytest.mark.asyncio
async def test_chain_sync_disabled_for_daily():
    with patch(
        "app.api.routes.repos._run_index_background",
        new_callable=AsyncMock,
    ) as mock_bg:
        with patch(
            "app.api.routes.repos._project_svc.get",
            new_callable=AsyncMock,
            return_value=MagicMock(repo_url="https://x/y.git"),
        ):
            with patch(
                "app.api.routes.repos.tracker.begin",
                new_callable=AsyncMock,
                return_value="wf",
            ):
                with patch("app.api.routes.repos.async_session_factory") as mock_sf:
                    mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
                    mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
                    from app.api.routes.repos import run_repo_index_task

                    await run_repo_index_task("p1", chain_sync=False)

    mock_bg.assert_awaited_once()
    assert mock_bg.await_args.kwargs.get("chain_sync") is False


@pytest.mark.asyncio
async def test_persist_run_writes_row():
    svc = DailyKnowledgeSyncService()
    result = KnowledgeSyncRunResult(
        project_id="proj-db",
        status="success",
        duration_seconds=12.5,
        steps_json={"repo_index": {"status": "completed"}},
    )

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    with patch("app.services.daily_knowledge_sync_service.async_session_factory") as mock_sf:
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        await svc.persist_run(result)

    mock_session.add.assert_called_once()
    row = mock_session.add.call_args[0][0]
    assert row.project_id == "proj-db"
    assert row.status == "success"
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_partial_status_on_connection_failure():
    svc = DailyKnowledgeSyncService()

    project = MagicMock()
    project.id = "proj-partial"
    project.repo_url = "https://github.com/org/repo.git"

    conn = MagicMock(id="conn-fail", is_active=True, created_at=datetime(2026, 1, 1))

    with (
        patch.object(svc, "_project_svc") as mock_proj,
        patch.object(svc, "_active_connections", AsyncMock(return_value=[conn])),
        patch.object(svc, "_run_repo_index", AsyncMock(return_value=("completed", None))),
        patch.object(
            svc,
            "_run_db_index",
            AsyncMock(return_value=("failed", "connection timeout")),
        ),
        patch("app.services.daily_knowledge_sync_service.async_session_factory") as mock_sf,
    ):
        mock_proj.get = AsyncMock(return_value=project)
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await svc.run_for_project("proj-partial")

    assert result.status == "partial"
    conn_steps = result.steps_json["connections"][0]
    assert conn_steps["db_index"]["status"] == "failed"
    assert conn_steps["code_db_sync"]["status"] == "skipped"
