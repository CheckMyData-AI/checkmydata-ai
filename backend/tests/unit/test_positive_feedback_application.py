"""Thumbs-up must credit the learnings that were exposed to the LLM for the
answer as *applied* (bump ``times_applied``). Symmetric counterpart to the V4
negative-feedback contradiction path; keeps ``times_applied`` a live signal in
production rather than dead code."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes.chat_feedback import apply_exposed_learnings_on_positive_feedback
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
    times_applied: int = 0,
    is_active: bool = True,
) -> AgentLearning:
    lrn = AgentLearning(
        id=str(uuid.uuid4()),
        connection_id=connection_id,
        category="schema_gotcha",
        subject="users",
        lesson=f"Some lesson {uuid.uuid4().hex[:6]}",
        lesson_hash=uuid.uuid4().hex[:32],
        confidence=0.8,
        times_applied=times_applied,
        is_active=is_active,
    )
    session.add(lrn)
    await session.commit()
    await session.refresh(lrn)
    return lrn


class TestPositiveFeedbackApplication:
    @pytest.mark.asyncio
    async def test_applies_all_exposed(self, session):
        l1 = await _seed(session, "c1", times_applied=0)
        l2 = await _seed(session, "c1", times_applied=3)

        n = await apply_exposed_learnings_on_positive_feedback(
            session,
            connection_id="c1",
            exposed_learning_ids=[l1.id, l2.id],
        )

        assert n == 2
        await session.refresh(l1)
        await session.refresh(l2)
        assert l1.times_applied == 1
        assert l2.times_applied == 4

    @pytest.mark.asyncio
    async def test_ignores_other_connection_ids(self, session):
        own = await _seed(session, "c1", times_applied=0)
        sibling = await _seed(session, "c2", times_applied=0)

        n = await apply_exposed_learnings_on_positive_feedback(
            session,
            connection_id="c1",
            exposed_learning_ids=[own.id, sibling.id],
        )

        assert n == 1
        await session.refresh(own)
        await session.refresh(sibling)
        assert own.times_applied == 1
        assert sibling.times_applied == 0

    @pytest.mark.asyncio
    async def test_skips_inactive(self, session):
        inactive = await _seed(session, "c1", times_applied=0, is_active=False)
        n = await apply_exposed_learnings_on_positive_feedback(
            session,
            connection_id="c1",
            exposed_learning_ids=[inactive.id],
        )
        assert n == 0
        await session.refresh(inactive)
        assert inactive.times_applied == 0

    @pytest.mark.asyncio
    async def test_handles_empty_exposed_list(self, session):
        n = await apply_exposed_learnings_on_positive_feedback(
            session,
            connection_id="c1",
            exposed_learning_ids=[],
        )
        assert n == 0

    @pytest.mark.asyncio
    async def test_handles_no_connection_id(self, session):
        l1 = await _seed(session, "c1", times_applied=0)
        n = await apply_exposed_learnings_on_positive_feedback(
            session,
            connection_id="",
            exposed_learning_ids=[l1.id],
        )
        assert n == 0
        await session.refresh(l1)
        assert l1.times_applied == 0
