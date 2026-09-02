"""A learning that reaches the prompt could never grow stale.

`AgentLearning.updated_at` carries `onupdate=func.now()`. `expose_learning` issues an
`UPDATE` — and `decay_stale_learnings` selects on `updated_at < now() - 30 days`. The SQL
agent exposes every surfaced learning on every run (`sql_agent.py:2117`), so the top
learnings for any active connection reset their own staleness clock faster than the clock
runs out. They could never lose confidence and never be deactivated; only three explicit
user downvotes could remove a wrong lesson.

Measured in production on 2026-09-02, and the split is exactly the shape of the defect:

| | rows | oldest `updated_at` | oldest `created_at` |
|---|---|---|---|
| ever exposed | 35 | **14 days** | 5 months 13 days |
| never exposed | 44 | 27 days | 5 months 12 days |

The never-exposed ones cycle through decay normally. The exposed ones cannot reach 30
days at all. 74 of the 79 active learnings were created over a month ago and **none** was
eligible to decay.

`expose_learning`'s own docstring says it "separates read-side traffic from citation so
`times_applied` (and the decay score derived from it) remains a meaningful signal". The
column default silently undid that separation: exposure is explicitly *not* a substantive
update, so it must not move the clock that measures substantive updates. Every other
mutation in the service sets `updated_at` by hand already — this is the only writer that
relied on `onupdate`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.agent_learning import AgentLearning
from app.models.base import Base
from app.services.agent_learning_service import AgentLearningService

_OLD = datetime.now(UTC) - timedelta(days=40)


@pytest_asyncio.fixture()
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _stale_learning(db, **kw) -> AgentLearning:
    row = AgentLearning(
        connection_id="conn-1",
        category="schema",
        subject="orders",
        lesson="Always filter orders by status = 'paid'.",
        lesson_hash="h" * 32,
        confidence=0.8,
        created_at=_OLD,
        updated_at=_OLD,
        **kw,
    )
    db.add(row)
    await db.commit()
    return row


async def _reload(db, row_id: str) -> AgentLearning:
    db.expire_all()
    return (await db.execute(select(AgentLearning).where(AgentLearning.id == row_id))).scalar_one()


class TestExposureDoesNotResetTheStalenessClock:
    async def test_updated_at_is_unchanged_by_exposure(self, db) -> None:
        row = await _stale_learning(db)
        await AgentLearningService().expose_learning(db, row.id)
        await db.commit()
        after = await _reload(db, row.id)
        # Asserted as the property that matters rather than as an exact timestamp: the
        # row must still be older than the cutoff `decay_stale_learnings` uses.
        cutoff = datetime.now(UTC) - timedelta(days=30)
        assert after.updated_at.replace(tzinfo=UTC) < cutoff, (
            "exposure moved updated_at to "
            f"{after.updated_at}, so a surfaced learning can never reach the 30-day "
            "decay cutoff"
        )

    async def test_the_exposure_count_still_moves(self, db) -> None:
        """The pin must not cost the signal it was pinning around."""
        row = await _stale_learning(db, times_exposed=4)
        await AgentLearningService().expose_learning(db, row.id)
        await db.commit()
        assert (await _reload(db, row.id)).times_exposed == 5

    async def test_a_surfaced_learning_can_still_decay(self, db) -> None:
        """The whole point: after exposure it is still eligible."""
        row = await _stale_learning(db, times_applied=0, times_exposed=9)
        svc = AgentLearningService()
        await svc.expose_learning(db, row.id)
        await db.commit()

        affected = await svc.decay_stale_learnings(db)
        assert affected >= 1, "a learning exposed today is immortal"
        assert (await _reload(db, row.id)).confidence < 0.8


class TestSubstantiveChangesStillMoveTheClock:
    async def test_a_confirmation_refreshes_it(self, db) -> None:
        """Pinning exposure must not pin everything — a real update is what the decay
        window is supposed to measure."""
        row = await _stale_learning(db)
        row.times_confirmed = 1
        row.updated_at = datetime.now(UTC)
        await db.commit()
        after = await _reload(db, row.id)
        assert after.updated_at.replace(tzinfo=UTC) > _OLD
