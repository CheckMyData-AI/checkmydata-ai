"""Regression: ``reconcile_with_query_results`` must tolerate a *naive*
``detected_at`` read-back.

``InsightRecord.detected_at`` is ``DateTime(timezone=True)`` with
``server_default=func.now()``, so on SQLite it is always populated by the DB
and reads back **naive** (even in the same session that created the row). The
staleness check compared it against an aware ``datetime.now(UTC) - …`` cutoff,
raising ``TypeError: can't compare offset-naive and offset-aware datetimes``
and crashing the whole reconciliation pass whenever an active insight went
unmatched. Production (PostgreSQL/asyncpg) returns aware datetimes and was
unaffected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.insight_memory import InsightMemoryService
from app.models.base import Base
from app.models.insight_record import InsightRecord  # noqa: F401 — register mapper


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    s = sm()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


async def _add_active_anomaly(session: AsyncSession, detected_at: datetime) -> InsightRecord:
    rec = InsightRecord(
        project_id="p1",
        connection_id="c1",
        insight_type="anomaly",
        severity="warning",
        title="Orders dropped 90%",
        description="anomaly detail",
        status="active",
    )
    session.add(rec)
    await session.commit()
    # Overwrite with a NAIVE value to mirror what SQLite returns for a
    # DateTime(timezone=True) server-default column.
    rec.detected_at = detected_at
    await session.commit()
    return rec


class TestReconcileNaiveDetectedAt:
    @pytest.mark.asyncio
    async def test_stale_insight_dismissed_with_naive_detected_at(self, session):
        svc = InsightMemoryService()
        await _add_active_anomaly(session, detected_at=datetime(2020, 1, 1))  # naive, stale

        # No fresh reports → the insight stays unmatched → it reaches the
        # staleness comparison that crashed on a naive detected_at.
        confirmed, dismissed = await svc.reconcile_with_query_results(
            session, project_id="p1", connection_id="c1", fresh_reports=[]
        )
        assert confirmed == 0
        assert dismissed == 1

    @pytest.mark.asyncio
    async def test_recent_insight_kept_with_naive_detected_at(self, session):
        svc = InsightMemoryService()
        recent_naive = (datetime.now(UTC) - timedelta(days=1)).replace(tzinfo=None)
        await _add_active_anomaly(session, detected_at=recent_naive)

        confirmed, dismissed = await svc.reconcile_with_query_results(
            session, project_id="p1", connection_id="c1", fresh_reports=[]
        )
        # Within the 14-day staleness window → kept, not dismissed, no crash.
        assert confirmed == 0
        assert dismissed == 0
