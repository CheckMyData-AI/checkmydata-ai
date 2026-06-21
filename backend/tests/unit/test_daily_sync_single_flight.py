"""Single-flight cron test: redis_lock prevents duplicate dispatch across dynos."""

from __future__ import annotations

from contextlib import asynccontextmanager

import app.main as main_mod


async def test_wave_skips_when_lock_not_acquired(monkeypatch):
    """When the lock is denied (yields False), the dispatch wave short-circuits before any work."""

    @asynccontextmanager
    async def denied(key, *, ttl_seconds):
        yield False

    monkeypatch.setattr(main_mod, "redis_lock", denied)

    called = {"n": 0}

    async def fake_list_all(session):
        return []

    class FakeSvc:
        _project_svc = type("P", (), {"list_all": staticmethod(fake_list_all)})()

        async def list_eligible_projects(self, s):
            called["n"] += 1
            return []

    # DailyKnowledgeSyncService is imported inside the function body — patch the source module
    import app.services.daily_knowledge_sync_service as svc_mod

    monkeypatch.setattr(svc_mod, "DailyKnowledgeSyncService", lambda: FakeSvc())

    await main_mod._dispatch_daily_knowledge_sync_wave()
    assert called["n"] == 0, "list_eligible_projects should NOT be called when lock is denied"


async def test_wave_proceeds_when_lock_acquired(monkeypatch):
    """When the lock is acquired (yields True), list_eligible_projects is called."""

    @asynccontextmanager
    async def acquired_cm(key, *, ttl_seconds):
        yield True

    monkeypatch.setattr(main_mod, "redis_lock", acquired_cm)

    called = {"n": 0}

    async def fake_list_all(session):
        return []

    class FakeSvc:
        _project_svc = type("P", (), {"list_all": staticmethod(fake_list_all)})()

        async def list_eligible_projects(self, s):
            called["n"] += 1
            return []

    # DailyKnowledgeSyncService is imported inside the function body via
    # `from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService`.
    # Python caches module objects so we patch the attribute on the already-imported module.
    import app.services.daily_knowledge_sync_service as svc_mod

    monkeypatch.setattr(svc_mod, "DailyKnowledgeSyncService", FakeSvc)

    # Patch async_session_factory to provide a minimal async context manager
    from contextlib import asynccontextmanager as acm

    class FakeSession:
        pass

    @acm
    async def fake_session_factory():
        yield FakeSession()

    monkeypatch.setattr(main_mod, "async_session_factory", fake_session_factory)

    await main_mod._dispatch_daily_knowledge_sync_wave()
    assert called["n"] == 1, "list_eligible_projects SHOULD be called when lock is acquired"
