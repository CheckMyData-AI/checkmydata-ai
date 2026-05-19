"""V4 — vision §7 #6: thumbs-down must contradict the learnings that
were exposed to the LLM for the failed query, capped at 3 to bound the
contradiction blast radius."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes.chat import contradict_exposed_learnings_on_negative_feedback
from app.models.agent_learning import AgentLearning
from app.models.base import Base


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _seed(
    session: AsyncSession,
    connection_id: str,
    *,
    confidence: float = 0.8,
    times_applied: int = 0,
    is_active: bool = True,
    lesson: str | None = None,
) -> AgentLearning:
    lrn = AgentLearning(
        id=str(uuid.uuid4()),
        connection_id=connection_id,
        category="schema_gotcha",
        subject="users",
        lesson=lesson or f"Some lesson {uuid.uuid4().hex[:6]}",
        lesson_hash=uuid.uuid4().hex[:32],
        confidence=confidence,
        times_applied=times_applied,
        is_active=is_active,
    )
    session.add(lrn)
    await session.commit()
    await session.refresh(lrn)
    return lrn


class TestV4Contradiction:
    @pytest.mark.asyncio
    async def test_contradicts_all_exposed_when_under_cap(self, session):
        l1 = await _seed(session, "c1", confidence=0.8)
        l2 = await _seed(session, "c1", confidence=0.6)

        n = await contradict_exposed_learnings_on_negative_feedback(
            session,
            connection_id="c1",
            exposed_learning_ids=[l1.id, l2.id],
        )

        assert n == 2
        await session.refresh(l1)
        await session.refresh(l2)
        assert l1.confidence == pytest.approx(0.5, abs=1e-6)
        assert l2.confidence == pytest.approx(0.3, abs=1e-6)

    @pytest.mark.asyncio
    async def test_caps_at_three_ranked_by_influence(self, session):
        # Higher confidence × times_applied → contradicted first
        high1 = await _seed(session, "c1", confidence=0.9, times_applied=10)
        high2 = await _seed(session, "c1", confidence=0.8, times_applied=8)
        high3 = await _seed(session, "c1", confidence=0.7, times_applied=6)
        low1 = await _seed(session, "c1", confidence=0.5, times_applied=1)
        low2 = await _seed(session, "c1", confidence=0.4, times_applied=0)

        n = await contradict_exposed_learnings_on_negative_feedback(
            session,
            connection_id="c1",
            exposed_learning_ids=[low1.id, low2.id, high1.id, high2.id, high3.id],
        )

        assert n == 3
        for lrn in (high1, high2, high3):
            await session.refresh(lrn)
            assert lrn.confidence < 0.9 - 0.2  # was deducted by 0.3
        for lrn in (low1, low2):
            await session.refresh(lrn)
            # Untouched (not in top-3)
            assert lrn.confidence in (0.5, 0.4)

    @pytest.mark.asyncio
    async def test_deactivates_below_threshold(self, session):
        # Confidence 0.35 → 0.05 after contradiction → deactivated
        weak = await _seed(session, "c1", confidence=0.35)

        n = await contradict_exposed_learnings_on_negative_feedback(
            session,
            connection_id="c1",
            exposed_learning_ids=[weak.id],
        )

        assert n == 1
        await session.refresh(weak)
        assert weak.confidence == pytest.approx(0.05, abs=1e-6)
        assert weak.is_active is False

    @pytest.mark.asyncio
    async def test_ignores_other_connection_ids(self, session):
        # A learning belonging to a different connection must NOT be touched
        # even if its ID is in the exposed list (defense-in-depth).
        own = await _seed(session, "c1", confidence=0.8)
        sibling = await _seed(session, "c2", confidence=0.8)

        n = await contradict_exposed_learnings_on_negative_feedback(
            session,
            connection_id="c1",
            exposed_learning_ids=[own.id, sibling.id],
        )

        assert n == 1
        await session.refresh(own)
        await session.refresh(sibling)
        assert own.confidence == pytest.approx(0.5, abs=1e-6)
        assert sibling.confidence == pytest.approx(0.8, abs=1e-6)

    @pytest.mark.asyncio
    async def test_handles_empty_exposed_list(self, session):
        n = await contradict_exposed_learnings_on_negative_feedback(
            session,
            connection_id="c1",
            exposed_learning_ids=[],
        )
        assert n == 0

    @pytest.mark.asyncio
    async def test_handles_no_connection_id(self, session):
        l1 = await _seed(session, "c1", confidence=0.8)
        n = await contradict_exposed_learnings_on_negative_feedback(
            session,
            connection_id="",
            exposed_learning_ids=[l1.id],
        )
        assert n == 0
        await session.refresh(l1)
        assert l1.confidence == pytest.approx(0.8, abs=1e-6)
