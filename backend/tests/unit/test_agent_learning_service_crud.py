"""Unit tests for AgentLearningService CRUD, deduplication, and confidence logic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.agent_learning import AgentLearning, _lesson_hash
from app.services.agent_learning_service import (
    AgentLearningService,
)


@pytest.fixture
def svc():
    return AgentLearningService()


def _real_learning(**overrides) -> AgentLearning:
    defaults = {
        "id": "l1",
        "connection_id": "conn-1",
        "category": "table_preference",
        "subject": "orders",
        "lesson": "Use orders_v2 instead of orders_legacy",
        "lesson_hash": _lesson_hash("Use orders_v2 instead of orders_legacy"),
        "confidence": 0.7,
        "source_query": None,
        "source_error": None,
        "times_confirmed": 1,
        "times_applied": 0,
        "is_active": True,
        "created_at": datetime(2026, 3, 18, tzinfo=UTC),
        "updated_at": datetime(2026, 3, 18, tzinfo=UTC),
    }
    defaults.update(overrides)
    obj = MagicMock(spec=AgentLearning)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_session(scalars_all=None, scalar_one_or_none=None, get_result=None):
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = scalars_all or []
    result_mock.scalar_one_or_none.return_value = scalar_one_or_none
    result_mock.scalar_one.return_value = 0
    session.execute = AsyncMock(return_value=result_mock)
    session.get = AsyncMock(return_value=get_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


class TestCreateLearning:
    @pytest.mark.asyncio
    async def test_create_new_learning(self, svc):
        session = _make_session()
        await svc.create_learning(
            session,
            connection_id="conn-1",
            category="table_preference",
            subject="orders",
            lesson="Use orders_v2",
        )
        session.add.assert_called_once()
        session.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_exact_duplicate_bumps_confidence(self, svc):
        existing = _real_learning(confidence=0.6, times_confirmed=1)

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                r.scalar_one_or_none.return_value = existing
            else:
                r.scalar_one_or_none.return_value = None
                r.scalars.return_value.all.return_value = []
            return r

        session = AsyncMock()
        session.execute = mock_execute
        session.flush = AsyncMock()

        result = await svc.create_learning(
            session,
            connection_id="conn-1",
            category="table_preference",
            subject="orders",
            lesson="Use orders_v2 instead of orders_legacy",
        )
        assert result == existing
        assert existing.times_confirmed == 2
        assert existing.confidence == pytest.approx(0.7, abs=0.01)

    @pytest.mark.asyncio
    async def test_fuzzy_duplicate_merges(self, svc):
        similar = _real_learning(
            confidence=0.6,
            times_confirmed=1,
            lesson="Use orders_v2 instead of orders_legacy for revenue",
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                r.scalar_one_or_none.return_value = None
            else:
                r.scalars.return_value.all.return_value = [similar]
            return r

        session = AsyncMock()
        session.execute = mock_execute
        session.flush = AsyncMock()

        longer_lesson = "Use orders_v2 instead of orders_legacy for revenue queries in reports"
        result = await svc.create_learning(
            session,
            connection_id="conn-1",
            category="table_preference",
            subject="orders",
            lesson=longer_lesson,
        )
        assert result == similar
        assert similar.times_confirmed == 2
        assert similar.lesson == longer_lesson

    @pytest.mark.asyncio
    async def test_invalid_category_raises(self, svc):
        session = AsyncMock()
        with pytest.raises(ValueError, match="Invalid category"):
            await svc.create_learning(
                session,
                connection_id="conn-1",
                category="bad_category",
                subject="test",
                lesson="test lesson",
            )

    @pytest.mark.asyncio
    async def test_different_category_is_not_duplicate(self, svc):
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            r.scalars.return_value.all.return_value = []
            return r

        session = AsyncMock()
        session.execute = mock_execute
        session.add = MagicMock()
        session.flush = AsyncMock()

        await svc.create_learning(
            session,
            "conn-1",
            "column_usage",
            "orders",
            "Use total_amount",
        )
        session.add.assert_called_once()


class TestFindSimilar:
    @pytest.mark.asyncio
    async def test_above_threshold_returns_match(self, svc):
        candidate = _real_learning(lesson="Use orders_v2 instead of orders_legacy")
        session = _make_session(scalars_all=[candidate])

        result = await svc.find_similar(
            session,
            "conn-1",
            "table_preference",
            "orders",
            "Use orders_v2 not orders_legacy",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_below_threshold_returns_none(self, svc):
        candidate = _real_learning(lesson="Use orders_v2 instead of orders_legacy")
        session = _make_session(scalars_all=[candidate])

        result = await svc.find_similar(
            session,
            "conn-1",
            "table_preference",
            "orders",
            "Completely different lesson about something else entirely",
        )
        assert result is None


class TestConfirmLearning:
    @pytest.mark.asyncio
    async def test_increments_confidence_and_count(self, svc):
        entry = _real_learning(confidence=0.6, times_confirmed=1)
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        session.flush = AsyncMock()

        result = await svc.confirm_learning(session, "l1")
        assert result is not None
        assert entry.times_confirmed == 2
        assert entry.confidence == pytest.approx(0.7, abs=0.01)

    @pytest.mark.asyncio
    async def test_caps_at_1(self, svc):
        entry = _real_learning(confidence=0.95, times_confirmed=5)
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        session.flush = AsyncMock()

        await svc.confirm_learning(session, "l1")
        assert entry.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self, svc):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        result = await svc.confirm_learning(session, "missing")
        assert result is None


class TestContradictLearning:
    @pytest.mark.asyncio
    async def test_decreases_confidence(self, svc):
        entry = _real_learning(confidence=0.7)
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        session.flush = AsyncMock()

        result = await svc.contradict_learning(session, "l1")
        assert result is not None
        assert entry.confidence == pytest.approx(0.4, abs=0.01)
        assert entry.is_active is True

    @pytest.mark.asyncio
    async def test_deactivates_below_threshold(self, svc):
        entry = _real_learning(confidence=0.05)
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        session.flush = AsyncMock()

        await svc.contradict_learning(session, "l1")
        assert entry.confidence == 0.0
        assert entry.is_active is False


class TestApplyLearning:
    @pytest.mark.asyncio
    async def test_increments_applied(self, svc):
        session = AsyncMock()
        session.execute = AsyncMock()

        await svc.apply_learning(session, "l1")
        session.execute.assert_awaited_once()


class TestDeactivateLearning:
    @pytest.mark.asyncio
    async def test_sets_inactive(self, svc):
        entry = _real_learning(is_active=True)
        session = _make_session(get_result=entry, scalar_one_or_none=None)

        result = await svc.deactivate_learning(session, "l1")
        assert result is not None
        assert entry.is_active is False


class TestGetLearnings:
    @pytest.mark.asyncio
    async def test_min_confidence_filter(self, svc):
        session = _make_session(scalars_all=[])
        result = await svc.get_learnings(session, "conn-1", min_confidence=0.5)
        session.execute.assert_awaited_once()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_learnings(self, svc):
        entries = [_real_learning(), _real_learning(id="l2")]
        session = _make_session(scalars_all=entries)
        result = await svc.get_learnings(session, "conn-1")
        assert len(result) == 2


class TestGetLearningsForTable:
    @pytest.mark.asyncio
    async def test_filters_by_table_name(self, svc):
        match = _real_learning(subject="users", lesson="Filter users by active")
        no_match = _real_learning(id="l2", subject="orders", lesson="Orders table tip")
        session = _make_session(scalars_all=[match, no_match])

        result = await svc.get_learnings_for_table(session, "conn-1", "users")
        assert any("users" in str(getattr(r, "subject", "")) for r in result)


class TestCountLearnings:
    @pytest.mark.asyncio
    async def test_returns_count(self, svc):
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 5
        session.execute = AsyncMock(return_value=result_mock)

        count = await svc.count_learnings(session, "conn-1")
        assert count == 5


class TestDecayStale:
    @pytest.mark.asyncio
    async def test_decays_old_learnings(self, svc):
        old_date = datetime.now(UTC) - timedelta(days=45)
        entry = _real_learning(confidence=0.5, updated_at=old_date)

        session = AsyncMock()
        stale_result = MagicMock()
        stale_result.scalars.return_value.all.return_value = [entry]
        summary_result = MagicMock()
        summary_result.scalar_one_or_none.return_value = None

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return stale_result
            return summary_result

        session.execute = mock_execute
        session.flush = AsyncMock()

        affected = await svc.decay_stale_learnings(session)
        assert affected == 1
        assert entry.confidence == pytest.approx(0.48, abs=0.01)

    @pytest.mark.asyncio
    async def test_deactivates_very_low_confidence(self, svc):
        old_date = datetime.now(UTC) - timedelta(days=45)
        entry = _real_learning(confidence=0.15, updated_at=old_date)

        session = AsyncMock()
        stale_result = MagicMock()
        stale_result.scalars.return_value.all.return_value = [entry]
        summary_result = MagicMock()
        summary_result.scalar_one_or_none.return_value = None

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return stale_result
            return summary_result

        session.execute = mock_execute
        session.flush = AsyncMock()

        await svc.decay_stale_learnings(session)
        assert entry.confidence < 0.2
        assert entry.is_active is False
