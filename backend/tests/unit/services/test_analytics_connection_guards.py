"""T12 — database-only paths must refuse analytics sources honestly.

Since the analytics spine (T2) made ``Connection.db_type`` / ``db_port`` /
``db_name`` nullable, a GA4 connection can reach code paths that assume a
database engine: ``get_connector(db_type)`` and ``SafetyGuard.validate(sql,
db_type)``. Without a guard those either explode (``ValueError: Unsupported
adapter: database``) or silently mis-handle the request.

These tests pin the honest behaviour:

* the four database-only API routes answer **HTTP 400** naming the connection
  and the vendor, never a 500 / stack trace;
* a batch referencing an analytics connection is recorded as ``failed`` with an
  explicit error, never a fake success;
* a normal database connection keeps working exactly as before (the
  regression half — it matters more than the new behaviour).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers every mapper on Base.metadata)
from app.api.deps import get_current_user, get_db
from app.api.routes import connection_learnings, health_monitor, notes, schedules
from app.connectors.base import ConnectionConfig, QueryResult
from app.core.rate_limit import limiter
from app.models.base import Base
from app.models.connection import Connection
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.saved_note import SavedNote
from app.models.scheduled_query import ScheduledQuery
from app.models.user import User
from app.services.batch_service import BatchService
from app.services.connection_service import ConnectionService

GA4_CONNECTION_NAME = "Marketing GA4"
DB_CONNECTION_NAME = "prod-postgres"


@dataclass
class Env:
    client: AsyncClient
    session: AsyncSession
    user: User
    project: Project
    db_conn: Connection
    ga_conn: Connection
    db_note: SavedNote
    ga_note: SavedNote
    db_schedule: ScheduledQuery
    ga_schedule: ScheduledQuery


def _build_app(session: AsyncSession, user: User) -> FastAPI:
    test_app = FastAPI()
    # slowapi reads ``request.app.state.limiter``; the fixture disables it, but
    # the attribute must exist for the decorated endpoints to import cleanly.
    test_app.state.limiter = limiter
    test_app.include_router(notes.router, prefix="/api/notes")
    test_app.include_router(schedules.router, prefix="/api/schedules")
    test_app.include_router(health_monitor.router, prefix="/api/connections")
    test_app.include_router(connection_learnings.router, prefix="/api/connections")

    async def _db():
        yield session

    test_app.dependency_overrides[get_db] = _db
    test_app.dependency_overrides[get_current_user] = lambda: {
        "user_id": user.id,
        "email": user.email,
    }
    return test_app


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = factory()

    user = User(
        email=f"t12-{uuid.uuid4().hex[:8]}@test.com",
        password_hash="x",
        display_name="T12",
    )
    project = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    session.add_all([user, project])
    await session.commit()

    session.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))

    db_conn = Connection(
        project_id=project.id,
        name=DB_CONNECTION_NAME,
        source_type="database",
        db_type="postgres",
        db_host="127.0.0.1",
        db_port=5432,
        db_name="app",
    )
    # Exactly the shape T2 made possible: no engine, no port, no database.
    ga_conn = Connection(
        project_id=project.id,
        name=GA4_CONNECTION_NAME,
        source_type="ga4",
        db_type=None,
        db_port=None,
        db_name=None,
    )
    session.add_all([db_conn, ga_conn])
    await session.commit()

    db_note = SavedNote(
        project_id=project.id,
        user_id=user.id,
        connection_id=db_conn.id,
        title="db note",
        sql_query="SELECT 1",
    )
    ga_note = SavedNote(
        project_id=project.id,
        user_id=user.id,
        connection_id=ga_conn.id,
        title="ga note",
        sql_query="SELECT 1",
    )
    db_schedule = ScheduledQuery(
        user_id=user.id,
        project_id=project.id,
        connection_id=db_conn.id,
        title="db schedule",
        sql_query="SELECT 1",
        cron_expression="0 0 * * *",
    )
    ga_schedule = ScheduledQuery(
        user_id=user.id,
        project_id=project.id,
        connection_id=ga_conn.id,
        title="ga schedule",
        sql_query="SELECT 1",
        cron_expression="0 0 * * *",
    )
    session.add_all([db_note, ga_note, db_schedule, ga_schedule])
    await session.commit()

    was_enabled = limiter.enabled
    limiter.enabled = False
    # raise_app_exceptions=False so an unguarded crash surfaces as a 500
    # response we can assert against instead of blowing up the test itself.
    transport = ASGITransport(app=_build_app(session, user), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield Env(
            client=client,
            session=session,
            user=user,
            project=project,
            db_conn=db_conn,
            ga_conn=ga_conn,
            db_note=db_note,
            ga_note=ga_note,
            db_schedule=db_schedule,
            ga_schedule=ga_schedule,
        )
    limiter.enabled = was_enabled
    await session.close()
    await engine.dispose()


def _fake_connector() -> AsyncMock:
    connector = AsyncMock()
    connector.connect = AsyncMock()
    connector.disconnect = AsyncMock()
    connector.test_connection = AsyncMock(return_value=True)
    connector.execute_query = AsyncMock(
        return_value=QueryResult(columns=["n"], rows=[[1]], row_count=1)
    )
    connector.introspect_schema = AsyncMock(
        return_value=SimpleNamespace(tables=[SimpleNamespace(name="orders")])
    )
    return connector


@pytest.fixture
def working_database_stack():
    """Patch out the real connector + credential decryption for the DB path."""
    connector = _fake_connector()
    with (
        patch.object(
            ConnectionService,
            "to_config",
            new_callable=AsyncMock,
            return_value=ConnectionConfig(db_type="postgres"),
        ),
        patch("app.connectors.registry.get_connector", return_value=connector),
        patch("app.api.routes.health_monitor.get_connector", return_value=connector),
    ):
        yield connector


def _assert_honest_400(resp, *, connection_name: str) -> None:
    assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text}"
    detail = resp.json()["detail"]
    assert connection_name in detail, detail
    assert "database connection" in detail, detail
    assert "Google Analytics" in detail, detail
    assert "Traceback" not in resp.text


# ---------------------------------------------------------------------------
# Routes — analytics source is refused with a clear 400
# ---------------------------------------------------------------------------


class TestRoutesRejectAnalyticsSources:
    async def test_note_execute_returns_400(self, env: Env):
        resp = await env.client.post(f"/api/notes/{env.ga_note.id}/execute")
        _assert_honest_400(resp, connection_name=GA4_CONNECTION_NAME)

    async def test_schedule_run_now_returns_400(self, env: Env):
        resp = await env.client.post(f"/api/schedules/{env.ga_schedule.id}/run-now")
        _assert_honest_400(resp, connection_name=GA4_CONNECTION_NAME)

    async def test_reconnect_returns_400(self, env: Env):
        resp = await env.client.post(f"/api/connections/{env.ga_conn.id}/reconnect")
        _assert_honest_400(resp, connection_name=GA4_CONNECTION_NAME)

    async def test_validate_learnings_schema_returns_400(self, env: Env):
        resp = await env.client.post(f"/api/connections/{env.ga_conn.id}/learnings/validate-schema")
        _assert_honest_400(resp, connection_name=GA4_CONNECTION_NAME)


# ---------------------------------------------------------------------------
# Routes — regression: a real database connection is untouched
# ---------------------------------------------------------------------------


class TestRoutesStillWorkForDatabaseConnections:
    async def test_note_execute_still_runs(self, env: Env, working_database_stack):
        resp = await env.client.post(f"/api/notes/{env.db_note.id}/execute")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["error"] is None
        assert json.loads(body["last_result_json"])["columns"] == ["n"]
        working_database_stack.execute_query.assert_awaited()

    async def test_schedule_run_now_still_runs(self, env: Env, working_database_stack):
        resp = await env.client.post(f"/api/schedules/{env.db_schedule.id}/run-now")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "success"
        assert json.loads(body["result_summary"])["columns"] == ["n"]

    async def test_reconnect_still_runs(self, env: Env, working_database_stack):
        resp = await env.client.post(f"/api/connections/{env.db_conn.id}/reconnect")
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True

    async def test_validate_learnings_schema_still_runs(self, env: Env, working_database_stack):
        resp = await env.client.post(f"/api/connections/{env.db_conn.id}/learnings/validate-schema")
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True
        working_database_stack.introspect_schema.assert_awaited()


# ---------------------------------------------------------------------------
# BatchService — fails the batch honestly instead of crashing
# ---------------------------------------------------------------------------


class TestBatchServiceRejectsAnalyticsSources:
    @staticmethod
    def _patch_session_factory(session: AsyncSession):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _factory():
            yield session

        return patch("app.services.batch_service.async_session_factory", _factory)

    async def test_batch_on_analytics_connection_fails_honestly(self, env: Env):
        svc = BatchService()
        with (
            self._patch_session_factory(env.session),
            patch("app.services.batch_service.tracker") as tracker,
        ):
            tracker.begin = AsyncMock(return_value="wf-1")
            tracker.emit = AsyncMock()
            tracker.end = AsyncMock()
            batch = await svc.create_batch(
                env.session,
                env.user.id,
                env.project.id,
                env.ga_conn.id,
                "GA batch",
                [{"sql": "SELECT 1", "title": "Q1"}],
            )
            await svc.execute_batch(batch.id, env.ga_conn.id, parallel=False)

        await env.session.refresh(batch)
        assert batch.status == "failed"
        assert batch.completed_at is not None
        results = json.loads(batch.results_json)
        assert GA4_CONNECTION_NAME in results[0]["error"]
        assert "Google Analytics" in results[0]["error"]

    async def test_batch_on_database_connection_still_runs(self, env: Env, working_database_stack):
        svc = BatchService()
        with (
            self._patch_session_factory(env.session),
            patch("app.services.batch_service.tracker") as tracker,
            patch(
                "app.services.batch_service.get_connector",
                return_value=working_database_stack,
            ),
        ):
            tracker.begin = AsyncMock(return_value="wf-1")
            tracker.emit = AsyncMock()
            tracker.end = AsyncMock()
            batch = await svc.create_batch(
                env.session,
                env.user.id,
                env.project.id,
                env.db_conn.id,
                "DB batch",
                [{"sql": "SELECT 1", "title": "Q1"}],
            )
            await svc.execute_batch(batch.id, env.db_conn.id, parallel=False)

        await env.session.refresh(batch)
        assert batch.status == "completed", batch.results_json
        results = json.loads(batch.results_json)
        assert results[0]["status"] == "success"
        assert results[0]["columns"] == ["n"]
