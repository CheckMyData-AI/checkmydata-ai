"""A-04: a GA4 day ends in the PROPERTY's timezone, not in the scheduler's.

GA4 evaluates a `date` dimension in the property's own zone. The collector's window
ended "yesterday" on the scheduler's clock (`daily_knowledge_sync_timezone`,
`Europe/Berlin` in production), so a property in Los Angeles had its 03:00 Berlin
collection read a day that still had six hours to run — and the journal recorded `ok`,
a **done** status, so those partial numbers were never collected again and the agent
published them as a measurement of a finished day.

Two halves, and both are needed. The zone is now a connection knob, validated where it
is parsed rather than where it is used; and a connection that does not carry one is not
guessed at — the newest period of its run is journalled `partial`, which keeps the rows
and keeps the period owed.

The last class covers the other half of "this period is not final": the **refetch tail**.
Those periods are re-fetched on every run precisely because the vendor revises them, so a
number quoted from one may change tomorrow. They stay a done status — the tail refetches
them regardless of status, and marking them owed would leave every connection permanently
`partial` — and say so in the note the agent repeats when it quotes the period.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every mapper
from app.analytics.base import AnalyticsReport, AnalyticsSourceAdapter, ReportSpec
from app.analytics.errors import AnalyticsError
from app.analytics.ga4.config import GA4Config
from app.analytics.ga4.reports import REPORTS_BY_NAME
from app.connectors.base import ConnectionConfig
from app.models.analytics_import import AnalyticsImport
from app.models.base import Base, enable_sqlite_fk
from app.models.connection import Connection
from app.models.project import Project
from app.services.analytics_collect_service import AnalyticsCollectService

PROPERTY_ID = "294380179"
TODAY = dt.date(2026, 7, 16)
YESTERDAY = dt.date(2026, 7, 15)
BACKFILL_DAYS = 3
REPORT = "overview"

#: 25 hours apart, so their local dates differ at every instant — no clock to freeze.
EAST = "Pacific/Kiritimati"  # UTC+14
WEST = "Pacific/Niue"  # UTC-11


# ---------------------------------------------------------------------------
# The knob
# ---------------------------------------------------------------------------


class TestTheZoneIsAKnob:
    def test_a_property_timezone_is_read_and_kept(self):
        config = GA4Config.from_mapping(
            {"property_ids": [PROPERTY_ID], "property_timezone": "America/Los_Angeles"}
        )

        assert config.property_timezone == "America/Los_Angeles"

    def test_an_absent_zone_is_none_rather_than_a_default(self):
        """A default would be a guess wearing a configuration's clothes."""
        config = GA4Config.from_mapping({"property_ids": [PROPERTY_ID]})

        assert config.property_timezone is None

    def test_a_zone_nobody_can_resolve_is_refused_where_it_is_written(self):
        with pytest.raises(AnalyticsError, match="not an IANA timezone"):
            GA4Config.from_mapping({"property_ids": [PROPERTY_ID], "property_timezone": "PST"})

    def test_an_offset_is_not_a_zone(self):
        """`UTC+2` names no place, so it cannot say when a day ends there."""
        with pytest.raises(AnalyticsError, match="not an IANA timezone"):
            GA4Config.from_mapping({"property_ids": [PROPERTY_ID], "property_timezone": "UTC+2"})


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def _conn(zone: str | None) -> Connection:
    config: dict[str, Any] = {"property_ids": [PROPERTY_ID], "backfill_days": BACKFILL_DAYS}
    if zone is not None:
        config["property_timezone"] = zone
    return Connection(
        id=uuid.uuid4().hex,
        project_id="p",
        name="ga4",
        source_type="ga4",
        source_config_json=json.dumps(config),
    )


class TestTodayIsTheProperties:
    def test_two_properties_a_day_apart_get_different_todays(self):
        """The real clock, deliberately: 25 hours of offset cannot collapse.

        Nor is it always one day. 25 hours is one calendar day for 23 hours of every UTC
        day and TWO for the hour 10:00-10:59 UTC, when Niue's 23:xx is Kiritimati's
        day-after-tomorrow. Asserting exactly one day failed CI every day in that hour
        (found 2026-09-23 on PR #407, 10:27 UTC: 09-24 vs 09-22). The defect this guards
        against — one clock for every property — gives zero, and zero is still refused.
        """
        service = AnalyticsCollectService(adapter_factory=lambda conn: FakeAdapter())

        east, east_known = service._today_for(_conn(EAST))
        west, west_known = service._today_for(_conn(WEST))

        assert east_known and west_known
        assert dt.timedelta(days=1) <= east - west <= dt.timedelta(days=2), (
            "the window was computed on one clock for every property on earth"
        )

    def test_no_zone_means_the_answer_is_not_trusted(self):
        service = AnalyticsCollectService(adapter_factory=lambda conn: FakeAdapter())

        _, known = service._today_for(_conn(None))

        assert known is False

    def test_an_unusable_zone_degrades_to_the_schedulers_clock_and_says_so(self):
        """A stored row can predate the validation above; it must not take the run down."""
        service = AnalyticsCollectService(
            adapter_factory=lambda conn: FakeAdapter(), today=lambda: TODAY
        )

        day, known = service._today_for(_conn("Middle/Earth"))

        assert (day, known) == (TODAY, False)


# ---------------------------------------------------------------------------
# The fake vendor — one report, one row a period
# ---------------------------------------------------------------------------


class FakeAdapter(AnalyticsSourceAdapter):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    @property
    def source_type(self) -> str:
        return "ga4"

    async def connect(self, config: ConnectionConfig) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def test_connection(self) -> bool:
        return True

    def available_reports(self) -> list[ReportSpec]:
        return [REPORTS_BY_NAME[REPORT].to_spec()]

    async def fetch(self, report: str, period: str) -> AnalyticsReport:
        self.calls.append((report, period))
        spec = REPORTS_BY_NAME[report]
        row: list[Any] = [PROPERTY_ID]
        for field in spec.fields:
            if field.kind == "date":
                row.append(dt.date.fromisoformat(period))
            elif field.kind == "str":
                row.append("v")
            elif field.kind == "int":
                row.append(7)
            else:
                row.append(Decimal("12.3400"))
        return AnalyticsReport(columns=spec.columns, rows=[row])


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_fk(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        yield session
    await engine.dispose()


async def _connection(db: AsyncSession, zone: str | None) -> str:
    project = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.commit()
    conn = _conn(zone)
    conn.id = None  # let the model mint its own
    conn.project_id = project.id
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn.id


async def _journal(db: AsyncSession) -> dict[str, AnalyticsImport]:
    rows = (
        (await db.execute(select(AnalyticsImport).where(AnalyticsImport.report == REPORT)))
        .scalars()
        .all()
    )
    return {row.period: row for row in rows}


def _service(adapter: FakeAdapter) -> AnalyticsCollectService:
    return AnalyticsCollectService(
        adapter_factory=lambda conn: adapter, today=lambda: TODAY, refetch_tail_periods=0
    )


# ---------------------------------------------------------------------------
# The verdict on the newest period
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTheNewestPeriodOfAnUntimedConnection:
    async def test_it_is_partial_and_the_older_ones_are_not(self, db: AsyncSession):
        connection_id = await _connection(db, None)

        await _service(FakeAdapter()).collect_in_session(db, connection_id)

        rows = await _journal(db)
        assert rows[YESTERDAY.isoformat()].status == "partial", (
            "yesterday on the scheduler's clock may still be today at the property"
        )
        older = [period for period in rows if period != YESTERDAY.isoformat()]
        assert older, "the run collected nothing but the newest period"
        assert {rows[period].status for period in older} == {"ok"}

    async def test_its_rows_are_kept(self, db: AsyncSession):
        """`partial` withholds the verdict, never the data."""
        connection_id = await _connection(db, None)

        outcome = await _service(FakeAdapter()).collect_in_session(db, connection_id)

        assert outcome.rows_written == BACKFILL_DAYS
        assert (await _journal(db))[YESTERDAY.isoformat()].rows_written == 1

    async def test_it_names_the_missing_knob_rather_than_blaming_the_vendor(self, db: AsyncSession):
        connection_id = await _connection(db, None)

        await _service(FakeAdapter()).collect_in_session(db, connection_id)

        note = (await _journal(db))[YESTERDAY.isoformat()].error or ""
        assert "property_timezone" in note
        assert "collected again" in note

    async def test_it_is_fetched_again_on_the_next_run(self, db: AsyncSession):
        """`partial` is not done, so the period stays owed with no refetch tail at all."""
        connection_id = await _connection(db, None)
        await _service(FakeAdapter()).collect_in_session(db, connection_id)

        second = FakeAdapter()
        await _service(second).collect_in_session(db, connection_id)

        assert second.calls == [(REPORT, YESTERDAY.isoformat())]

    async def test_a_known_zone_seals_the_period_as_done(self, db: AsyncSession):
        connection_id = await _connection(db, "Europe/Berlin")

        await _service(FakeAdapter()).collect_in_session(db, connection_id)

        rows = await _journal(db)
        assert {row.status for row in rows.values()} == {"ok"}
        assert rows[YESTERDAY.isoformat()].error is None

        second = FakeAdapter()
        await _service(second).collect_in_session(db, connection_id)
        assert second.calls == [], "a sealed period must not be re-fetched"


def _service_with_tail(adapter: FakeAdapter, tail: int) -> AnalyticsCollectService:
    return AnalyticsCollectService(
        adapter_factory=lambda conn: adapter, today=lambda: TODAY, refetch_tail_periods=tail
    )


@pytest.mark.asyncio
class TestTheRefetchTailSaysItIsStillSettling:
    async def test_the_tail_periods_carry_the_caveat_and_the_older_ones_do_not(
        self, db: AsyncSession
    ):
        connection_id = await _connection(db, "Europe/Berlin")

        await _service_with_tail(FakeAdapter(), 2).collect_in_session(db, connection_id)

        rows = await _journal(db)
        newest = sorted(rows)[-2:]
        for period in newest:
            assert rows[period].status == "ok", "the tail is collected in full; it is not owed"
            assert "revises" in (rows[period].error or ""), (
                "a number the vendor is still revising was quoted as settled"
            )
        for period in sorted(rows)[:-2]:
            assert rows[period].error is None

    async def test_no_tail_means_no_caveat(self, db: AsyncSession):
        """`analytics_refetch_tail_periods=0` refetches nothing, so nothing is unsettled."""
        connection_id = await _connection(db, "Europe/Berlin")

        await _service_with_tail(FakeAdapter(), 0).collect_in_session(db, connection_id)

        assert {row.error for row in (await _journal(db)).values()} == {None}

    async def test_the_missing_timezone_caveat_wins_on_the_newest_period(self, db: AsyncSession):
        """Both would apply; the one naming a fixable cause is the one worth printing."""
        connection_id = await _connection(db, None)

        await _service_with_tail(FakeAdapter(), 2).collect_in_session(db, connection_id)

        newest = (await _journal(db))[YESTERDAY.isoformat()]
        assert newest.status == "partial"
        assert "property_timezone" in (newest.error or "")
