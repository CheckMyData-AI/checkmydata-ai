"""Tests for the analytics import journal (T5 — spec §2.5, REQ-005).

The invariant under test is the watermark rule: what is still pending is
``expected − done``, **never** "everything after ``max(period)``". Once later
days succeed, a failed day sits *below* the high-water mark, and a
high-water-mark implementation would skip it forever —
:meth:`TestPendingPeriods.test_failed_period_below_high_water_mark_refills`
exists precisely to fail that implementation. Every other test here passes
under both, which is why that one carries the weight.

``PRAGMA foreign_keys=ON`` is enabled via :func:`enable_sqlite_fk` so the
journal rows hang off a real connection instead of a dangling id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every mapper
from app.analytics import journal
from app.models.analytics_import import AnalyticsImport
from app.models.base import Base, enable_sqlite_fk
from app.models.connection import Connection
from app.models.project import Project

REPORT = "overview"
OTHER_REPORT = "geo"

# Five consecutive days. D3 is the hole: it fails while D4/D5 succeed, so it
# ends up *below* the high-water mark.
D1, D2, D3, D4, D5 = (
    "2026-07-11",
    "2026-07-12",
    "2026-07-13",
    "2026-07-14",
    "2026-07-15",
)
EXPECTED = [D1, D2, D3, D4, D5]


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


async def _connection(db: AsyncSession) -> str:
    """A GA4 connection to hang journal rows off (FKs are enforced here)."""
    proj = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(proj)
    await db.commit()
    conn = Connection(project_id=proj.id, name=f"ga4-{uuid.uuid4().hex[:6]}", source_type="ga4")
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn.id


@pytest_asyncio.fixture
async def conn_id(db: AsyncSession) -> str:
    return await _connection(db)


async def _rows(db: AsyncSession, connection_id: str | None = None) -> list[AnalyticsImport]:
    stmt = select(AnalyticsImport).order_by(AnalyticsImport.report, AnalyticsImport.period)
    if connection_id is not None:
        stmt = stmt.where(AnalyticsImport.connection_id == connection_id)
    return list((await db.execute(stmt)).scalars().all())


async def _count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(AnalyticsImport))).scalar_one())


async def _record_many(
    db: AsyncSession, connection_id: str, statuses: dict[str, str], *, report: str = REPORT
) -> None:
    for period, status in statuses.items():
        await journal.record(
            db,
            connection_id=connection_id,
            report=report,
            period=period,
            status=status,
            rows_written=1 if status == "ok" else 0,
            error="boom" if status == "failed" else None,
        )


async def _pending(
    db: AsyncSession,
    connection_id: str,
    *,
    expected: list[str] | None = None,
    tail: int = 0,
    report: str = REPORT,
) -> list[str]:
    return await journal.pending_periods(
        db,
        connection_id=connection_id,
        report=report,
        expected=EXPECTED if expected is None else expected,
        tail=tail,
    )


class TestPendingPeriods:
    async def test_failed_period_below_high_water_mark_refills(
        self, db: AsyncSession, conn_id: str
    ):
        """THE HOLE CASE — D3 failed, D4/D5 succeeded; D3 must still be pending.

        A ``max(period)``/high-water-mark implementation returns ``[]`` here
        because the newest successful period is D5. The journal contract is
        ``expected − done``, so the hole refills.
        """
        await _record_many(db, conn_id, {D1: "ok", D2: "ok", D3: "failed", D4: "ok", D5: "ok"})

        pending = await _pending(db, conn_id, tail=0)

        assert pending == [D3], (
            "a failed period below the high-water mark must stay pending; "
            f"got {pending!r} — this is the max(period) bug"
        )

    async def test_failed_period_stays_pending_across_repeated_checks(
        self, db: AsyncSession, conn_id: str
    ):
        """It stays pending forever until it actually succeeds — then it clears."""
        await _record_many(db, conn_id, {D1: "ok", D2: "ok", D3: "failed", D4: "ok", D5: "ok"})
        assert await _pending(db, conn_id, tail=0) == [D3]
        assert await _pending(db, conn_id, tail=0) == [D3]

        await _record_many(db, conn_id, {D3: "ok"})
        assert await _pending(db, conn_id, tail=0) == []

    async def test_empty_journal_makes_everything_pending(self, db: AsyncSession, conn_id: str):
        assert await _pending(db, conn_id, tail=0) == EXPECTED

    async def test_empty_status_counts_as_done(self, db: AsyncSession, conn_id: str):
        """A period with genuinely no data is complete — never retried forever."""
        await _record_many(db, conn_id, {D1: "ok", D2: "ok", D3: "empty", D4: "ok", D5: "ok"})

        assert await _pending(db, conn_id, tail=0) == []

    async def test_tail_periods_are_always_refetched(self, db: AsyncSession, conn_id: str):
        """Vendors revise recent data, so the last ``tail`` periods always refetch."""
        await _record_many(db, conn_id, dict.fromkeys(EXPECTED, "ok"))

        assert await _pending(db, conn_id, tail=2) == [D4, D5]

    async def test_tail_unions_with_the_hole(self, db: AsyncSession, conn_id: str):
        """The tail is a union, not a replacement — the hole survives it."""
        await _record_many(db, conn_id, {D1: "ok", D2: "ok", D3: "failed", D4: "ok", D5: "ok"})

        assert await _pending(db, conn_id, tail=2) == [D3, D4, D5]

    async def test_tail_larger_than_expected_is_clamped(self, db: AsyncSession, conn_id: str):
        await _record_many(db, conn_id, dict.fromkeys(EXPECTED, "ok"))

        assert await _pending(db, conn_id, tail=99) == EXPECTED

    async def test_tail_zero_refetches_nothing(self, db: AsyncSession, conn_id: str):
        """``expected[-0:]`` is the whole list — tail=0 must mean *no* tail."""
        await _record_many(db, conn_id, dict.fromkeys(EXPECTED, "ok"))

        assert await _pending(db, conn_id, tail=0) == []

    async def test_output_is_sorted_and_never_outside_expected(
        self, db: AsyncSession, conn_id: str
    ):
        """Unsorted input, journal rows outside ``expected`` — output stays clean."""
        await _record_many(db, conn_id, {D2: "ok", "2026-06-30": "ok", "2026-07-20": "failed"})

        pending = await _pending(db, conn_id, expected=[D5, D1, D3, D2, D4], tail=0)

        assert pending == [D1, D3, D4, D5]
        assert pending == sorted(pending)
        assert set(pending) <= set(EXPECTED)

    async def test_tail_follows_chronology_not_input_order(self, db: AsyncSession, conn_id: str):
        """The tail means the chronologically latest periods, however they arrive."""
        await _record_many(db, conn_id, dict.fromkeys(EXPECTED, "ok"))

        assert await _pending(db, conn_id, expected=[D3, D5, D1, D4, D2], tail=1) == [D5]

    async def test_duplicate_expected_entries_appear_once(self, db: AsyncSession, conn_id: str):
        assert await _pending(db, conn_id, expected=[D1, D1, D2], tail=0) == [D1, D2]

    async def test_empty_expected_is_empty_pending(self, db: AsyncSession, conn_id: str):
        assert await _pending(db, conn_id, expected=[], tail=5) == []

    async def test_other_report_does_not_mark_a_period_done(self, db: AsyncSession, conn_id: str):
        """The journal key is (connection, report, period) — reports are independent."""
        await _record_many(db, conn_id, dict.fromkeys(EXPECTED, "ok"), report=OTHER_REPORT)

        assert await _pending(db, conn_id, tail=0) == EXPECTED
        assert await _pending(db, conn_id, tail=0, report=OTHER_REPORT) == []

    async def test_other_connection_does_not_mark_a_period_done(self, db: AsyncSession):
        """Tenant isolation: another connection's success is not ours."""
        mine = await _connection(db)
        theirs = await _connection(db)
        await _record_many(db, theirs, dict.fromkeys(EXPECTED, "ok"))

        assert await _pending(db, mine, tail=0) == EXPECTED


class TestRecord:
    async def test_same_triple_upserts_to_one_row_latest_status_wins(
        self, db: AsyncSession, conn_id: str
    ):
        await journal.record(
            db,
            connection_id=conn_id,
            report=REPORT,
            period=D1,
            status="failed",
            error="quota exhausted",
        )
        await journal.record(
            db,
            connection_id=conn_id,
            report=REPORT,
            period=D1,
            status="ok",
            rows_written=42,
        )

        rows = await _rows(db, conn_id)
        assert len(rows) == 1, "the UNIQUE key must be the upsert conflict target"
        assert rows[0].status == "ok"
        assert rows[0].rows_written == 42
        assert rows[0].error is None, "a successful re-run must clear the stale error"

    async def test_upsert_refreshes_fetched_at(self, db: AsyncSession, conn_id: str):
        await journal.record(db, connection_id=conn_id, report=REPORT, period=D1, status="ok")
        first = (await _rows(db, conn_id))[0].fetched_at
        assert first is not None

        stale = datetime.now(UTC) - timedelta(days=3)
        (await _rows(db, conn_id))[0].fetched_at = stale
        await db.commit()

        await journal.record(db, connection_id=conn_id, report=REPORT, period=D1, status="ok")

        refreshed = (await _rows(db, conn_id))[0].fetched_at
        assert refreshed.replace(tzinfo=None) > stale.replace(tzinfo=None)

    async def test_distinct_triples_are_distinct_rows(self, db: AsyncSession, conn_id: str):
        other_conn = await _connection(db)
        await journal.record(db, connection_id=conn_id, report=REPORT, period=D1, status="ok")
        await journal.record(db, connection_id=conn_id, report=OTHER_REPORT, period=D1, status="ok")
        await journal.record(db, connection_id=conn_id, report=REPORT, period=D2, status="ok")
        await journal.record(db, connection_id=other_conn, report=REPORT, period=D1, status="ok")

        assert await _count(db) == 4

    async def test_failure_is_recorded_with_its_error(self, db: AsyncSession, conn_id: str):
        await journal.record(
            db,
            connection_id=conn_id,
            report=REPORT,
            period=D1,
            status="failed",
            error="429 quota",
        )

        row = (await _rows(db, conn_id))[0]
        assert (row.status, row.rows_written, row.error) == ("failed", 0, "429 quota")

    async def test_record_is_durable_without_a_caller_commit(self, db: AsyncSession, conn_id: str):
        """The verdict must survive a crash mid-run, so ``record`` commits itself."""
        await journal.record(db, connection_id=conn_id, report=REPORT, period=D1, status="ok")
        await db.rollback()

        assert await _count(db) == 1

    async def test_rejects_an_unknown_status(self, db: AsyncSession, conn_id: str):
        """A typo'd status would silently become "not done" forever."""
        with pytest.raises(ValueError, match="status"):
            await journal.record(
                db, connection_id=conn_id, report=REPORT, period=D1, status="success"
            )

    async def test_upsert_falls_back_on_an_unknown_dialect(
        self, db: AsyncSession, conn_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        """Neither Postgres nor SQLite: the portable select-then-write path runs."""
        monkeypatch.setattr(journal, "_dialect_name", lambda _session: "mysql")

        await journal.record(db, connection_id=conn_id, report=REPORT, period=D1, status="failed")
        await journal.record(
            db, connection_id=conn_id, report=REPORT, period=D1, status="ok", rows_written=7
        )

        rows = await _rows(db, conn_id)
        assert len(rows) == 1
        assert (rows[0].status, rows[0].rows_written) == ("ok", 7)


class TestPrune:
    async def _seed(self, db: AsyncSession, conn_id: str, ages_days: dict[str, int]) -> None:
        now = datetime.now(UTC)
        for period, age in ages_days.items():
            db.add(
                AnalyticsImport(
                    connection_id=conn_id,
                    report=REPORT,
                    period=period,
                    status="ok",
                    rows_written=1,
                    fetched_at=now - timedelta(days=age),
                )
            )
        await db.commit()

    async def test_deletes_only_rows_older_than_the_cutoff(self, db: AsyncSession, conn_id: str):
        await self._seed(db, conn_id, {D1: 500, D2: 401, D3: 399, D4: 0})

        deleted = await journal.prune(db, older_than_days=400)

        assert deleted == 2
        assert [r.period for r in await _rows(db, conn_id)] == [D3, D4]

    async def test_returns_zero_when_nothing_is_old_enough(self, db: AsyncSession, conn_id: str):
        await self._seed(db, conn_id, {D1: 10, D2: 20})

        assert await journal.prune(db, older_than_days=400) == 0
        assert await _count(db) == 2

    async def test_default_retention_is_400_days(self, db: AsyncSession, conn_id: str):
        await self._seed(db, conn_id, {D1: 401, D2: 399})

        assert await journal.prune(db) == 1
        assert [r.period for r in await _rows(db, conn_id)] == [D2]

    async def test_prune_is_durable_without_a_caller_commit(self, db: AsyncSession, conn_id: str):
        await self._seed(db, conn_id, {D1: 500})

        await journal.prune(db, older_than_days=400)
        await db.rollback()

        assert await _count(db) == 0

    async def test_rejects_a_non_positive_retention(self, db: AsyncSession, conn_id: str):
        """``older_than_days=0`` would delete the whole journal."""
        await self._seed(db, conn_id, {D1: 1})

        with pytest.raises(ValueError, match="older_than_days"):
            await journal.prune(db, older_than_days=0)
        assert await _count(db) == 1
