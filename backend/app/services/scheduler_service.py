import json
import logging
from datetime import UTC, datetime

from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scheduled_query import ScheduledQuery, ScheduleRun

logger = logging.getLogger(__name__)


class SchedulerService:
    @staticmethod
    def compute_next_run(cron_expression: str, base: datetime | None = None) -> datetime:
        base = base or datetime.now(UTC)
        cron = croniter(cron_expression, base)
        return cron.get_next(datetime).replace(tzinfo=UTC)

    @staticmethod
    def validate_cron(cron_expression: str) -> bool:
        return croniter.is_valid(cron_expression)

    async def create_schedule(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        project_id: str,
        connection_id: str,
        title: str,
        sql_query: str,
        cron_expression: str,
        alert_conditions: str | None = None,
        notification_channels: str | None = None,
    ) -> ScheduledQuery:
        next_run = self.compute_next_run(cron_expression)
        schedule = ScheduledQuery(
            user_id=user_id,
            project_id=project_id,
            connection_id=connection_id,
            title=title,
            sql_query=sql_query,
            cron_expression=cron_expression,
            alert_conditions=alert_conditions,
            notification_channels=notification_channels,
            next_run_at=next_run,
        )
        db.add(schedule)
        await db.commit()
        await db.refresh(schedule)
        return schedule

    async def get_schedule(self, db: AsyncSession, schedule_id: str) -> ScheduledQuery | None:
        result = await db.execute(select(ScheduledQuery).where(ScheduledQuery.id == schedule_id))
        return result.scalar_one_or_none()

    async def list_schedules(
        self,
        db: AsyncSession,
        project_id: str,
        skip: int = 0,
        limit: int = 50,
    ) -> list[ScheduledQuery]:
        result = await db.execute(
            select(ScheduledQuery)
            .where(ScheduledQuery.project_id == project_id)
            .order_by(ScheduledQuery.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_schedule(
        self,
        db: AsyncSession,
        schedule_id: str,
        **kwargs,
    ) -> ScheduledQuery | None:
        schedule = await self.get_schedule(db, schedule_id)
        if not schedule:
            return None

        updatable = {
            "title",
            "sql_query",
            "cron_expression",
            "alert_conditions",
            "notification_channels",
            "is_active",
        }
        for key, value in kwargs.items():
            if key in updatable:
                setattr(schedule, key, value)

        if "cron_expression" in kwargs:
            schedule.next_run_at = self.compute_next_run(kwargs["cron_expression"])

        if "is_active" in kwargs and kwargs["is_active"] and not schedule.next_run_at:
            schedule.next_run_at = self.compute_next_run(schedule.cron_expression)

        schedule.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(schedule)
        return schedule

    async def delete_schedule(self, db: AsyncSession, schedule_id: str) -> bool:
        schedule = await self.get_schedule(db, schedule_id)
        if not schedule:
            return False
        await db.delete(schedule)
        await db.commit()
        return True

    async def creator_still_has_access(self, db: AsyncSession, schedule: ScheduledQuery) -> bool:
        """Whether the person who created *schedule* may still reach its project.

        F-SCHED-01. The loop ran every due schedule with no membership check, so one
        created by somebody since removed kept querying that project's database on a
        cron — and unlike the WebSocket case, nobody is at the keyboard to notice. It
        is not only wasted compute: the loop evaluates alert conditions and writes
        ``Notification(user_id=schedule.user_id, body=alert["message"])``, and the alert
        body carries values from the query, so a removed member keeps receiving the
        project's data.

        Asks the membership service rather than re-deriving the rule — the fourth copy
        of that predicate was found in the chat WebSocket gate (F-CHAT-01).
        """
        from app.services.membership_service import MembershipService

        return await MembershipService().can_access(db, schedule.project_id, schedule.user_id)

    async def pause_for_revoked_access(self, db: AsyncSession, schedule: ScheduledQuery) -> None:
        """Deactivate *schedule* and say why in its run history.

        Paused, not deleted: ``is_active=False`` already excludes it from
        :meth:`get_due_schedules`, the state is recoverable if the person is re-added,
        and destroying somebody's work over an access change would be a second wrong.
        The reason is recorded because a schedule that simply stops looks like a bug —
        the owner reading the history is owed the cause.
        """
        schedule.is_active = False
        await db.commit()
        await self.record_run(
            db,
            schedule.id,
            status="failed",
            result_summary=json.dumps(
                {
                    "error": (
                        "Paused: the user who created this schedule no longer has access "
                        "to the project. Re-add them, or recreate the schedule under an "
                        "account that does, then re-enable it."
                    )
                }
            ),
        )
        logger.info(
            "Scheduler: paused schedule %s — creator %s lost access to project %s",
            schedule.id[:8],
            schedule.user_id[:8],
            schedule.project_id[:8],
        )

    async def get_due_schedules(self, db: AsyncSession) -> list[ScheduledQuery]:
        now = datetime.now(UTC)
        result = await db.execute(
            select(ScheduledQuery).where(
                ScheduledQuery.is_active == True,  # noqa: E712
                ScheduledQuery.next_run_at <= now,
            )
        )
        return list(result.scalars().all())

    async def claim_due(self, db: AsyncSession, schedule_id: str, cron_expression: str) -> bool:
        """Atomically claim a due schedule for execution (multi-dyno safe).

        Advances ``next_run_at`` to the next cron instant in a single
        conditional UPDATE. Returns ``True`` if this caller won the claim, or
        ``False`` if another dyno already advanced it (the row no longer matches
        the due predicate). This prevents duplicate execution — and duplicate
        alert notifications — when more than one web dyno runs the scheduler
        loop concurrently.
        """
        now = datetime.now(UTC)
        result = await db.execute(
            update(ScheduledQuery)
            .where(
                ScheduledQuery.id == schedule_id,
                ScheduledQuery.is_active == True,  # noqa: E712
                ScheduledQuery.next_run_at <= now,
            )
            .values(next_run_at=self.compute_next_run(cron_expression, base=now))
        )
        await db.commit()
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined]

    async def record_run(
        self,
        db: AsyncSession,
        schedule_id: str,
        *,
        status: str,
        result_summary: str | None = None,
        alerts_fired: str | None = None,
        duration_ms: int | None = None,
    ) -> ScheduleRun:
        run = ScheduleRun(
            schedule_id=schedule_id,
            status=status,
            result_summary=result_summary,
            alerts_fired=alerts_fired,
            duration_ms=duration_ms,
        )
        db.add(run)

        schedule = await self.get_schedule(db, schedule_id)
        if schedule:
            schedule.last_run_at = datetime.now(UTC)
            if result_summary:
                schedule.last_result_json = result_summary
            schedule.next_run_at = self.compute_next_run(schedule.cron_expression)

        await db.commit()
        await db.refresh(run)
        return run

    async def get_run_history(
        self,
        db: AsyncSession,
        schedule_id: str,
        skip: int = 0,
        limit: int = 50,
    ) -> list[ScheduleRun]:
        result = await db.execute(
            select(ScheduleRun)
            .where(ScheduleRun.schedule_id == schedule_id)
            .order_by(ScheduleRun.executed_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
