"""Unit tests for AgentLearningService."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.agent_learning import AgentLearning, AgentLearningSummary, _lesson_hash
from app.services.agent_learning_service import (
    CATEGORY_LABELS,
    VALID_CATEGORIES,
    AgentLearningService,
)


@pytest.fixture
def svc():
    return AgentLearningService()


def _make_learning(**overrides) -> AgentLearning:
    defaults = {
        "id": "l1",
        "connection_id": "conn-1",
        "category": "table_preference",
        "subject": "orders",
        "lesson": "Use orders_v2 instead of orders_legacy",
        "lesson_hash": "abc123",
        "confidence": 0.7,
        "source_query": "SELECT * FROM orders_v2",
        "source_error": None,
        "times_confirmed": 1,
        "times_applied": 0,
        "is_active": True,
        "created_at": datetime(2026, 3, 18, tzinfo=UTC),
        "updated_at": datetime(2026, 3, 18, tzinfo=UTC),
    }
    defaults.update(overrides)
    entry = MagicMock(spec=AgentLearning)
    for k, v in defaults.items():
        setattr(entry, k, v)
    return entry


def _mock_session(scalar_one_or_none=None, scalars_all=None):
    session = AsyncMock()
    result_mock = MagicMock()
    if scalars_all is not None:
        result_mock.scalars.return_value.all.return_value = scalars_all
    result_mock.scalar_one_or_none.return_value = scalar_one_or_none
    result_mock.scalar_one.return_value = scalar_one_or_none
    session.execute = AsyncMock(return_value=result_mock)
    return session


class TestCompilePrompt:
    @pytest.mark.asyncio
    async def test_compile_prompt_empty(self, svc):
        session = _mock_session(scalars_all=[])
        prompt = await svc.compile_prompt(session, "conn-1")
        assert prompt == ""

    @pytest.mark.asyncio
    async def test_compile_prompt_with_learnings(self, svc):
        learnings = [
            _make_learning(
                category="table_preference",
                subject="orders_legacy",
                lesson="Use orders_v2 instead of orders_legacy",
                confidence=0.9,
                times_confirmed=3,
            ),
            _make_learning(
                id="l2",
                category="data_format",
                subject="orders_v2",
                lesson="amount column stores cents, divide by 100",
                confidence=0.8,
                times_confirmed=2,
            ),
        ]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result_mock = MagicMock()
            if call_count == 1:
                result_mock.scalars.return_value.all.return_value = learnings
            else:
                result_mock.scalar_one_or_none.return_value = None
            return result_mock

        session = AsyncMock()
        session.execute = mock_execute
        session.add = MagicMock()
        session.flush = AsyncMock()

        prompt = await svc.compile_prompt(session, "conn-1")
        assert "Table Preferences" in prompt
        assert "Data Formats" in prompt
        assert "orders_v2" in prompt
        assert "90% confidence" in prompt
        assert "3x confirmed" in prompt

    @pytest.mark.asyncio
    async def test_compile_prompt_critical_badge(self, svc):
        """Learnings with times_confirmed >= 5 get CRITICAL badge."""
        lrn = _make_learning(confidence=0.9, times_confirmed=5)
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalars.return_value.all.return_value = [lrn]
            else:
                m.scalar_one_or_none.return_value = None
            return m

        session = AsyncMock()
        session.execute = mock_execute
        session.add = MagicMock()
        session.flush = AsyncMock()

        prompt = await svc.compile_prompt(session, "conn-1")
        assert "★CRITICAL" in prompt

    @pytest.mark.asyncio
    async def test_compile_prompt_updates_existing_summary(self, svc):
        lrn = _make_learning(confidence=0.8, times_confirmed=1)
        existing_summary = MagicMock(spec=AgentLearningSummary)

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalars.return_value.all.return_value = [lrn]
            elif call_count == 2:
                m.scalar_one_or_none.return_value = None
                m.all.return_value = []
            elif call_count == 3:
                m.scalar_one_or_none.return_value = existing_summary
            else:
                m.scalar_one_or_none.return_value = None
            return m

        session = AsyncMock()
        session.execute = mock_execute
        session.flush = AsyncMock()

        await svc.compile_prompt(session, "conn-1")
        assert existing_summary.total_lessons == 1


class TestCategoryLabels:
    def test_all_categories_have_labels(self):
        for cat in VALID_CATEGORIES:
            assert cat in CATEGORY_LABELS, f"Missing label for category: {cat}"


class TestCreateLearning:
    @pytest.mark.asyncio
    async def test_invalid_category_raises(self, svc):
        session = AsyncMock()
        with pytest.raises(ValueError, match="Invalid category"):
            await svc.create_learning(
                session,
                connection_id="conn-1",
                category="invalid_cat",
                subject="test",
                lesson="test lesson",
            )

    @pytest.mark.asyncio
    async def test_exact_duplicate_confirms(self, svc):
        existing = _make_learning(confidence=0.6, times_confirmed=1)
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=result_mock)

        entry = await svc.create_learning(
            session,
            connection_id="conn-1",
            category="table_preference",
            subject="orders",
            lesson="Use orders_v2 instead of orders_legacy",
        )
        assert entry.times_confirmed == 2
        assert entry.confidence == 0.7
        assert entry.is_active is True

    @pytest.mark.asyncio
    async def test_similar_lesson_updates(self, svc):
        """Similar but not exact: longer lesson replaces shorter."""
        call_count = 0
        existing_similar = _make_learning(
            lesson="Use orders_v2 table instead of legacy",
            lesson_hash="old_hash",
            confidence=0.5,
            times_confirmed=1,
        )

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalar_one_or_none.return_value = None
            else:
                m.scalars.return_value.all.return_value = [existing_similar]
            return m

        session = AsyncMock()
        session.execute = mock_execute

        entry = await svc.create_learning(
            session,
            connection_id="conn-1",
            category="table_preference",
            subject="orders",
            lesson="Use orders_v2 table instead of legacy orders table",
        )
        assert entry.times_confirmed == 2
        assert "legacy orders table" in entry.lesson

    @pytest.mark.asyncio
    async def test_new_learning_truncates_sources(self, svc):
        """source_query is truncated to 2000 chars, source_error to 1000."""
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            m.scalar_one_or_none.return_value = None
            m.scalars.return_value.all.return_value = []
            return m

        session = AsyncMock()
        session.execute = mock_execute
        session.add = MagicMock()

        long_query = "X" * 5000
        long_error = "E" * 3000

        with patch.object(svc, "_invalidate_summary", new_callable=AsyncMock):
            entry = await svc.create_learning(
                session,
                connection_id="conn-1",
                category="table_preference",
                subject="test",
                lesson="unique lesson for truncation test",
                source_query=long_query,
                source_error=long_error,
            )
            assert len(entry.source_query) == 2000
            assert len(entry.source_error) == 1000

    @pytest.mark.asyncio
    async def test_new_learning_invalidates_summary(self, svc):
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            m.scalar_one_or_none.return_value = None
            m.scalars.return_value.all.return_value = []
            return m

        session = AsyncMock()
        session.execute = mock_execute
        session.add = MagicMock()

        with patch.object(svc, "_invalidate_summary", new_callable=AsyncMock) as mock_inv:
            await svc.create_learning(
                session,
                connection_id="conn-1",
                category="table_preference",
                subject="test",
                lesson="brand new lesson xyz",
            )
            mock_inv.assert_awaited_once_with(session, "conn-1")


class TestFindSimilar:
    @pytest.mark.asyncio
    async def test_no_candidates(self, svc):
        session = _mock_session(scalars_all=[])
        result = await svc.find_similar(session, "conn-1", "table_preference", "orders", "lesson")
        assert result is None

    @pytest.mark.asyncio
    async def test_below_threshold(self, svc):
        candidate = _make_learning(lesson="completely different text about something else")
        session = _mock_session(scalars_all=[candidate])
        result = await svc.find_similar(
            session, "conn-1", "table_preference", "orders", "use orders_v2 for everything"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_above_threshold(self, svc):
        candidate = _make_learning(lesson="Use orders_v2 instead of orders_legacy")
        session = _mock_session(scalars_all=[candidate])
        result = await svc.find_similar(
            session,
            "conn-1",
            "table_preference",
            "orders",
            "Use orders_v2 instead of orders_legacy table",
        )
        assert result is candidate


class TestConfirmLearning:
    @pytest.mark.asyncio
    async def test_not_found(self, svc):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        assert await svc.confirm_learning(session, "missing-id") is None

    @pytest.mark.asyncio
    async def test_confirm_bumps(self, svc):
        entry = _make_learning(confidence=0.5, times_confirmed=1)
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        result = await svc.confirm_learning(session, "l1")
        assert result.times_confirmed == 2
        assert result.confidence == 0.6

    @pytest.mark.asyncio
    async def test_confirm_caps_at_one(self, svc):
        entry = _make_learning(confidence=0.95, times_confirmed=10)
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        result = await svc.confirm_learning(session, "l1")
        assert result.confidence == 1.0


class TestApplyLearning:
    @pytest.mark.asyncio
    async def test_apply(self, svc):
        session = AsyncMock()
        await svc.apply_learning(session, "l1")
        session.execute.assert_awaited_once()


class TestDeactivateLearning:
    @pytest.mark.asyncio
    async def test_not_found(self, svc):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        assert await svc.deactivate_learning(session, "missing") is None

    @pytest.mark.asyncio
    async def test_deactivates(self, svc):
        entry = _make_learning(is_active=True)
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        result = await svc.deactivate_learning(session, "l1")
        assert result.is_active is False


class TestContradictLearning:
    @pytest.mark.asyncio
    async def test_not_found(self, svc):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        assert await svc.contradict_learning(session, "missing") is None

    @pytest.mark.asyncio
    async def test_reduces_confidence(self, svc):
        entry = _make_learning(confidence=0.7)
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        result = await svc.contradict_learning(session, "l1")
        assert abs(result.confidence - 0.4) < 0.001

    @pytest.mark.asyncio
    async def test_deactivates_below_threshold(self, svc):
        entry = _make_learning(confidence=0.2)
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        result = await svc.contradict_learning(session, "l1")
        assert result.confidence == 0.0
        assert result.is_active is False

    @pytest.mark.asyncio
    async def test_stays_active_above_threshold(self, svc):
        entry = _make_learning(confidence=0.5, is_active=True)
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        result = await svc.contradict_learning(session, "l1")
        assert result.confidence == 0.2
        assert result.is_active is True


class TestGetLearnings:
    @pytest.mark.asyncio
    async def test_returns_list(self, svc):
        items = [_make_learning(), _make_learning(id="l2")]
        session = _mock_session(scalars_all=items)
        result = await svc.get_learnings(session, "conn-1")
        assert len(result) == 2


class TestGetLearningsForTable:
    @pytest.mark.asyncio
    async def test_matches_subject(self, svc):
        item = _make_learning(subject="orders_table", lesson="something unrelated")
        session = _mock_session(scalars_all=[item])
        result = await svc.get_learnings_for_table(session, "conn-1", "orders_table")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_matches_lesson(self, svc):
        item = _make_learning(subject="schema", lesson="The users table has UUID PK")
        session = _mock_session(scalars_all=[item])
        result = await svc.get_learnings_for_table(session, "conn-1", "users")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_match(self, svc):
        item = _make_learning(subject="orders", lesson="use orders_v2")
        session = _mock_session(scalars_all=[item])
        result = await svc.get_learnings_for_table(session, "conn-1", "products")
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_case_insensitive(self, svc):
        item = _make_learning(subject="ORDERS", lesson="something")
        session = _mock_session(scalars_all=[item])
        result = await svc.get_learnings_for_table(session, "conn-1", "orders")
        assert len(result) == 1


class TestGetLearningById:
    @pytest.mark.asyncio
    async def test_found(self, svc):
        entry = _make_learning()
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        assert await svc.get_learning_by_id(session, "l1") is entry

    @pytest.mark.asyncio
    async def test_not_found(self, svc):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        assert await svc.get_learning_by_id(session, "missing") is None


class TestHasLearnings:
    @pytest.mark.asyncio
    async def test_has(self, svc):
        session = _mock_session(scalar_one_or_none="some-id")
        assert await svc.has_learnings(session, "conn-1") is True

    @pytest.mark.asyncio
    async def test_has_not(self, svc):
        session = _mock_session(scalar_one_or_none=None)
        assert await svc.has_learnings(session, "conn-1") is False


class TestCountLearnings:
    @pytest.mark.asyncio
    async def test_count(self, svc):
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 5
        session.execute = AsyncMock(return_value=result_mock)
        assert await svc.count_learnings(session, "conn-1") == 5


class TestUpdateLearning:
    @pytest.mark.asyncio
    async def test_not_found(self, svc):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        assert await svc.update_learning(session, "missing", lesson="new") is None

    @pytest.mark.asyncio
    async def test_update_lesson_rehashes(self, svc):
        entry = _make_learning(lesson="old lesson", lesson_hash="old_hash")
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        result = await svc.update_learning(session, "l1", lesson="new lesson text")
        assert result.lesson == "new lesson text"
        assert result.lesson_hash == _lesson_hash("new lesson text")

    @pytest.mark.asyncio
    async def test_ignores_protected_fields(self, svc):
        entry = _make_learning()
        original_id = entry.id
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        await svc.update_learning(
            session, "l1", id="hacked", connection_id="hack", created_at="hack"
        )
        assert entry.id == original_id


class TestDeleteLearning:
    @pytest.mark.asyncio
    async def test_not_found(self, svc):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        assert await svc.delete_learning(session, "missing") is False

    @pytest.mark.asyncio
    async def test_deletes_and_invalidates(self, svc):
        entry = _make_learning()
        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        result = await svc.delete_learning(session, "l1")
        assert result is True
        session.delete.assert_awaited_once()


class TestDeleteAll:
    @pytest.mark.asyncio
    async def test_no_entries(self, svc):
        session = _mock_session(scalars_all=[])
        count = await svc.delete_all(session, "conn-1")
        assert count == 0

    @pytest.mark.asyncio
    async def test_deletes_entries_and_summaries(self, svc):
        entries = [_make_learning(), _make_learning(id="l2")]
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalars.return_value.all.return_value = entries
            return m

        session = AsyncMock()
        session.execute = mock_execute
        count = await svc.delete_all(session, "conn-1")
        assert count == 2
        assert call_count == 3  # select + delete learnings + delete summaries


class TestGetOrCompileSummary:
    @pytest.mark.asyncio
    async def test_returns_cached_prompt(self, svc):
        summary = MagicMock(spec=AgentLearningSummary)
        summary.compiled_prompt = "cached prompt content"
        session = _mock_session(scalar_one_or_none=summary)

        result = await svc.get_or_compile_summary(session, "conn-1")
        assert result == "cached prompt content"

    @pytest.mark.asyncio
    async def test_compiles_when_empty(self, svc):
        summary = MagicMock(spec=AgentLearningSummary)
        summary.compiled_prompt = ""

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalar_one_or_none.return_value = summary
            else:
                m.scalars.return_value.all.return_value = []
                m.scalar_one_or_none.return_value = None
            return m

        session = AsyncMock()
        session.execute = mock_execute
        result = await svc.get_or_compile_summary(session, "conn-1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_compiles_when_no_summary(self, svc):
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            m.scalar_one_or_none.return_value = None
            m.scalars.return_value.all.return_value = []
            return m

        session = AsyncMock()
        session.execute = mock_execute
        result = await svc.get_or_compile_summary(session, "conn-1")
        assert result == ""


class TestGetSummary:
    @pytest.mark.asyncio
    async def test_found(self, svc):
        summary = MagicMock(spec=AgentLearningSummary)
        session = _mock_session(scalar_one_or_none=summary)
        assert await svc.get_summary(session, "conn-1") is summary

    @pytest.mark.asyncio
    async def test_not_found(self, svc):
        session = _mock_session(scalar_one_or_none=None)
        assert await svc.get_summary(session, "conn-1") is None


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_no_learnings(self, svc):
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalar_one.return_value = 0
            else:
                m.scalar_one_or_none.return_value = None
            return m

        session = AsyncMock()
        session.execute = mock_execute
        status = await svc.get_status(session, "conn-1")
        assert status["has_learnings"] is False
        assert status["total_active"] == 0
        assert status["categories"] == {}
        assert status["last_compiled_at"] is None

    @pytest.mark.asyncio
    async def test_with_learnings(self, svc):
        summary = MagicMock(spec=AgentLearningSummary)
        summary.last_compiled_at = datetime(2026, 3, 20, tzinfo=UTC)
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalar_one.return_value = 3
            elif call_count == 2:
                m.scalar_one_or_none.return_value = summary
            else:
                m.all.return_value = [("table_preference", 2), ("data_format", 1)]
            return m

        session = AsyncMock()
        session.execute = mock_execute
        status = await svc.get_status(session, "conn-1")
        assert status["has_learnings"] is True
        assert status["total_active"] == 3
        assert status["last_compiled_at"] is not None


class TestDecayStale:
    @pytest.mark.asyncio
    async def test_no_stale(self, svc):
        session = _mock_session(scalars_all=[])
        assert await svc.decay_stale_learnings(session) == 0

    @pytest.mark.asyncio
    async def test_decays_confidence(self, svc):
        stale = _make_learning(
            confidence=0.5,
            updated_at=datetime.now(UTC) - timedelta(days=60),
        )
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalars.return_value.all.return_value = [stale]
            else:
                m.scalar_one_or_none.return_value = None
            return m

        session = AsyncMock()
        session.execute = mock_execute
        count = await svc.decay_stale_learnings(session)
        assert count == 1
        assert stale.confidence == 0.48

    @pytest.mark.asyncio
    async def test_deactivates_very_low(self, svc):
        stale = _make_learning(
            confidence=0.19,
            is_active=True,
            updated_at=datetime.now(UTC) - timedelta(days=60),
        )
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalars.return_value.all.return_value = [stale]
            else:
                m.scalar_one_or_none.return_value = None
            return m

        session = AsyncMock()
        session.execute = mock_execute
        await svc.decay_stale_learnings(session)
        assert stale.is_active is False


class TestPriorityScore:
    def test_score_computation(self):
        lrn = _make_learning(confidence=1.0, times_confirmed=10, times_applied=5)
        score = AgentLearningService._priority_score(lrn)
        assert score > 0

    def test_higher_confidence_higher_score(self):
        high = _make_learning(confidence=1.0, times_confirmed=1, times_applied=0)
        low = _make_learning(confidence=0.3, times_confirmed=1, times_applied=0)
        assert AgentLearningService._priority_score(high) > AgentLearningService._priority_score(
            low
        )


class TestInvalidateSummary:
    @pytest.mark.asyncio
    async def test_invalidates_existing(self, svc):
        summary = MagicMock(spec=AgentLearningSummary)
        summary.compiled_prompt = "old content"
        session = _mock_session(scalar_one_or_none=summary)

        await svc._invalidate_summary(session, "conn-1")
        assert summary.compiled_prompt == ""

    @pytest.mark.asyncio
    async def test_no_summary_noop(self, svc):
        session = _mock_session(scalar_one_or_none=None)
        await svc._invalidate_summary(session, "conn-1")
        session.flush.assert_not_awaited()


class TestResolveConflicts:
    """Test the _resolve_conflicts private method."""

    @pytest.mark.asyncio
    async def test_no_existing_learnings(self, svc):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        await svc._resolve_conflicts(
            session,
            "conn-1",
            "table_preference",
            "orders",
            "always use orders_v2 table",
            0.8,
        )

    @pytest.mark.asyncio
    async def test_no_conflict_indicators_in_new(self, svc):
        session = AsyncMock()
        old = _make_learning(lesson="something plain")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [old]
        session.execute = AsyncMock(return_value=mock_result)

        await svc._resolve_conflicts(
            session,
            "conn-1",
            "table_preference",
            "orders",
            "hello world test",
            0.8,
        )
        assert old.is_active is True

    @pytest.mark.asyncio
    async def test_negation_flip_deactivates_old(self, svc):
        session = AsyncMock()
        old = _make_learning(
            lesson="always use column_a for filtering",
            confidence=0.5,
            is_active=True,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [old]
        session.execute = AsyncMock(return_value=mock_result)

        await svc._resolve_conflicts(
            session,
            "conn-1",
            "table_preference",
            "orders",
            "never use column_a for filtering queries in production environment",
            0.8,
        )
        assert old.is_active is False

    @pytest.mark.asyncio
    async def test_similar_lesson_skipped(self, svc):
        session = AsyncMock()
        old = _make_learning(
            lesson="always use orders_v2 table",
            confidence=0.5,
            is_active=True,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [old]
        session.execute = AsyncMock(return_value=mock_result)

        await svc._resolve_conflicts(
            session,
            "conn-1",
            "table_preference",
            "orders",
            "always use orders_v2 table",
            0.8,
        )
        assert old.is_active is True

    @pytest.mark.asyncio
    async def test_no_shared_action_words_skipped(self, svc):
        session = AsyncMock()
        old = _make_learning(
            lesson="avoid using table_x for joins",
            confidence=0.5,
            is_active=True,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [old]
        session.execute = AsyncMock(return_value=mock_result)

        await svc._resolve_conflicts(
            session,
            "conn-1",
            "table_preference",
            "orders",
            "not select from different_table in production context completely unrelated",
            0.8,
        )
        assert old.is_active is True

    @pytest.mark.asyncio
    async def test_old_higher_confidence_stays(self, svc):
        session = AsyncMock()
        old = _make_learning(
            lesson="always use column_a for filtering",
            confidence=0.9,
            is_active=True,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [old]
        session.execute = AsyncMock(return_value=mock_result)

        await svc._resolve_conflicts(
            session,
            "conn-1",
            "table_preference",
            "orders",
            "never use column_a for filtering queries in production environment",
            0.5,
        )
        assert old.is_active is True


class TestUpdateLearningNonLesson:
    @pytest.mark.asyncio
    async def test_update_non_lesson_field(self, svc):
        session = AsyncMock()
        entry = _make_learning(category="table_preference", subject="orders")
        session.get = AsyncMock(return_value=entry)
        session.flush = AsyncMock()

        with patch.object(svc, "_invalidate_summary", new_callable=AsyncMock):
            result = await svc.update_learning(session, "l1", category="schema_gotcha")

        assert result is not None
        assert result.category == "schema_gotcha"


class TestGetCrossConnectionLearnings:
    @pytest.mark.asyncio
    async def test_returns_formatted_lines(self, svc):
        session = AsyncMock()

        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = "proj-1"

        sibling_result = MagicMock()
        sibling_result.all.return_value = [("conn-2",), ("conn-3",)]

        sibling_learning = _make_learning(
            id="sl1",
            connection_id="conn-2",
            category="schema_gotcha",
            lesson="Watch out for datetime timezone",
            lesson_hash="hash-sibling",
            confidence=0.8,
        )
        learning_result = MagicMock()
        learning_result.scalars.return_value.all.return_value = [sibling_learning]

        session.execute = AsyncMock(side_effect=[proj_result, sibling_result, learning_result])

        lines = await svc._get_cross_connection_learnings(session, "conn-1", set())
        assert len(lines) == 1
        assert "[from sibling]" in lines[0]
        assert "80% confidence" in lines[0]

    @pytest.mark.asyncio
    async def test_no_project_returns_empty(self, svc):
        session = AsyncMock()
        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=proj_result)

        lines = await svc._get_cross_connection_learnings(session, "conn-1", set())
        assert lines == []

    @pytest.mark.asyncio
    async def test_no_siblings_returns_empty(self, svc):
        session = AsyncMock()

        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = "proj-1"

        sibling_result = MagicMock()
        sibling_result.all.return_value = []

        session.execute = AsyncMock(side_effect=[proj_result, sibling_result])

        lines = await svc._get_cross_connection_learnings(session, "conn-1", set())
        assert lines == []

    @pytest.mark.asyncio
    async def test_excludes_duplicate_hashes(self, svc):
        session = AsyncMock()

        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = "proj-1"

        sibling_result = MagicMock()
        sibling_result.all.return_value = [("conn-2",)]

        sibling_learning = _make_learning(
            lesson_hash="already-seen-hash",
            confidence=0.8,
        )
        learning_result = MagicMock()
        learning_result.scalars.return_value.all.return_value = [sibling_learning]

        session.execute = AsyncMock(side_effect=[proj_result, sibling_result, learning_result])

        lines = await svc._get_cross_connection_learnings(session, "conn-1", {"already-seen-hash"})
        assert lines == []


class TestCompilePromptCrossConnection:
    @pytest.mark.asyncio
    async def test_prompt_includes_cross_connection(self, svc):
        session = AsyncMock()

        learning = _make_learning()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [learning]

        summary_result = MagicMock()
        summary_result.scalar_one_or_none.return_value = None

        session.execute = AsyncMock(side_effect=[mock_result, summary_result])

        with patch.object(
            svc,
            "_get_cross_connection_learnings",
            new_callable=AsyncMock,
            return_value=["- [from sibling] Use ISO dates [80% confidence]"],
        ):
            prompt = await svc.compile_prompt(session, "conn-1")

        assert "From Similar Connections" in prompt
        assert "[from sibling]" in prompt
