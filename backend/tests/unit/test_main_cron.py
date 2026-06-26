"""Tests for T16: cron wave honors per-project hour + reconciler covers all connections.

M4: _dispatch_daily_knowledge_sync_wave dispatches only projects whose effective hour
    equals current_hour; uses hour-scoped Redis lock.
M1: _freshness_reconcile iterates all connections (not just connections[0]);
    applies a one-shot guard for sync_failed to prevent retry storms.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import app.main as main_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(pid: str) -> Any:
    p = MagicMock()
    p.id = pid
    return p


def _make_connection(cid: str) -> Any:
    c = MagicMock()
    c.id = cid
    return c


# ---------------------------------------------------------------------------
# M4 — wave filters by effective hour
# ---------------------------------------------------------------------------


async def test_wave_dispatches_only_projects_matching_current_hour(monkeypatch):
    """Only projects whose effective hour equals the current local hour are dispatched."""

    import app.services.daily_knowledge_sync_service as svc_mod
    import app.services.sync_schedule_service as schedule_mod

    # Freeze "now" at hour 3 in the configured timezone by patching datetime.now
    # inside the main module.  We intercept `datetime.now(tz).hour`.
    frozen_hour = 3

    original_datetime = main_mod.datetime

    class FrozenDatetime(original_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            real = original_datetime.now(tz)
            # return a mock whose .hour == frozen_hour, .strftime keeps working
            m = MagicMock()
            m.hour = frozen_hour
            m.strftime = real.strftime
            return m

    monkeypatch.setattr(main_mod, "datetime", FrozenDatetime)

    # Lock always acquired
    @asynccontextmanager
    async def acquired_cm(key, *, ttl_seconds):
        yield True

    monkeypatch.setattr(main_mod, "redis_lock", acquired_cm)

    # Two projects: proj_a runs at hour 3 (matches), proj_b runs at hour 5 (no match)
    proj_a = _make_project("proj-a")
    proj_b = _make_project("proj-b")

    class FakeSvc:
        _project_svc = MagicMock()

        async def list_eligible_projects(self, s):
            return [proj_a, proj_b]

    FakeSvc._project_svc.list_all = AsyncMock(return_value=[proj_a, proj_b])

    monkeypatch.setattr(svc_mod, "DailyKnowledgeSyncService", lambda: FakeSvc())

    # SyncScheduleService.effective returns per-project hour
    effective_hours: dict[str, int] = {"proj-a": 3, "proj-b": 5}

    class FakeScheduleSvc:
        async def effective(self, session, project_id):
            return {"hour": effective_hours[project_id]}

    monkeypatch.setattr(schedule_mod, "SyncScheduleService", lambda: FakeScheduleSvc())

    # Fake session factory
    from contextlib import asynccontextmanager as acm

    @acm
    async def fake_session():
        yield MagicMock()

    monkeypatch.setattr(main_mod, "async_session_factory", fake_session)

    # Capture enqueued task_ids by patching the enqueue function on the task_queue module.
    # _dispatch_daily_knowledge_sync_wave does `from app.core import task_queue` and then
    # calls `await task_queue.enqueue(...)`, so we patch the module-level `enqueue` function.
    enqueued: list[str] = []

    import app.core.task_queue as tq_mod

    async def fake_enqueue(name, *, coro_factory, task_id, **kwargs):
        enqueued.append(task_id)

    monkeypatch.setattr(tq_mod, "enqueue", fake_enqueue)

    await main_mod._dispatch_daily_knowledge_sync_wave()

    # Only proj-a (hour==3) should be dispatched; proj-b (hour==5) skipped
    assert len(enqueued) == 1
    assert "proj-a" in enqueued[0]
    assert "proj-b" not in "".join(enqueued)


async def test_wave_uses_hour_scoped_lock_key(monkeypatch):
    """Redis lock key must contain both run_date AND current_hour."""

    frozen_hour = 7
    original_datetime = main_mod.datetime

    class FrozenDatetime(original_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            real = original_datetime.now(tz)
            m = MagicMock()
            m.hour = frozen_hour
            m.strftime = real.strftime
            return m

    monkeypatch.setattr(main_mod, "datetime", FrozenDatetime)

    captured_keys: list[str] = []

    @asynccontextmanager
    async def recording_lock(key, *, ttl_seconds):
        captured_keys.append(key)
        yield False  # deny — we just need to check the key

    monkeypatch.setattr(main_mod, "redis_lock", recording_lock)

    await main_mod._dispatch_daily_knowledge_sync_wave()

    assert len(captured_keys) == 1
    key = captured_keys[0]
    # Key must contain hour component
    assert f":{frozen_hour}" in key or f":{frozen_hour:02d}" in key, (
        f"Expected hour {frozen_hour} in lock key, got: {key!r}"
    )


# ---------------------------------------------------------------------------
# M1 — reconciler covers ALL connections
# ---------------------------------------------------------------------------


async def test_reconciler_iterates_all_connections(monkeypatch):
    """_freshness_reconcile must call maybe_autostart_db_index for EACH connection."""
    import app.api.routes.connections as conn_routes
    import app.services.connection_service as conn_svc_mod
    import app.services.knowledge_freshness_service as fresh_mod
    import app.services.project_service as proj_svc_mod

    # Enable reconciler
    monkeypatch.setattr(main_mod.settings, "freshness_reconciler_enabled", True)
    monkeypatch.setattr(main_mod.settings, "git_poll_enabled", True)  # skip git poll branch

    proj = _make_project("p1")
    conn1 = _make_connection("c1")
    conn2 = _make_connection("c2")
    conn3 = _make_connection("c3")

    class FakeProjSvc:
        async def list_all(self, s):
            return [proj]

    class FakeConnSvc:
        async def list_by_project(self, s, pid):
            return [conn1, conn2, conn3]

    # Freshness: db_index_stale for all, sync not stale
    class FakeFreshness:
        def __init__(self):
            self.overall_stale = True
            self.db_index_stale = True
            self.sync_stale = False
            self.sync_failed = False

    class FakeFreshSvc:
        async def evaluate(self, session, *, project_id, connection_id, repo_clone_dir):
            return FakeFreshness()

    monkeypatch.setattr(proj_svc_mod, "ProjectService", lambda: FakeProjSvc())
    monkeypatch.setattr(conn_svc_mod, "ConnectionService", lambda: FakeConnSvc())
    monkeypatch.setattr(fresh_mod, "KnowledgeFreshnessService", lambda: FakeFreshSvc())

    triggered_conn_ids: list[str] = []

    async def fake_maybe_autostart_db_index(conn_id, project_id):
        triggered_conn_ids.append(conn_id)
        return True

    async def fake_maybe_autostart_sync(conn_id, project_id):
        return False

    monkeypatch.setattr(conn_routes, "maybe_autostart_db_index", fake_maybe_autostart_db_index)
    monkeypatch.setattr(conn_routes, "maybe_autostart_sync", fake_maybe_autostart_sync)

    from contextlib import asynccontextmanager as acm

    @acm
    async def fake_session():
        yield MagicMock()

    monkeypatch.setattr(main_mod, "async_session_factory", fake_session)

    await main_mod._freshness_reconcile()

    # All three connections must have triggered db_index
    assert set(triggered_conn_ids) == {"c1", "c2", "c3"}, (
        f"Expected all 3 connections triggered, got: {triggered_conn_ids}"
    )


async def test_reconciler_sync_failed_one_shot_guard(monkeypatch):
    """A connection with sync_failed=True must be retried at most once per reconcile pass."""
    import app.api.routes.connections as conn_routes
    import app.services.connection_service as conn_svc_mod
    import app.services.knowledge_freshness_service as fresh_mod
    import app.services.project_service as proj_svc_mod

    monkeypatch.setattr(main_mod.settings, "freshness_reconciler_enabled", True)
    monkeypatch.setattr(main_mod.settings, "git_poll_enabled", True)

    # Two projects, both with one connection each that has sync_failed=True
    proj1 = _make_project("p1")
    proj2 = _make_project("p2")
    conn_p1 = _make_connection("c-p1")
    conn_p2 = _make_connection("c-p2")

    class FakeProjSvc:
        async def list_all(self, s):
            return [proj1, proj2]

    class FakeConnSvc:
        async def list_by_project(self, s, pid):
            return {
                "p1": [conn_p1],
                "p2": [conn_p2],
            }[pid]

    class FakeFreshness:
        def __init__(self):
            self.overall_stale = True
            self.db_index_stale = False
            self.sync_stale = True
            self.sync_failed = True

    class FakeFreshSvc:
        async def evaluate(self, session, *, project_id, connection_id, repo_clone_dir):
            return FakeFreshness()

    monkeypatch.setattr(proj_svc_mod, "ProjectService", lambda: FakeProjSvc())
    monkeypatch.setattr(conn_svc_mod, "ConnectionService", lambda: FakeConnSvc())
    monkeypatch.setattr(fresh_mod, "KnowledgeFreshnessService", lambda: FakeFreshSvc())

    sync_calls: list[str] = []

    async def fake_maybe_autostart_db_index(conn_id, project_id):
        return False

    async def fake_maybe_autostart_sync(conn_id, project_id):
        sync_calls.append(conn_id)
        return True

    monkeypatch.setattr(conn_routes, "maybe_autostart_db_index", fake_maybe_autostart_db_index)
    monkeypatch.setattr(conn_routes, "maybe_autostart_sync", fake_maybe_autostart_sync)

    from contextlib import asynccontextmanager as acm

    @acm
    async def fake_session():
        yield MagicMock()

    monkeypatch.setattr(main_mod, "async_session_factory", fake_session)

    await main_mod._freshness_reconcile()

    # Each (project, connection) pair should be attempted exactly once despite sync_failed
    assert sync_calls.count("c-p1") == 1
    assert sync_calls.count("c-p2") == 1

    # Run again — the guard is per-pass (in-memory set is reset per call), so each
    # new reconcile pass should retry once more.  The set is local to the function
    # invocation, so a second call should also yield exactly one attempt per connection.
    sync_calls.clear()
    await main_mod._freshness_reconcile()
    assert sync_calls.count("c-p1") == 1
    assert sync_calls.count("c-p2") == 1
