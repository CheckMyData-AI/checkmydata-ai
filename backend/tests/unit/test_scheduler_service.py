"""Unit tests for SchedulerService."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.chat_session  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.saved_note  # noqa: F401
import app.models.scheduled_query  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.connection import Connection
from app.models.project import Project
from app.models.user import User
from app.services.scheduler_service import SchedulerService

svc = SchedulerService()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_user(db: AsyncSession) -> User:
    u = User(email=f"user-{uuid.uuid4().hex[:6]}@test.com", password_hash="fake", display_name="T")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_project(db: AsyncSession) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _make_connection(db: AsyncSession, project_id: str) -> Connection:
    c = Connection(
        project_id=project_id,
        name="test-conn",
        db_type="postgresql",
        db_host="localhost",
        db_port=5432,
        db_name="test",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


class TestCreateSchedule:
    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        schedule = await svc.create_schedule(
            db,
            user_id=user.id,
            project_id=proj.id,
            connection_id=conn.id,
            title="Hourly Check",
            sql_query="SELECT count(*) FROM orders",
            cron_expression="0 * * * *",
        )
        assert schedule.id is not None
        assert schedule.title == "Hourly Check"
        assert schedule.is_active is True
        assert schedule.next_run_at is not None

    @pytest.mark.asyncio
    async def test_create_with_alert_conditions(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        conditions = json.dumps([{"column": "cnt", "operator": "gt", "threshold": 100}])
        schedule = await svc.create_schedule(
            db,
            user_id=user.id,
            project_id=proj.id,
            connection_id=conn.id,
            title="Alert Check",
            sql_query="SELECT count(*) as cnt FROM errors",
            cron_expression="0 9 * * *",
            alert_conditions=conditions,
        )
        assert schedule.alert_conditions == conditions


class TestGetSchedule:
    @pytest.mark.asyncio
    async def test_get_existing(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        created = await svc.create_schedule(
            db,
            user_id=user.id,
            project_id=proj.id,
            connection_id=conn.id,
            title="X",
            sql_query="SELECT 1",
            cron_expression="0 * * * *",
        )
        fetched = await svc.get_schedule(db, created.id)
        assert fetched is not None
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db):
        assert await svc.get_schedule(db, "no-id") is None


class TestListSchedules:
    @pytest.mark.asyncio
    async def test_list_filters_by_project(self, db):
        user = await _make_user(db)
        p1 = await _make_project(db)
        p2 = await _make_project(db)
        c1 = await _make_connection(db, p1.id)
        c2 = await _make_connection(db, p2.id)

        await svc.create_schedule(
            db, user_id=user.id, project_id=p1.id, connection_id=c1.id,
            title="P1", sql_query="SELECT 1", cron_expression="0 * * * *",
        )
        await svc.create_schedule(
            db, user_id=user.id, project_id=p2.id, connection_id=c2.id,
            title="P2", sql_query="SELECT 2", cron_expression="0 * * * *",
        )

        items = await svc.list_schedules(db, p1.id)
        assert len(items) == 1
        assert items[0].title == "P1"


class TestUpdateSchedule:
    @pytest.mark.asyncio
    async def test_update_title(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        s = await svc.create_schedule(
            db, user_id=user.id, project_id=proj.id, connection_id=conn.id,
            title="Old", sql_query="SELECT 1", cron_expression="0 * * * *",
        )
        updated = await svc.update_schedule(db, s.id, title="New")
        assert updated is not None
        assert updated.title == "New"

    @pytest.mark.asyncio
    async def test_update_cron_recalculates_next_run(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        s = await svc.create_schedule(
            db, user_id=user.id, project_id=proj.id, connection_id=conn.id,
            title="X", sql_query="SELECT 1", cron_expression="0 * * * *",
        )
        old_next = s.next_run_at
        updated = await svc.update_schedule(db, s.id, cron_expression="0 9 * * 1")
        assert updated is not None
        assert updated.next_run_at != old_next

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, db):
        assert await svc.update_schedule(db, "bad", title="X") is None


class TestDeleteSchedule:
    @pytest.mark.asyncio
    async def test_delete_existing(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        s = await svc.create_schedule(
            db, user_id=user.id, project_id=proj.id, connection_id=conn.id,
            title="X", sql_query="SELECT 1", cron_expression="0 * * * *",
        )
        assert await svc.delete_schedule(db, s.id) is True
        assert await svc.get_schedule(db, s.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db):
        assert await svc.delete_schedule(db, "bad") is False


class TestGetDueSchedules:
    @pytest.mark.asyncio
    async def test_returns_due_schedules(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        s = await svc.create_schedule(
            db, user_id=user.id, project_id=proj.id, connection_id=conn.id,
            title="Due", sql_query="SELECT 1", cron_expression="0 * * * *",
        )
        s.next_run_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.commit()

        due = await svc.get_due_schedules(db)
        assert len(due) >= 1
        assert any(d.id == s.id for d in due)

    @pytest.mark.asyncio
    async def test_excludes_inactive(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        s = await svc.create_schedule(
            db, user_id=user.id, project_id=proj.id, connection_id=conn.id,
            title="Inactive", sql_query="SELECT 1", cron_expression="0 * * * *",
        )
        s.is_active = False
        s.next_run_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.commit()

        due = await svc.get_due_schedules(db)
        assert not any(d.id == s.id for d in due)


class TestRecordRun:
    @pytest.mark.asyncio
    async def test_record_success(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        s = await svc.create_schedule(
            db, user_id=user.id, project_id=proj.id, connection_id=conn.id,
            title="X", sql_query="SELECT 1", cron_expression="0 * * * *",
        )
        run = await svc.record_run(
            db, s.id, status="success",
            result_summary='{"rows":[]}',
            duration_ms=150,
        )
        assert run.status == "success"
        assert run.duration_ms == 150

        refreshed = await svc.get_schedule(db, s.id)
        assert refreshed is not None
        assert refreshed.last_run_at is not None

    @pytest.mark.asyncio
    async def test_run_history(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        s = await svc.create_schedule(
            db, user_id=user.id, project_id=proj.id, connection_id=conn.id,
            title="X", sql_query="SELECT 1", cron_expression="0 * * * *",
        )
        await svc.record_run(db, s.id, status="success", duration_ms=100)
        await svc.record_run(db, s.id, status="failed", duration_ms=50)

        history = await svc.get_run_history(db, s.id)
        assert len(history) == 2
        statuses = {r.status for r in history}
        assert statuses == {"success", "failed"}


class TestComputeNextRun:
    def test_hourly(self):
        base = datetime(2026, 3, 21, 10, 30, 0, tzinfo=UTC)
        nxt = SchedulerService.compute_next_run("0 * * * *", base)
        assert nxt.hour == 11
        assert nxt.minute == 0

    def test_daily_at_9(self):
        base = datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC)
        nxt = SchedulerService.compute_next_run("0 9 * * *", base)
        assert nxt.day == 22
        assert nxt.hour == 9

    def test_validate_valid(self):
        assert SchedulerService.validate_cron("0 * * * *") is True

    def test_validate_invalid(self):
        assert SchedulerService.validate_cron("not a cron") is False
