"""Tests for the hourly analytics-collect wave and its ARQ job (T7 — spec §3.2).

The wave is the only thing standing between "a user enabled collection" and
"data appears", so the tests exercise the real selection query against a real
(in-memory) database rather than a mocked service: a connection is dispatched
**only** when it is an analytics source, active, collection-enabled, and its
``collection_hour`` equals the current local hour. Getting any one of those
filters wrong is silent — nothing errors, data simply never arrives.

Two dispatch invariants get their own tests because both have already bitten
this codebase once:

* the ``task_id`` is **day-scoped**, so two waves in one calendar day dedupe;
* the **no-Redis path** genuinely runs the coroutine. ``task_queue`` falls back
  to in-process asyncio when ``REDIS_URL`` is unset, and a ``coro_factory``
  that is missing or wrong fails only in that mode — i.e. in local dev and in
  any deployment without Redis.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.task_queue as tq_mod
import app.main as main_mod
import app.models  # noqa: F401 — register every mapper
from app.models.base import Base, enable_sqlite_fk
from app.models.connection import Connection
from app.models.project import Project

FROZEN_HOUR = 3
RUN_DATE = "2026-08-01"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory(monkeypatch: pytest.MonkeyPatch):
    """A real in-memory database, patched in as ``main.async_session_factory``."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_fk(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(main_mod, "async_session_factory", sm)
    yield sm
    await engine.dispose()


@pytest_asyncio.fixture
async def project_id(session_factory) -> str:
    async with session_factory() as session:
        project = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
        session.add(project)
        await session.commit()
        return project.id


async def _add_connection(session_factory, project_id: str, name: str, **kwargs: Any) -> str:
    defaults: dict[str, Any] = {
        "source_type": "ga4",
        "is_active": True,
        "collection_enabled": True,
        "collection_hour": FROZEN_HOUR,
    }
    defaults.update(kwargs)
    async with session_factory() as session:
        conn = Connection(project_id=project_id, name=name, **defaults)
        session.add(conn)
        await session.commit()
        return conn.id


def _freeze_clock(
    monkeypatch: pytest.MonkeyPatch, *, hour: int = FROZEN_HOUR, date: str = RUN_DATE
):
    """Freeze ``datetime.now(tz)`` inside ``app.main`` at *hour* on *date*."""
    original = main_mod.datetime

    class FrozenDatetime(original):  # type: ignore[misc, valid-type]
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            frozen = MagicMock()
            frozen.hour = hour
            frozen.strftime = lambda _fmt: date
            return frozen

    monkeypatch.setattr(main_mod, "datetime", FrozenDatetime)


def _grant_lock(monkeypatch: pytest.MonkeyPatch, *, acquired: bool = True) -> list[str]:
    keys: list[str] = []

    @asynccontextmanager
    async def fake_lock(key, *, ttl_seconds):
        keys.append(key)
        yield acquired

    monkeypatch.setattr(main_mod, "redis_lock", fake_lock)
    return keys


def _capture_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_enqueue(task_name, coro_factory=None, *, task_id=None, **kwargs):
        calls.append(
            {
                "task_name": task_name,
                "coro_factory": coro_factory,
                "task_id": task_id,
                **kwargs,
            }
        )
        return task_id

    monkeypatch.setattr(tq_mod, "enqueue", fake_enqueue)
    return calls


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


class TestWaveSelection:
    async def test_only_due_connections_are_dispatched(
        self, session_factory, project_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        due = await _add_connection(session_factory, project_id, "due")
        await _add_connection(session_factory, project_id, "wrong-hour", collection_hour=11)
        await _add_connection(session_factory, project_id, "paused", collection_enabled=False)
        await _add_connection(session_factory, project_id, "inactive", is_active=False)
        await _add_connection(
            session_factory, project_id, "a-database", source_type="database", db_type="postgres"
        )
        _freeze_clock(monkeypatch)
        _grant_lock(monkeypatch)
        calls = _capture_enqueue(monkeypatch)

        await main_mod._dispatch_analytics_collect_wave()

        assert [call["connection_id"] for call in calls] == [due]

    async def test_every_analytics_vendor_is_dispatched(
        self, session_factory, project_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The filter is on the vendor family, not hard-coded to GA4."""
        from app.services.analytics_collect_service import ANALYTICS_SOURCE_TYPES

        expected = set()
        for source_type in ANALYTICS_SOURCE_TYPES:
            expected.add(
                await _add_connection(
                    session_factory, project_id, f"c-{source_type}", source_type=source_type
                )
            )
        _freeze_clock(monkeypatch)
        _grant_lock(monkeypatch)
        calls = _capture_enqueue(monkeypatch)

        await main_mod._dispatch_analytics_collect_wave()

        assert {call["connection_id"] for call in calls} == expected

    async def test_wave_dispatches_nothing_when_the_lock_is_held(
        self, session_factory, project_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        await _add_connection(session_factory, project_id, "due")
        _freeze_clock(monkeypatch)
        _grant_lock(monkeypatch, acquired=False)
        calls = _capture_enqueue(monkeypatch)

        await main_mod._dispatch_analytics_collect_wave()

        assert calls == []

    async def test_lock_key_is_scoped_to_the_hour(
        self, session_factory, monkeypatch: pytest.MonkeyPatch
    ):
        """Two dynos in the same hour contend; the next hour is a fresh wave."""
        _freeze_clock(monkeypatch, hour=7)
        keys = _grant_lock(monkeypatch, acquired=False)

        await main_mod._dispatch_analytics_collect_wave()

        assert len(keys) == 1
        assert "analytics_collect" in keys[0]
        assert keys[0].endswith(f"{RUN_DATE}:7")


# ---------------------------------------------------------------------------
# Dispatch shape
# ---------------------------------------------------------------------------


class TestDispatch:
    async def test_task_id_is_day_scoped(
        self, session_factory, project_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        conn_id = await _add_connection(session_factory, project_id, "due")
        _grant_lock(monkeypatch)
        calls = _capture_enqueue(monkeypatch)

        _freeze_clock(monkeypatch)
        await main_mod._dispatch_analytics_collect_wave()
        _freeze_clock(monkeypatch, hour=FROZEN_HOUR)
        await main_mod._dispatch_analytics_collect_wave()

        assert [call["task_id"] for call in calls] == [
            f"analytics_collect:{conn_id}:{RUN_DATE}"
        ] * 2

        _freeze_clock(monkeypatch, date="2026-08-02")
        await main_mod._dispatch_analytics_collect_wave()
        assert calls[-1]["task_id"] == f"analytics_collect:{conn_id}:2026-08-02"

    async def test_job_name_and_timeout_are_forwarded(
        self, session_factory, project_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        await _add_connection(session_factory, project_id, "due")
        _freeze_clock(monkeypatch)
        _grant_lock(monkeypatch)
        monkeypatch.setattr(main_mod.settings, "analytics_collect_job_timeout_seconds", 900)
        calls = _capture_enqueue(monkeypatch)

        await main_mod._dispatch_analytics_collect_wave()

        assert calls[0]["task_name"] == "run_analytics_collect"
        assert calls[0]["_job_timeout"] == 900

    async def test_no_redis_path_actually_runs_the_collection(
        self, session_factory, project_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        """With the in-process queue the ``coro_factory`` must really execute."""
        import app.services.analytics_collect_service as collect_mod

        conn_id = await _add_connection(session_factory, project_id, "due")
        _freeze_clock(monkeypatch)
        _grant_lock(monkeypatch)
        monkeypatch.setattr(tq_mod, "_arq_pool", None)
        tq_mod._fallback_tasks.clear()

        collected: list[str] = []

        class FakeService:
            async def collect(self, connection_id: str):
                collected.append(connection_id)
                return collect_mod.CollectOutcome()

        monkeypatch.setattr(collect_mod, "AnalyticsCollectService", FakeService)

        await main_mod._dispatch_analytics_collect_wave()
        for _ in range(50):
            if collected:
                break
            await asyncio.sleep(0.01)

        assert collected == [conn_id]

    async def test_same_day_double_dispatch_runs_one_job(
        self, session_factory, project_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The day-scoped task_id dedupes an already-running in-process job."""
        import app.services.analytics_collect_service as collect_mod

        await _add_connection(session_factory, project_id, "due")
        _freeze_clock(monkeypatch)
        _grant_lock(monkeypatch)
        monkeypatch.setattr(tq_mod, "_arq_pool", None)
        tq_mod._fallback_tasks.clear()

        started = 0
        release = asyncio.Event()

        class SlowService:
            async def collect(self, connection_id: str):
                nonlocal started
                started += 1
                await release.wait()
                return collect_mod.CollectOutcome()

        monkeypatch.setattr(collect_mod, "AnalyticsCollectService", SlowService)

        await main_mod._dispatch_analytics_collect_wave()
        await asyncio.sleep(0.01)
        await main_mod._dispatch_analytics_collect_wave()
        await asyncio.sleep(0.01)

        assert started == 1
        release.set()
        await asyncio.sleep(0.01)
        tq_mod._fallback_tasks.clear()


# ---------------------------------------------------------------------------
# The loop's flag gate
# ---------------------------------------------------------------------------


class TestCronLoop:
    async def test_loop_returns_immediately_when_disabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(main_mod.settings, "analytics_collect_enabled", False)
        dispatched: list[int] = []

        async def fake_wave():
            dispatched.append(1)

        monkeypatch.setattr(main_mod, "_dispatch_analytics_collect_wave", fake_wave)

        await asyncio.wait_for(main_mod._analytics_collect_cron_loop(), timeout=1)

        assert dispatched == []

    async def test_loop_keeps_running_when_enabled_and_stops_on_cancel(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Enabled, the loop stays alive until cancelled (the shutdown path)."""
        monkeypatch.setattr(main_mod.settings, "analytics_collect_enabled", True)

        task = asyncio.create_task(main_mod._analytics_collect_cron_loop())
        await asyncio.sleep(0.05)
        assert not task.done(), "the loop returned instead of waiting for the next hour"

        task.cancel()
        await task  # the loop swallows CancelledError and returns cleanly
        assert task.done()


# ---------------------------------------------------------------------------
# The ARQ job
# ---------------------------------------------------------------------------


class TestJournalRetention:
    """REQ-015: the journal is pruned by the existing 24 h maintenance cron."""

    async def test_prune_uses_the_configured_retention_window(
        self, session_factory, project_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        from app.analytics import journal
        from app.models.analytics_import import AnalyticsImport

        conn_id = await _add_connection(session_factory, project_id, "due")
        async with session_factory() as session:
            await journal.record(
                session, connection_id=conn_id, report="overview", period="2020-01-01", status="ok"
            )
            stale = (await session.execute(select(AnalyticsImport))).scalars().one()
            stale.fetched_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=500)
            await session.commit()
        monkeypatch.setattr(main_mod.settings, "analytics_journal_retention_days", 400)

        await main_mod._prune_analytics_journal()

        async with session_factory() as session:
            assert (await session.execute(select(AnalyticsImport))).scalars().all() == []

    async def test_prune_keeps_rows_inside_the_window(
        self, session_factory, project_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        from app.analytics import journal
        from app.models.analytics_import import AnalyticsImport

        conn_id = await _add_connection(session_factory, project_id, "due")
        async with session_factory() as session:
            await journal.record(
                session, connection_id=conn_id, report="overview", period="2026-07-15", status="ok"
            )
        monkeypatch.setattr(main_mod.settings, "analytics_journal_retention_days", 400)

        await main_mod._prune_analytics_journal()

        async with session_factory() as session:
            assert len((await session.execute(select(AnalyticsImport))).scalars().all()) == 1

    async def test_prune_failure_never_escapes_the_maintenance_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from app.analytics import journal

        async def boom(*_args, **_kwargs):
            raise RuntimeError("database is on fire")

        monkeypatch.setattr(journal, "prune", boom)

        await main_mod._prune_analytics_journal()


def _worker_module(monkeypatch: pytest.MonkeyPatch):
    """Import ``app.worker`` with arq stubbed (arq is absent in the unit venv)."""
    import types

    from tests.unit.test_task_queue import _import_worker_with_arq_stub

    return _import_worker_with_arq_stub(monkeypatch, types.ModuleType("arq.worker"))


class TestWorkerJob:
    async def test_job_collects_the_connection(self, monkeypatch: pytest.MonkeyPatch):
        import app.services.analytics_collect_service as collect_mod

        worker_mod = _worker_module(monkeypatch)
        collected: list[str] = []

        class FakeService:
            async def collect(self, connection_id: str):
                collected.append(connection_id)
                return collect_mod.CollectOutcome(rows_written=3, periods_ok=1)

        monkeypatch.setattr(collect_mod, "AnalyticsCollectService", FakeService)

        await worker_mod.run_analytics_collect({}, connection_id="conn-9")

        assert collected == ["conn-9"]

    async def test_job_never_raises_out_of_the_worker(self, monkeypatch: pytest.MonkeyPatch):
        """An unhandled exception would poison the ARQ worker's job slot."""
        import app.services.analytics_collect_service as collect_mod

        worker_mod = _worker_module(monkeypatch)

        class ExplodingService:
            async def collect(self, connection_id: str):
                raise RuntimeError("database is on fire")

        monkeypatch.setattr(collect_mod, "AnalyticsCollectService", ExplodingService)

        await worker_mod.run_analytics_collect({}, connection_id="conn-9")

    def test_registered_in_worker_settings_with_its_timeout(self, monkeypatch: pytest.MonkeyPatch):
        import types

        from tests.unit.test_task_queue import _import_worker_with_arq_stub

        captured: list[tuple[Any, dict]] = []

        def fake_func(coroutine, **kwargs):
            captured.append((coroutine, kwargs))
            return ("Function", coroutine.__name__, kwargs)

        worker_mod = types.ModuleType("arq.worker")
        worker_mod.func = fake_func  # type: ignore[attr-defined]
        w = _import_worker_with_arq_stub(monkeypatch, worker_mod)

        from app.config import settings

        registrations = [f for f in w.WorkerSettings.functions if isinstance(f, tuple)]
        assert (
            "Function",
            "run_analytics_collect",
            {"timeout": settings.analytics_collect_job_timeout_seconds},
        ) in registrations
