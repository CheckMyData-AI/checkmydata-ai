import logging
from datetime import UTC, datetime

from croniter import croniter  # type: ignore[import-untyped]
from sqlalchemy import select
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
    ) -> list[ScheduledQuery]:
        result = await db.execute(
            select(ScheduledQuery)
            .where(ScheduledQuery.project_id == project_id)
            .order_by(ScheduledQuery.created_at.desc())
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

    async def get_due_schedules(self, db: AsyncSession) -> list[ScheduledQuery]:
        now = datetime.now(UTC)
        result = await db.execute(
            select(ScheduledQuery).where(
                ScheduledQuery.is_active == True,  # noqa: E712
                ScheduledQuery.next_run_at <= now,
            )
        )
        return list(result.scalars().all())

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
        limit: int = 50,
    ) -> list[ScheduleRun]:
        result = await db.execute(
            select(ScheduleRun)
            .where(ScheduleRun.schedule_id == schedule_id)
            .order_by(ScheduleRun.executed_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
