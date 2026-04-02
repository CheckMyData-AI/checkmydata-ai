"""Unit tests for FeedbackPipeline (mock-based, no DB)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.feedback_pipeline import (
    FeedbackPipeline,
    _derive_learning,
    _extract_subject,
    _try_float,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_feedback(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="fb-1",
        connection_id="conn-1",
        session_id="sess-1",
        message_id="msg-1",
        query="SELECT count(*) FROM orders",
        verdict="confirmed",
        metric_description="Total orders",
        agent_value="1500",
        user_expected_value=None,
        rejection_reason=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def pipeline():
    p = FeedbackPipeline()
    p._benchmark_svc = MagicMock()
    p._benchmark_svc.create_or_confirm = AsyncMock()
    p._benchmark_svc.flag_stale = AsyncMock()

    p._notes_svc = MagicMock()
    note_mock = MagicMock()
    note_mock.id = "note-1"
    p._notes_svc.create_note = AsyncMock(return_value=note_mock)

    p._learning_svc = MagicMock()
    learning_mock = MagicMock()
    learning_mock.id = "learning-1"
    p._learning_svc.create_learning = AsyncMock(return_value=learning_mock)

    p._validation_svc = MagicMock()
    p._validation_svc.resolve = AsyncMock()

    return p


@pytest.fixture
def session():
    return AsyncMock()


# ------------------------------------------------------------------
# process() — verdict routing
# ------------------------------------------------------------------


class TestProcessConfirmed:
    @pytest.mark.asyncio
    async def test_confirmed_updates_benchmark(self, pipeline, session):
        fb = _make_feedback(verdict="confirmed")
        result = await pipeline.process(session, fb, "proj-1")

        assert result["benchmark_updated"] is True
        assert "confirmed" in result["resolution"].lower()
        pipeline._benchmark_svc.create_or_confirm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confirmed_resolves_feedback(self, pipeline, session):
        fb = _make_feedback(verdict="confirmed")
        await pipeline.process(session, fb, "proj-1")

        pipeline._validation_svc.resolve.assert_awaited_once()


class TestProcessApproximate:
    @pytest.mark.asyncio
    async def test_approximate_with_expected_value(self, pipeline, session):
        fb = _make_feedback(
            verdict="approximate",
            user_expected_value="1400",
            metric_description="Total orders",
        )
        result = await pipeline.process(session, fb, "proj-1")

        assert result["benchmark_updated"] is True
        assert len(result["notes_created"]) == 1
        pipeline._notes_svc.create_note.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_approximate_without_expected_value(self, pipeline, session):
        fb = _make_feedback(verdict="approximate", user_expected_value=None)
        result = await pipeline.process(session, fb, "proj-1")

        assert result["benchmark_updated"] is True
        assert len(result["notes_created"]) == 0
        pipeline._notes_svc.create_note.assert_not_awaited()


class TestProcessRejected:
    @pytest.mark.asyncio
    async def test_rejected_creates_note_learning_and_flags_stale(self, pipeline, session):
        fb = _make_feedback(
            verdict="rejected",
            rejection_reason="Amount is in cents not dollars",
            user_expected_value="$50,000",
        )
        result = await pipeline.process(session, fb, "proj-1")

        assert len(result["notes_created"]) >= 1
        assert len(result["learnings_created"]) >= 1
        assert "rejected" in result["resolution"].lower()
        pipeline._benchmark_svc.flag_stale.assert_awaited_once()
        pipeline._notes_svc.create_note.assert_awaited_once()
        pipeline._learning_svc.create_learning.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejected_survives_quality_check_failure(self, pipeline, session):
        """Pipeline should not crash when create_learning raises ValueError."""
        pipeline._learning_svc.create_learning = AsyncMock(
            side_effect=ValueError("Learning quality check failed: blocklisted subject")
        )
        fb = _make_feedback(
            verdict="rejected",
            rejection_reason="Wrong data returned",
            user_expected_value="100",
        )
        result = await pipeline.process(session, fb, "proj-1")

        assert len(result["notes_created"]) >= 1
        assert len(result["learnings_created"]) == 0
        assert "rejected" in result["resolution"].lower()
        pipeline._benchmark_svc.flag_stale.assert_awaited_once()


class TestProcessUnknown:
    @pytest.mark.asyncio
    async def test_unknown_verdict_no_action(self, pipeline, session):
        fb = _make_feedback(verdict="something_else")
        result = await pipeline.process(session, fb, "proj-1")

        assert result["benchmark_updated"] is False
        assert len(result["learnings_created"]) == 0
        assert len(result["notes_created"]) == 0
        assert "no automatic action" in result["resolution"].lower()


# ------------------------------------------------------------------
# _extract_subject()
# ------------------------------------------------------------------


class TestExtractSubject:
    def test_with_metric_description(self):
        fb = _make_feedback(metric_description="Revenue per user monthly")
        assert _extract_subject(fb) == "Revenue"

    def test_without_metric_description(self):
        fb = _make_feedback(metric_description=None)
        assert _extract_subject(fb) == "query_result"

    def test_empty_metric_description(self):
        fb = _make_feedback(metric_description="")
        assert _extract_subject(fb) == "query_result"


# ------------------------------------------------------------------
# _derive_learning()
# ------------------------------------------------------------------


class TestDeriveLearning:
    def test_currency_keyword(self):
        fb = _make_feedback(metric_description="Total revenue")
        cat, lesson = _derive_learning(fb, "Amount is in cents not dollars")
        assert cat == "data_format"
        assert "format" in lesson.lower() or "cents" in lesson.lower()

    def test_dollar_keyword(self):
        fb = _make_feedback(metric_description="Revenue")
        cat, _ = _derive_learning(fb, "Values stored in dollar amounts")
        assert cat == "data_format"

    def test_unit_keyword(self):
        fb = _make_feedback(metric_description="Weight")
        cat, _ = _derive_learning(fb, "Wrong unit conversion")
        assert cat == "data_format"

    def test_format_keyword(self):
        fb = _make_feedback(metric_description="Date field")
        cat, _ = _derive_learning(fb, "Date format is wrong")
        assert cat == "data_format"

    def test_filter_keyword(self):
        fb = _make_feedback(metric_description="Active users")
        cat, lesson = _derive_learning(fb, "Missing filter for active status")
        assert cat == "schema_gotcha"
        assert "filter" in lesson.lower() or "condition" in lesson.lower()

    def test_missing_keyword(self):
        fb = _make_feedback(metric_description="Count")
        cat, _ = _derive_learning(fb, "Missing rows for deleted items")
        assert cat == "schema_gotcha"

    def test_where_keyword(self):
        fb = _make_feedback(metric_description="Orders")
        cat, _ = _derive_learning(fb, "Needs where clause for status")
        assert cat == "schema_gotcha"

    def test_table_keyword(self):
        fb = _make_feedback(metric_description="Orders total")
        cat, lesson = _derive_learning(fb, "Used wrong table for orders")
        assert cat == "table_preference"
        assert "table" in lesson.lower()

    def test_legacy_keyword(self):
        fb = _make_feedback(metric_description="Users count")
        cat, _ = _derive_learning(fb, "Using legacy users table")
        assert cat == "table_preference"

    def test_join_keyword(self):
        fb = _make_feedback(metric_description="Order details")
        cat, lesson = _derive_learning(fb, "Missing join to customers")
        assert cat == "schema_gotcha"
        assert "join" in lesson.lower()

    def test_relationship_keyword(self):
        fb = _make_feedback(metric_description="Products")
        cat, _ = _derive_learning(fb, "Bad relationship between entities")
        assert cat == "schema_gotcha"

    def test_default_category(self):
        fb = _make_feedback(metric_description="Some metric")
        cat, lesson = _derive_learning(fb, "Just plain wrong")
        assert cat == "schema_gotcha"
        assert "accuracy" in lesson.lower() or "issue" in lesson.lower()


# ------------------------------------------------------------------
# _try_float()
# ------------------------------------------------------------------


class TestTryFloat:
    def test_valid_float(self):
        assert _try_float("123.45") == 123.45

    def test_integer_string(self):
        assert _try_float("42") == 42.0

    def test_strips_dollar(self):
        assert _try_float("$1,234.56") == 1234.56

    def test_strips_euro(self):
        assert _try_float("€999") == 999.0

    def test_strips_commas(self):
        assert _try_float("1,000,000") == 1_000_000.0

    def test_none_returns_none(self):
        assert _try_float(None) is None

    def test_empty_string_returns_none(self):
        assert _try_float("") is None

    def test_invalid_string_returns_none(self):
        assert _try_float("not a number") is None

    def test_whitespace_stripped(self):
        assert _try_float("  500  ") == 500.0
