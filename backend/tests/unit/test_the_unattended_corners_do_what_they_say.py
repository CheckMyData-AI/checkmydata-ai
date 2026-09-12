"""Five promises the product makes on a schedule and does not keep.

P2 row 16; COR-01, COR-02, COR-03, COR-07 and BILL-09. Each is a feature that
exists, is sold, and quietly does something other than what its own interface says.

**COR-01 — "Every day at 9 AM" means 9 AM UTC.** Every cron evaluation in
`SchedulerService` runs against `datetime.now(UTC)`, while the creation UI offers
presets labelled in bare wall-clock time and renders stored crons back as "Daily at
9:00" with no qualifier. The product's *other* two schedulers deliberately share
`daily_knowledge_sync_timezone` "so both agree what 3 a.m. means" — user-facing
scheduled queries are the one scheduler that ignores it. A user in UTC+3 gets their
morning revenue check at noon, every day, silently.

**COR-02 — `notification_channels` is accepted, validated, stored, returned, and
read by nothing.** When an alert fires, the only artifact is a `Notification` row
behind the bell icon. An alerting feature that can only alert people already looking
at the product delivers nothing the schedule list did not already show — and two code
comments assert a mail delivery that does not exist.

**COR-03 — alerts are evaluated against a truncated head built for storage.** The
loop hands the evaluator `rows[:500]`; run-now re-truncates to 50 *before* evaluating
whenever the summary exceeds 1 MB. So the same query alerts differently depending on
how wide its rows are, and `pct_change` — defined as "compare the latest two
periods" — compares rows 499↔500 of the head once a daily series passes ~17 months.
The run is then recorded `success`.

**COR-07 — nothing prunes notifications or run history, and the loop's payload is
uncapped** where the identical run-now path bounds it at 1 MB. The maintenance cron
prunes three other journals in the same function, so retention was considered and
these two were missed.

**BILL-09 — seats are priced, published on the pricing page, carried through
entitlements, and compared to nothing.** Nine references: one column, one API
projection, one dataclass field, four catalogue literals. Zero comparisons. A `base`
customer paying for five seats can accept two hundred members.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from datetime import UTC, datetime

import pytest


class TestASchedulesClockIsTheUsers:
    """COR-01."""

    def test_the_cron_is_evaluated_in_the_configured_timezone(self) -> None:
        from app.config import settings
        from app.services.scheduler_service import SchedulerService

        # 2026-03-01 00:30 UTC. With the product's configured timezone ahead of UTC,
        # "every day at 09:00" is still ahead on the same calendar day; in UTC it is
        # 09:00 UTC, which is a different instant.
        base = datetime(2026, 3, 1, 0, 30, tzinfo=UTC)
        nxt = SchedulerService.compute_next_run("0 9 * * *", base)

        import zoneinfo

        tz = zoneinfo.ZoneInfo(settings.daily_knowledge_sync_timezone)
        local = nxt.astimezone(tz)
        assert (local.hour, local.minute) == (9, 0), (
            "the schedule fires at 09:00 UTC, and the UI that created it said "
            f"'Every day at 9 AM' with no qualifier — it lands at {local:%H:%M} for the "
            "user. The daily-sync and analytics crons already share "
            "`daily_knowledge_sync_timezone` so they agree what 3 a.m. means; this is "
            "the one scheduler that ignored it (COR-01)"
        )

    def test_the_stored_instant_is_still_utc(self) -> None:
        """The clock changes; the storage contract does not."""
        from app.services.scheduler_service import SchedulerService

        nxt = SchedulerService.compute_next_run("0 9 * * *", datetime(2026, 3, 1, tzinfo=UTC))
        assert nxt.tzinfo is not None and nxt.utcoffset() == UTC.utcoffset(None)


class TestAnAlertReachesSomebody:
    """COR-02."""

    def test_the_channels_field_has_a_reader(self) -> None:
        import pathlib

        root = pathlib.Path(__file__).parents[1].parent / "app"
        readers = [
            str(p.relative_to(root))
            for p in root.rglob("*.py")
            if "notification_channels" in p.read_text(encoding="utf-8")
            and p.name not in {"scheduled_query.py", "schedules.py", "scheduler_service.py"}
        ]
        assert readers, (
            "`notification_channels` is accepted by the route, validated at 5000 "
            "characters, stored on the model and returned — and no consumer exists. "
            "The knob is reachable only through the raw API, where it silently does "
            "nothing, while two code comments assert the alert is mailed (COR-02)"
        )

    @pytest.mark.asyncio
    async def test_an_email_channel_only_reaches_a_project_member(self) -> None:
        """A field that mails anybody is a spam relay, not an alerting feature."""
        from app.services.alert_delivery import resolve_email_recipients

        allowed = {"owner@example.com", "teammate@example.com"}
        assert resolve_email_recipients(
            json.dumps(["email:teammate@example.com", "email:stranger@elsewhere.test"]),
            member_emails=allowed,
        ) == ["teammate@example.com"]

    def test_an_unknown_channel_is_refused_not_ignored(self) -> None:
        from app.services.alert_delivery import validate_channels

        with pytest.raises(ValueError):
            validate_channels(json.dumps(["carrier-pigeon:bob"]))
        validate_channels(json.dumps(["email:a@b.c", "in_app"]))


class TestAnAlertSeesTheWholeResult:
    """COR-03."""

    def test_the_evaluator_is_not_handed_the_storage_head(self) -> None:
        from app.api.routes import schedules as sched_mod

        source = textwrap.dedent(inspect.getsource(sched_mod.run_now))
        tree = ast.parse(source.replace("async def", "def", 1))
        evaluate = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and "AlertEvaluator.evaluate" in ast.unparse(node.func)
        )
        handed = ast.unparse(evaluate.args[0])
        assert handed != "serialized_rows", (
            "run-now truncates to 50 rows for STORAGE and then evaluates the alert on "
            "those 50, so the same query alerts differently depending on how wide its "
            "rows are — and `pct_change`, defined as 'compare the latest two periods', "
            "compares rows 49 and 50 of a head (COR-03)"
        )

    def test_pct_change_reads_the_real_last_two_rows(self) -> None:
        from app.core.alert_evaluator import AlertEvaluator

        # A series long enough that any storage cap would cut it.
        rows = [[f"2026-01-{i:02d}", 100] for i in range(1, 29)] + [
            ["2026-02-01", 100],
            ["2026-02-02", 130],
        ]
        alerts = AlertEvaluator.evaluate(
            rows,
            ["day", "revenue"],
            json.dumps([{"column": "revenue", "operator": "pct_change", "threshold": 20}]),
        )
        assert alerts, "the premise is wrong: a 30% jump in the last two rows did not fire"


class TestTheUnattendedTablesAreBounded:
    """COR-07."""

    def test_the_loop_caps_its_payload_like_run_now_does(self) -> None:
        from app import main

        source = inspect.getsource(main._scheduler_loop)
        assert "MAX_RESULT_BYTES" in source or "max_result_bytes" in source, (
            "the loop stores 500 serialized rows with no byte bound into TWO places — "
            "`schedule_runs.result_summary` and `scheduled_queries.last_result_json` — "
            "while the identical run-now path bounds the same payload at 1 MB, so the "
            "bound plainly reflects intent (COR-07)"
        )

    def test_maintenance_prunes_notifications_and_runs(self) -> None:
        from app import main

        source = inspect.getsource(main._maintenance_loop)
        assert "_prune_unattended_history" in source, (
            "every alert writes a Notification per triggered condition per run and "
            "every run writes a ScheduleRun; neither table has a TTL, a prune, or even "
            "a delete endpoint. The maintenance cron prunes three other journals in "
            "the same function, so retention was considered and these two were missed "
            "(COR-07)"
        )

    def test_the_retention_horizon_is_configurable(self) -> None:
        from app.config import Settings

        assert Settings().unattended_history_retention_days > 0


class TestSeatsAreCompared:
    """BILL-09."""

    @pytest.mark.asyncio
    async def test_adding_a_member_over_the_seat_cap_is_refused(self) -> None:
        """A member added against a real cap, not the word "seat" in the source.

        The first draft asserted that `MembershipService`'s source mentions seats.
        Renaming the method to `_unused_seat_check` and deleting its call satisfied
        that while enforcing nothing — the fifth presence check this programme has
        watched pass against its own defect.
        """
        import uuid

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app import entitlements as ent_mod
        from app.entitlements import QuotaExceededError
        from app.models.base import Base
        from app.models.project import Project
        from app.models.project_member import ProjectMember
        from app.models.user import User
        from app.services.membership_service import MembershipService

        class _TwoSeats:
            async def get_entitlements(self, db, user_id):  # noqa: ARG002
                return type("E", (), {"seats": 2})()

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        project_id = uuid.uuid4().hex
        ids = [uuid.uuid4().hex for _ in range(3)]
        async with sm() as session:
            session.add(Project(id=project_id, name="p"))
            for i, uid in enumerate(ids):
                session.add(User(id=uid, email=f"u{i}@example.com", password_hash="x"))
            session.add(ProjectMember(project_id=project_id, user_id=ids[0], role="owner"))
            await session.commit()

            ent_mod.set_entitlements(_TwoSeats())
            try:
                svc = MembershipService()
                await svc.add_member(session, project_id, ids[1], "viewer")
                with pytest.raises(QuotaExceededError):
                    await svc.add_member(session, project_id, ids[2], "viewer")

                # A role change on an existing member is not a new seat.
                await svc.add_member(session, project_id, ids[1], "editor")
            finally:
                ent_mod.reset_entitlements()
        await engine.dispose()
