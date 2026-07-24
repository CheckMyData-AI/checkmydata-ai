"""AQ-7: per-user vote dedup on learning confirm/contradict.

One active vote per (learning, user): a repeated same-sign vote is a no-op
(one user cannot pump confidence to 1.0 / ★CRITICAL or deactivate someone
else's learning with two clicks); a sign change reverses the previous
effect; votes from different users are independent.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.agent_learning import AgentLearning
from app.models.base import Base
from app.services.agent_learning_service import AgentLearningService


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def learning(session: AsyncSession) -> AgentLearning:
    lrn = AgentLearning(
        id=str(uuid.uuid4()),
        connection_id="c1",
        category="schema_gotcha",
        subject="users",
        lesson="Filter users by deleted_at IS NULL for active rows",
        lesson_hash=uuid.uuid4().hex[:32],
        confidence=0.6,
        is_active=True,
    )
    session.add(lrn)
    await session.commit()
    await session.refresh(lrn)
    return lrn


_svc = AgentLearningService()


class TestVoteDedup:
    @pytest.mark.asyncio
    async def test_repeated_confirm_is_noop(self, session, learning):
        # 4 clicks by the same user must NOT pump 0.6 → 1.0 (AQ-7).
        outcomes = []
        for _ in range(4):
            _, outcome = await _svc.vote_learning(session, learning.id, "user-a", 1)
            outcomes.append(outcome)

        assert outcomes == ["recorded", "noop", "noop", "noop"]
        await session.refresh(learning)
        assert learning.confidence == pytest.approx(0.7, abs=1e-6)  # bumped exactly once
        assert learning.times_confirmed == 1

    @pytest.mark.asyncio
    async def test_repeated_contradict_is_noop(self, session, learning):
        # 2 contradict clicks by the same user must NOT deactivate (0.6 → 0.0).
        _, o1 = await _svc.vote_learning(session, learning.id, "user-a", -1)
        _, o2 = await _svc.vote_learning(session, learning.id, "user-a", -1)

        assert (o1, o2) == ("recorded", "noop")
        await session.refresh(learning)
        assert learning.confidence == pytest.approx(0.3, abs=1e-6)
        assert learning.is_active is True

    @pytest.mark.asyncio
    async def test_sign_change_reverses_previous_effect(self, session, learning):
        _, o1 = await _svc.vote_learning(session, learning.id, "user-a", 1)
        _, o2 = await _svc.vote_learning(session, learning.id, "user-a", -1)

        assert (o1, o2) == ("recorded", "changed")
        await session.refresh(learning)
        # 0.6 → confirm 0.7 → reverse (-0.1) → 0.6 → contradict (-0.3) → 0.3
        assert learning.confidence == pytest.approx(0.3, abs=1e-6)
        assert learning.times_confirmed == 0

    @pytest.mark.asyncio
    async def test_sign_change_back_to_confirm(self, session, learning):
        await _svc.vote_learning(session, learning.id, "user-a", -1)
        _, outcome = await _svc.vote_learning(session, learning.id, "user-a", 1)

        assert outcome == "changed"
        await session.refresh(learning)
        # 0.6 → contradict 0.3 → reverse (+0.3) → 0.6 → confirm (+0.1) → 0.7
        assert learning.confidence == pytest.approx(0.7, abs=1e-6)
        assert learning.times_confirmed == 1
        assert learning.is_active is True

    @pytest.mark.asyncio
    async def test_votes_from_different_users_are_independent(self, session, learning):
        _, o1 = await _svc.vote_learning(session, learning.id, "user-a", 1)
        _, o2 = await _svc.vote_learning(session, learning.id, "user-b", 1)
        _, o3 = await _svc.vote_learning(session, learning.id, "user-c", -1)

        assert (o1, o2, o3) == ("recorded", "recorded", "recorded")
        await session.refresh(learning)
        # 0.6 + 0.1 + 0.1 - 0.3
        assert learning.confidence == pytest.approx(0.5, abs=1e-6)
        assert learning.times_confirmed == 2

    @pytest.mark.asyncio
    async def test_contradict_deactivates_only_below_threshold(self, session, learning):
        # A single user's contradict on a weak learning still deactivates…
        learning.confidence = 0.35
        await session.commit()
        await _svc.vote_learning(session, learning.id, "user-a", -1)
        await session.refresh(learning)
        assert learning.confidence == pytest.approx(0.05, abs=1e-6)
        assert learning.is_active is False
        # …but a repeat click from the same user stays a no-op.
        _, outcome = await _svc.vote_learning(session, learning.id, "user-a", -1)
        assert outcome == "noop"
        await session.refresh(learning)
        assert learning.confidence == pytest.approx(0.05, abs=1e-6)

    @pytest.mark.asyncio
    async def test_missing_learning_returns_none(self, session):
        entry, outcome = await _svc.vote_learning(session, "nope", "user-a", 1)
        assert entry is None
        assert outcome == "missing"

    @pytest.mark.asyncio
    async def test_invalid_vote_rejected(self, session, learning):
        with pytest.raises(ValueError, match="Invalid vote"):
            await _svc.vote_learning(session, learning.id, "user-a", 2)
