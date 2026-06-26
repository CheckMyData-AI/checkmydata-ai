"""Unit tests for daily knowledge sync cron."""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.indexing_run import IndexingRun
from app.models.project import Project
from app.services.daily_knowledge_sync_service import (
    _STATUS_SUCCESS,
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
            result = await svc._orchestrate("proj-1")

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
        result = await svc._orchestrate("proj-seq")

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
        result = await svc._orchestrate("proj-multi")

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
        result = await svc._orchestrate("proj-partial")

    assert result.status == "partial"
    conn_steps = result.steps_json["connections"][0]
    assert conn_steps["db_index"]["status"] == "failed"
    assert conn_steps["code_db_sync"]["status"] == "skipped"


# --------------------------------------------------------------------------- #
# T11 (R5): parent heartbeat, adopt-not-run, progress, budget skip, overview.  #
# --------------------------------------------------------------------------- #


@pytest.fixture
async def file_db():
    """A real SQLite engine session factory for projection-aware tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield sm
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_parent_run_heartbeat_refreshed_during_orchestrate(monkeypatch, file_db):
    """H1: the PARENT daily_sync run's heartbeat_at advances during a slow orchestrate."""
    sm = file_db
    async with sm() as s:
        s.add(Project(id="p-hb", name="x", repo_url="https://x/y.git"))
        await s.commit()
    monkeypatch.setattr("app.services.daily_knowledge_sync_service.async_session_factory", sm)
    # Tight heartbeat so a short sleep crosses several beats.
    monkeypatch.setattr(
        "app.services.daily_knowledge_sync_service.settings.heartbeat_interval_seconds",
        0,
        raising=False,
    )

    svc = DailyKnowledgeSyncService()
    captured: dict = {}

    async def slow_orchestrate(project_id, *, run_id):
        # Capture the heartbeat at start, sleep, then read again at the end.
        async with sm() as s:
            run = await s.get(IndexingRun, run_id)
            captured["before"] = run.heartbeat_at
        await asyncio.sleep(0.15)
        return KnowledgeSyncRunResult(project_id=project_id, status=_STATUS_SUCCESS)

    monkeypatch.setattr(svc, "_orchestrate", slow_orchestrate)
    await svc.run_for_project("p-hb")

    async with sm() as s:
        run = (
            (await s.execute(select(IndexingRun).where(IndexingRun.kind == "daily_sync")))
            .scalars()
            .one()
        )
    before = captured["before"]
    after = run.heartbeat_at
    assert before is not None and after is not None
    if before.tzinfo is None:
        before = before.replace(tzinfo=UTC)
    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    assert after > before, "parent heartbeat_at did not advance during orchestrate"


@pytest.mark.asyncio
async def test_start_child_wf_returns_already_active_tuple(monkeypatch):
    """H9: _start_child_wf returns (None, True) when a run is already active."""
    from app.services.run_coordinator import RunAlreadyActiveError

    svc = DailyKnowledgeSyncService()

    class _Coord:
        async def start(self, *a, **k):
            raise RunAlreadyActiveError("existing-run")

    monkeypatch.setattr("app.services.run_coordinator.RunCoordinator", lambda: _Coord())
    with patch("app.services.daily_knowledge_sync_service.async_session_factory") as mock_sf:
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        wf_id, already = await svc._start_child_wf("db_index", "c1", "p1")
    assert wf_id is None
    assert already is True


@pytest.mark.asyncio
async def test_child_skips_when_already_active(monkeypatch):
    """H9: a sub-step returns SKIPPED (not an untracked pipeline) when adopted."""
    svc = DailyKnowledgeSyncService()

    # Child wf already active -> (None, True).
    monkeypatch.setattr(svc, "_start_child_wf", AsyncMock(return_value=(None, True)))

    # Guards must pass so we reach the adopt-check.
    from app.services.code_db_sync_service import CodeDbSyncService
    from app.services.db_index_service import DbIndexService

    monkeypatch.setattr(CodeDbSyncService, "get_sync_status", AsyncMock(return_value="idle"))
    monkeypatch.setattr(DbIndexService, "is_indexed", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.services.sync_budget.preflight_owner_budget",
        AsyncMock(return_value=(True, None, "owner")),
    )
    pipeline_run = AsyncMock()
    monkeypatch.setattr("app.knowledge.code_db_sync_pipeline.CodeDbSyncPipeline.run", pipeline_run)

    with patch("app.services.daily_knowledge_sync_service.async_session_factory") as mock_sf:
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        status, detail = await svc._run_code_db_sync("c1", "p1")

    assert status == "skipped"
    assert "adopt" in (detail or "").lower()
    pipeline_run.assert_not_called()


@pytest.mark.asyncio
async def test_budget_skip_in_code_db_sync(monkeypatch):
    """H5: when owner budget is exceeded, sync is SKIPPED with a budget reason."""
    svc = DailyKnowledgeSyncService()

    monkeypatch.setattr(svc, "_start_child_wf", AsyncMock(return_value=("wf", False)))

    from app.services.code_db_sync_service import CodeDbSyncService
    from app.services.db_index_service import DbIndexService

    monkeypatch.setattr(CodeDbSyncService, "get_sync_status", AsyncMock(return_value="idle"))
    monkeypatch.setattr(DbIndexService, "is_indexed", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.services.sync_budget.preflight_owner_budget",
        AsyncMock(return_value=(False, "daily limit reached", "owner")),
    )
    pipeline_run = AsyncMock()
    monkeypatch.setattr("app.knowledge.code_db_sync_pipeline.CodeDbSyncPipeline.run", pipeline_run)

    with patch("app.services.daily_knowledge_sync_service.async_session_factory") as mock_sf:
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        status, detail = await svc._run_code_db_sync("c1", "p1")

    assert status == "skipped"
    assert "owner budget" in (detail or "")
    assert "daily limit reached" in (detail or "")
    pipeline_run.assert_not_called()


@pytest.mark.asyncio
async def test_overview_regen_after_successful_sync(monkeypatch):
    """M5: a successful code-db sync regenerates the connection overview."""
    svc = DailyKnowledgeSyncService()

    monkeypatch.setattr(svc, "_start_child_wf", AsyncMock(return_value=("wf", False)))

    from app.services.code_db_sync_service import CodeDbSyncService
    from app.services.db_index_service import DbIndexService

    monkeypatch.setattr(CodeDbSyncService, "get_sync_status", AsyncMock(return_value="idle"))
    monkeypatch.setattr(CodeDbSyncService, "set_sync_status", AsyncMock())
    monkeypatch.setattr(DbIndexService, "is_indexed", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.services.sync_budget.preflight_owner_budget",
        AsyncMock(return_value=(True, None, "owner")),
    )
    monkeypatch.setattr(
        "app.knowledge.code_db_sync_pipeline.CodeDbSyncPipeline.run",
        AsyncMock(return_value={"status": "ok"}),
    )
    regen = AsyncMock()
    monkeypatch.setattr("app.api.routes.connections._regenerate_overview", regen)

    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    with patch("app.services.daily_knowledge_sync_service.async_session_factory") as mock_sf:
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
        status, _detail = await svc._run_code_db_sync("c1", "p1")

    assert status == "completed"
    regen.assert_awaited_once_with("p1", "c1")


@pytest.mark.asyncio
async def test_progress_emits_match_manifest(monkeypatch, file_db):
    """M3: orchestrate emits manifest-aligned progress steps on the PARENT wf."""
    from app.knowledge.run_manifests import resolve_manifest
    from app.services.run_coordinator import RunCoordinator

    manifest_keys = {s.key for s in resolve_manifest("daily_sync")}
    assert manifest_keys == {
        "plan_targets",
        "repo_index",
        "db_index",
        "code_db_sync",
        "summarize",
    }

    sm = file_db
    async with sm() as s:
        s.add(Project(id="p-prog", name="x", repo_url="https://x/y.git"))
        await s.commit()
    monkeypatch.setattr("app.services.daily_knowledge_sync_service.async_session_factory", sm)

    svc = DailyKnowledgeSyncService()
    conn = MagicMock(id="c1", is_active=True, created_at=datetime(2026, 1, 1))
    monkeypatch.setattr(svc, "_active_connections", AsyncMock(return_value=[conn]))
    monkeypatch.setattr(svc, "_run_repo_index", AsyncMock(return_value=("completed", None)))
    monkeypatch.setattr(svc, "_run_db_index", AsyncMock(return_value=("completed", None)))
    monkeypatch.setattr(svc, "_run_code_db_sync", AsyncMock(return_value=("completed", None)))

    emits: list[tuple[str, str, str]] = []
    orig_emit = svc._tracker.emit

    async def spy_emit(workflow_id, step, status, detail="", **kw):
        emits.append((workflow_id, step, status))
        await orig_emit(workflow_id, step, status, detail, **kw)

    monkeypatch.setattr(svc._tracker, "emit", spy_emit)

    # Mint the parent run ourselves so we know its workflow_id.
    coord = RunCoordinator()
    async with sm() as s:
        parent = await coord.start(
            s, kind="daily_sync", project_id="p-prog", connection_id=None, trigger="schedule"
        )
        parent_wf = parent.workflow_id
        run_id = parent.id

    result = await svc._orchestrate("p-prog", run_id=run_id)
    assert result.status == "success"

    steps_started = [step for (wf, step, st) in emits if wf == parent_wf and st == "started"]
    steps_completed = [step for (wf, step, st) in emits if wf == parent_wf and st == "completed"]
    for key in ("plan_targets", "repo_index", "db_index", "code_db_sync", "summarize"):
        assert key in steps_started, f"missing started emit for {key}"
        assert key in steps_completed, f"missing completed emit for {key}"


@pytest.mark.asyncio
async def test_adopted_parent_projects_and_partial_on_skip(monkeypatch, file_db):
    """C4-4: an ADOPTED parent still projects progress; an adopted child -> PARTIAL."""
    from app.services.run_coordinator import RunCoordinator

    sm = file_db
    async with sm() as s:
        s.add(Project(id="p-adopt", name="x", repo_url="https://x/y.git"))
        await s.commit()
    monkeypatch.setattr("app.services.daily_knowledge_sync_service.async_session_factory", sm)

    # Ensure the projection hook is attached so emits advance the parent run.
    RunCoordinator().attach()

    # Simulate sync_now having minted the daily_sync run BEFORE run_for_project.
    coord = RunCoordinator()
    async with sm() as s:
        minted = await coord.start(
            s, kind="daily_sync", project_id="p-adopt", connection_id=None, trigger="manual"
        )
        minted_id = minted.id

    svc = DailyKnowledgeSyncService()
    conn = MagicMock(id="c1", is_active=True, created_at=datetime(2026, 1, 1))
    monkeypatch.setattr(svc, "_active_connections", AsyncMock(return_value=[conn]))
    monkeypatch.setattr(svc, "_run_repo_index", AsyncMock(return_value=("completed", None)))
    monkeypatch.setattr(svc, "_run_db_index", AsyncMock(return_value=("completed", None)))
    # The sub-step is adopted (already active elsewhere) -> SKIPPED.
    monkeypatch.setattr(
        svc, "_run_code_db_sync", AsyncMock(return_value=("skipped", "already running (adopted)"))
    )

    result = await svc.run_for_project("p-adopt", trigger="schedule")

    # (b) adopted child skip -> aggregate is PARTIAL, not SUCCESS.
    assert result.status == "partial"

    # (a) the adopted parent run advanced past 0% and reached a terminal state.
    async with sm() as s:
        run = await s.get(IndexingRun, minted_id)
    assert run is not None
    assert run.status in ("completed", "failed")
    assert run.progress_pct > 0
