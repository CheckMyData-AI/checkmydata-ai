"""F-LEARN-03: confidence treated re-derivation as if it were a person's vote.

Two paths bump a learning's confidence by exactly `+0.1`, and they carry very
different evidence:

* **A user upvote** (`vote_learning`) is deduplicated per user by the `LearningVote`
  table — a second identical vote returns `"noop"` — and vision §7 makes user feedback
  the highest authority there is.
* **Re-deriving the same lesson** (`create_learning` finding an exact or similar match)
  is deduplicated **not at all**. Call it four times from one agent run and 0.6 becomes
  1.0, at which point the number reads as certainty earned from one lesson submitted
  four times.

So the defect is not simply that 1.0 is reachable. It is that the weakest and the
strongest evidence move the number identically, and only one of the two is counted
once. Re-derivation now has diminishing returns and a ceiling below what a person can
confer; the vote path is deliberately untouched.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.agent_learning import AgentLearning, _lesson_hash
from app.services.agent_learning_service import AgentLearningService


@pytest.fixture
def svc():
    return AgentLearningService()


def _entry(**over) -> AgentLearning:
    d = {
        "id": "l1",
        "connection_id": "conn-1",
        "category": "table_preference",
        "subject": "orders",
        "lesson": "Use orders_v2 instead of orders_legacy",
        "lesson_hash": _lesson_hash("Use orders_v2 instead of orders_legacy"),
        "confidence": 0.6,
        "times_confirmed": 1,
        "times_applied": 0,
        "times_exposed": 0,
        "is_active": True,
        "created_at": datetime(2026, 3, 18, tzinfo=UTC),
        "updated_at": datetime(2026, 3, 18, tzinfo=UTC),
    }
    d.update(over)
    obj = MagicMock(spec=AgentLearning)
    for k, v in d.items():
        setattr(obj, k, v)
    return obj


def _session_returning(entry):
    """A session whose first query finds `entry` (the exact-duplicate path)."""
    calls = {"n": 0}

    async def execute(stmt):  # noqa: ARG001
        calls["n"] += 1
        r = MagicMock()
        if calls["n"] == 1:
            r.scalar_one_or_none.return_value = entry
        else:
            r.scalar_one_or_none.return_value = None
            r.scalars.return_value.all.return_value = []
        return r

    session = AsyncMock()
    session.execute = execute
    session.flush = AsyncMock()
    return session


async def _rederive(svc, entry) -> None:
    await svc.create_learning(
        _session_returning(entry),
        connection_id="conn-1",
        category="table_preference",
        subject="orders",
        lesson="Use orders_v2 instead of orders_legacy",
    )


class TestRederivationHasDiminishingReturns:
    @pytest.mark.asyncio
    async def test_the_second_rederivation_adds_less_than_the_first(self, svc):
        e = _entry(confidence=0.6, times_confirmed=1)
        await _rederive(svc, e)
        first = e.confidence - 0.6
        before = e.confidence
        await _rederive(svc, e)
        second = e.confidence - before
        assert second < first, (
            f"each repetition must count for less: first added {first:.4f}, "
            f"second added {second:.4f}"
        )

    @pytest.mark.asyncio
    async def test_repetition_alone_cannot_reach_certainty(self, svc):
        """Four submissions of one lesson used to take 0.6 to 1.0.

        Iterating far past the point where the ceiling binds, on purpose. The steps
        shrink harmonically, so their sum still grows without bound — about 55
        re-derivations would reach 1.0 on their own. A test that stopped at 40 passed
        with the ceiling raised to 1.0 and so proved nothing about it.
        """
        e = _entry(confidence=0.6, times_confirmed=1)
        for _ in range(400):
            await _rederive(svc, e)
        assert e.confidence <= 0.95, (
            f"re-derivation reached {e.confidence} — a number that reads as certainty "
            "earned from one lesson submitted repeatedly"
        )

    @pytest.mark.asyncio
    async def test_the_ceiling_is_what_stops_it_not_the_shrinking_step(self, svc):
        """Both mechanisms are load-bearing and this says which does what."""
        e = _entry(confidence=0.6, times_confirmed=1)
        for _ in range(400):
            await _rederive(svc, e)
        assert e.confidence == pytest.approx(0.95, abs=1e-9), (
            "after enough repetitions the ceiling should be exactly what is left"
        )

    @pytest.mark.asyncio
    async def test_the_count_of_confirmations_stays_honest(self, svc):
        """`times_confirmed` is a count and must keep counting; only the weight changes."""
        e = _entry(confidence=0.6, times_confirmed=1)
        await _rederive(svc, e)
        await _rederive(svc, e)
        assert e.times_confirmed == 3

    @pytest.mark.asyncio
    async def test_a_first_rederivation_still_moves_the_number(self, svc):
        """Diminishing is not zero: an independent re-derivation IS evidence."""
        e = _entry(confidence=0.6, times_confirmed=1)
        await _rederive(svc, e)
        assert e.confidence > 0.6


class TestAUserVoteKeepsItsWeight:
    def test_the_vote_path_still_reaches_certainty(self):
        """Vision §7: user feedback is the highest authority, and the `LearningVote`
        table already makes a second identical vote a no-op — so this path was never
        the pumpable one and must not be dampened with it."""
        import inspect

        from app.services import agent_learning_service as mod

        src = inspect.getsource(mod.AgentLearningService.vote_learning)
        assert "min(1.0, entry.confidence + 0.1)" in src, (
            "the upvote weight changed — a person saying 'this helped' is the strongest "
            "signal there is and should not inherit re-derivation's damping"
        )

    def test_the_two_paths_no_longer_share_one_increment(self):
        """The defect was that they did."""
        import inspect

        from app.services import agent_learning_service as mod

        create_src = inspect.getsource(mod.AgentLearningService.create_learning)
        assert "min(1.0, entry.confidence + 0.1)" not in create_src
        assert "min(1.0, similar.confidence + 0.1)" not in create_src
