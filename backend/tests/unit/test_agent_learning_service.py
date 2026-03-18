"""Unit tests for AgentLearningService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.agent_learning import AgentLearning
from app.services.agent_learning_service import (
    CATEGORY_LABELS,
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


class TestCompilePrompt:
    @pytest.mark.asyncio
    async def test_compile_prompt_empty(self, svc):
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

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


class TestCategoryLabels:
    def test_all_categories_have_labels(self):
        from app.services.agent_learning_service import VALID_CATEGORIES

        for cat in VALID_CATEGORIES:
            assert cat in CATEGORY_LABELS, f"Missing label for category: {cat}"


class TestCreateLearningValidation:
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
