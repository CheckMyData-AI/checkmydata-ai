"""F-LEARN-08, the half that was still open: the upvote path had no per-message guard.

The board lists F-LEARN-08 as "feedback not idempotent → repeated 👎 deactivates
shared learnings". The **downvote** half is closed — `process_negative_feedback_
learning_effects` refuses a repeat via a `learning_contradicted_at_feedback` flag,
and `test_feedback_downvote_idempotency.py` covers it. Its twin was not.

The route guards the positive path on `learning_credited_at_validation`, which is
set at *validation* time by a different path. For a message that was never credited
there, clicking 👍 twice calls `apply_exposed_learnings_on_positive_feedback` twice
and bumps `times_applied` twice per learning. That counter feeds the decay score and
the ranking — `times_exposed` is deliberately NOT the same signal — so a replayed
upvote inflates a learning's standing. The mirror of the downvote-bomb, and the
codebase said so out loud: "apply_learning is not idempotent, so a second pass would
double-bump times_applied".

So the fix is the symmetry both docstrings already claim: a
`learning_credited_at_feedback` flag, checked and set exactly like its twin.
"""

from __future__ import annotations

import json
import uuid

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes.chat_feedback import process_positive_feedback_learning_effects
from app.models.agent_learning import AgentLearning
from app.models.base import Base
from app.models.chat_session import ChatMessage, ChatSession

CONNECTION_ID = "conn-fixed"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[ChatMessage, AgentLearning]:
    chat = ChatSession(id=str(uuid.uuid4()), project_id=str(uuid.uuid4()))
    session.add(chat)
    learning = AgentLearning(
        id=str(uuid.uuid4()),
        connection_id=CONNECTION_ID,
        category="schema_gotcha",
        subject="users table",
        lesson="Join through user_profiles, never directly on email.",
        lesson_hash=uuid.uuid4().hex[:32],
        confidence=0.5,
        times_applied=0,
        is_active=True,
    )
    session.add(learning)
    msg = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=chat.id,
        role="assistant",
        content="Here is the answer.",
        metadata_json=json.dumps({"exposed_learning_ids": [learning.id]}),
    )
    session.add(msg)
    await session.commit()
    return msg, learning


async def _times_applied(session: AsyncSession, learning_id: str) -> int:
    row = (
        await session.execute(select(AgentLearning).where(AgentLearning.id == learning_id))
    ).scalar_one()
    await session.refresh(row)
    return row.times_applied


async def test_a_repeated_upvote_credits_exactly_once(session: AsyncSession):
    msg, learning = await _seed(session)

    first = await process_positive_feedback_learning_effects(
        session,
        message_id=msg.id,
        connection_id=CONNECTION_ID,
        exposed_learning_ids=[learning.id],
    )
    after_first = await _times_applied(session, learning.id)

    second = await process_positive_feedback_learning_effects(
        session,
        message_id=msg.id,
        connection_id=CONNECTION_ID,
        exposed_learning_ids=[learning.id],
    )
    after_second = await _times_applied(session, learning.id)

    assert first is True
    assert second is False, "the second upvote on the same message must be a no-op"
    assert after_first == 1
    assert after_second == 1, (
        f"times_applied was bumped again by a replayed upvote: {after_first} -> {after_second}"
    )


async def test_an_upvote_on_a_different_message_still_credits(session: AsyncSession):
    """The guard is per MESSAGE, exactly like its downvote twin — not per learning."""
    msg_a, learning = await _seed(session)
    chat_b = ChatSession(id=str(uuid.uuid4()), project_id=str(uuid.uuid4()))
    session.add(chat_b)
    msg_b = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=chat_b.id,
        role="assistant",
        content="Another answer.",
        metadata_json=json.dumps({"exposed_learning_ids": [learning.id]}),
    )
    session.add(msg_b)
    await session.commit()

    await process_positive_feedback_learning_effects(
        session,
        message_id=msg_a.id,
        connection_id=CONNECTION_ID,
        exposed_learning_ids=[learning.id],
    )
    await process_positive_feedback_learning_effects(
        session,
        message_id=msg_b.id,
        connection_id=CONNECTION_ID,
        exposed_learning_ids=[learning.id],
    )
    assert await _times_applied(session, learning.id) == 2


async def test_a_missing_connection_is_refused_not_guessed(session: AsyncSession):
    msg, learning = await _seed(session)
    assert (
        await process_positive_feedback_learning_effects(
            session,
            message_id=msg.id,
            connection_id=None,
            exposed_learning_ids=[learning.id],
        )
        is False
    )
    assert await _times_applied(session, learning.id) == 0
