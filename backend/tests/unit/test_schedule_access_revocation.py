"""F-SCHED-01: a schedule must stop when its creator loses access to the project.

The scheduler loop takes every due schedule and runs it with no membership check, so a
schedule created by somebody since removed from the project keeps querying that
project's database on a cron. Unlike the WebSocket case (F-CHAT-01), nobody is at the
keyboard: it runs forever.

And it is not only wasted compute. The loop evaluates alert conditions and writes
``Notification(user_id=schedule.user_id, body=alert["message"])`` — the alert body
carries values from the query — so a removed member **keeps receiving the project's
data**. That is an ongoing exposure, which is why the Medium label understates it.

The schedule is **paused, not deleted**: `is_active=False` already excludes it from
`get_due_schedules`, the state is recoverable if the person is re-added, and deleting
somebody's work on an access change would be a second wrong. The reason is recorded in
the run history, because a schedule that simply stops looks like a bug.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.scheduled_query import ScheduledQuery
from app.models.user import User
from app.services.scheduler_service import SchedulerService


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _setup(session: AsyncSession, *, creator_is_member: bool):
    owner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:6]}@x.com")
    creator = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:6]}@x.com")
    session.add_all([owner, creator])
    p = Project(id=str(uuid.uuid4()), name="P", owner_id=owner.id)
    session.add(p)
    if creator_is_member:
        session.add(ProjectMember(project_id=p.id, user_id=creator.id, role="editor"))
    sched = ScheduledQuery(
        id=str(uuid.uuid4()),
        user_id=creator.id,
        project_id=p.id,
        connection_id=str(uuid.uuid4()),
        title="nightly revenue",
        sql_query="SELECT 1",
        cron_expression="0 3 * * *",
        is_active=True,
        next_run_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    session.add(sched)
    await session.commit()
    return p, creator, sched


class TestRevocation:
    async def test_a_revoked_creator_stops_the_schedule(self, session: AsyncSession):
        _p, _creator, sched = await _setup(session, creator_is_member=False)
        svc = SchedulerService()
        assert await svc.creator_still_has_access(session, sched) is False

    async def test_a_member_creator_keeps_running(self, session: AsyncSession):
        _p, _creator, sched = await _setup(session, creator_is_member=True)
        svc = SchedulerService()
        assert await svc.creator_still_has_access(session, sched) is True

    async def test_the_project_owner_keeps_running_without_a_member_row(
        self, session: AsyncSession
    ):
        """The owner is an owner whichever reader you ask (F-PROJ-02)."""
        owner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:6]}@x.com")
        session.add(owner)
        p = Project(id=str(uuid.uuid4()), name="P", owner_id=owner.id)
        session.add(p)
        sched = ScheduledQuery(
            id=str(uuid.uuid4()),
            user_id=owner.id,
            project_id=p.id,
            connection_id=str(uuid.uuid4()),
            title="t",
            sql_query="SELECT 1",
            cron_expression="0 3 * * *",
            is_active=True,
            next_run_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        session.add(sched)
        await session.commit()
        assert await SchedulerService().creator_still_has_access(session, sched) is True


class TestPausing:
    async def test_pausing_removes_it_from_the_due_set(self, session: AsyncSession):
        _p, _creator, sched = await _setup(session, creator_is_member=False)
        svc = SchedulerService()
        await svc.pause_for_revoked_access(session, sched)

        refreshed = (
            await session.execute(select(ScheduledQuery).where(ScheduledQuery.id == sched.id))
        ).scalar_one()
        assert refreshed.is_active is False
        assert sched.id not in {s.id for s in await svc.get_due_schedules(session)}

    async def test_pausing_is_recorded_not_silent(self, session: AsyncSession):
        """A schedule that just stops looks like a bug; the owner is owed the reason."""
        from app.models.scheduled_query import ScheduleRun

        _p, _creator, sched = await _setup(session, creator_is_member=False)
        await SchedulerService().pause_for_revoked_access(session, sched)

        runs = (
            (await session.execute(select(ScheduleRun).where(ScheduleRun.schedule_id == sched.id)))
            .scalars()
            .all()
        )
        assert len(runs) == 1
        assert "access" in (runs[0].result_summary or "").lower()

    async def test_the_schedule_is_not_deleted(self, session: AsyncSession):
        """Recoverable: re-adding the person lets an owner resume it."""
        _p, _creator, sched = await _setup(session, creator_is_member=False)
        await SchedulerService().pause_for_revoked_access(session, sched)
        assert await SchedulerService().get_schedule(session, sched.id) is not None


class TestTheLoopActuallyUsesIt:
    """A method nobody calls is not a fix.

    The service can now answer the question and pause the schedule, but the exposure
    only closes if the scheduler loop asks — and asks BEFORE running the query, since
    running it is what reaches the project's database.
    """

    def test_the_scheduler_loop_checks_before_executing(self):
        import inspect

        from app import main

        src = inspect.getsource(main._scheduler_loop)
        assert "creator_still_has_access" in src, (
            "the loop still runs every due schedule without asking whether its creator "
            "may still reach the project"
        )
        assert "pause_for_revoked_access" in src

        # Order matters: the check has to precede the connector work, or the query has
        # already run by the time we decline.
        check_at = src.index("creator_still_has_access")
        run_at = src.index("get_connector")
        assert check_at < run_at, "access is checked after the query has already run"
