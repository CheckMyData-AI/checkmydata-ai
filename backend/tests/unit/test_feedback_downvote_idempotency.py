"""AQ-1: repeated thumbs-down on the SAME message must apply the learning
rollback exactly once (symmetric to the positive-path ``learning_credited_at_validation``
guard). Previously every repeated downvote re-applied −0.3 to the top-3 exposed
learnings and pumped the "User flagged incorrect results…" lesson via exact
dedup up to ★CRITICAL.
"""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes.chat_feedback import process_negative_feedback_learning_effects
from app.models.agent_learning import AgentLearning
from app.models.base import Base
from app.models.chat_session import ChatMessage, ChatSession


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _seed_message(session: AsyncSession) -> ChatMessage:
    chat = ChatSession(id=str(uuid.uuid4()), project_id=str(uuid.uuid4()))
    session.add(chat)
    msg = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=chat.id,
        role="assistant",
        content="Here is the answer.",
        metadata_json=json.dumps(
            {
                "query": "SELECT * FROM users",
                "question": "how many users?",
                "exposed_learning_ids": [],
            }
        ),
    )
    session.add(msg)
    await session.commit()
    return msg


async def _seed_learning(
    session: AsyncSession,
    connection_id: str,
    *,
    confidence: float = 0.8,
) -> AgentLearning:
    lrn = AgentLearning(
        id=str(uuid.uuid4()),
        connection_id=connection_id,
        category="schema_gotcha",
        subject="users",
        lesson=f"Some lesson {uuid.uuid4().hex[:6]}",
        lesson_hash=uuid.uuid4().hex[:32],
        confidence=confidence,
        is_active=True,
    )
    session.add(lrn)
    await session.commit()
    await session.refresh(lrn)
    return lrn


class TestNegativeFeedbackIdempotency:
    @pytest.mark.asyncio
    async def test_double_downvote_applies_contradiction_once(self, session):
        msg = await _seed_message(session)
        lrn = await _seed_learning(session, "c1", confidence=0.8)

        kwargs = {
            "message_id": msg.id,
            "connection_id": "c1",
            "query": "SELECT * FROM users",
            "question": "how many users?",
            "exposed_learning_ids": [lrn.id],
        }
        first = await process_negative_feedback_learning_effects(session, **kwargs)
        second = await process_negative_feedback_learning_effects(session, **kwargs)

        assert first is True
        assert second is False, "repeat downvote on the same message must be a no-op"
        await session.refresh(lrn)
        # −0.3 applied exactly once (would be 0.2 without the guard)
        assert lrn.confidence == pytest.approx(0.5, abs=1e-6)

    @pytest.mark.asyncio
    async def test_double_downvote_does_not_pump_flagged_lesson(self, session):
        msg = await _seed_message(session)

        kwargs = {
            "message_id": msg.id,
            "connection_id": "c1",
            "query": "SELECT * FROM users",
            "question": "how many users?",
            "exposed_learning_ids": [],
        }
        assert await process_negative_feedback_learning_effects(session, **kwargs) is True
        assert await process_negative_feedback_learning_effects(session, **kwargs) is False

        stmt = select(AgentLearning).where(AgentLearning.connection_id == "c1")
        rows = (await session.execute(stmt)).scalars().all()
        flagged = [r for r in rows if "User flagged" in r.lesson]
        assert len(flagged) == 1, "garbage flagged-lesson must not be duplicated"
        # Exact-dedup would have pumped this to 0.8 / times_confirmed=1 on repeat.
        assert flagged[0].confidence == pytest.approx(0.7, abs=1e-6)
        assert flagged[0].times_confirmed == 0

    @pytest.mark.asyncio
    async def test_downvote_on_other_message_still_applies(self, session):
        msg1 = await _seed_message(session)
        msg2 = await _seed_message(session)
        lrn = await _seed_learning(session, "c1", confidence=0.8)

        base = {
            "connection_id": "c1",
            "query": "SELECT * FROM users",
            "question": "q",
            "exposed_learning_ids": [lrn.id],
        }
        assert (
            await process_negative_feedback_learning_effects(session, message_id=msg1.id, **base)
            is True
        )
        # A different message = a different user signal — rollback applies again.
        assert (
            await process_negative_feedback_learning_effects(session, message_id=msg2.id, **base)
            is True
        )
        await session.refresh(lrn)
        assert lrn.confidence == pytest.approx(0.2, abs=1e-6)

    @pytest.mark.asyncio
    async def test_missing_connection_is_noop(self, session):
        msg = await _seed_message(session)
        applied = await process_negative_feedback_learning_effects(
            session,
            message_id=msg.id,
            connection_id=None,
            query="SELECT * FROM users",
            question="q",
            exposed_learning_ids=[],
        )
        assert applied is False

    @pytest.mark.asyncio
    async def test_positive_credit_flag_still_works(self, session):
        """Regression: the refactor of the meta-flag helpers must keep the
        positive-path credited flag behaviour intact."""
        from app.api.routes.chat_feedback import (
            _mark_message_learning_credited,
            _message_learning_credited,
        )

        msg = await _seed_message(session)
        assert await _message_learning_credited(session, msg.id) is False
        await _mark_message_learning_credited(session, msg.id)
        assert await _message_learning_credited(session, msg.id) is True
