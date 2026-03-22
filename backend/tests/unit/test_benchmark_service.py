"""Unit tests for BenchmarkService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.benchmark import DataBenchmark
from app.services.benchmark_service import BenchmarkService, normalize_metric_key


@pytest.fixture
def svc():
    return BenchmarkService()


def _make_benchmark(**overrides) -> DataBenchmark:
    defaults = {
        "id": "bm1",
        "connection_id": "conn-1",
        "metric_key": "monthly_revenue",
        "metric_description": "Total monthly revenue",
        "value": "125000",
        "value_numeric": 125000.0,
        "unit": "USD",
        "confidence": 0.8,
        "source": "user_confirmed",
        "times_confirmed": 1,
        "last_confirmed_at": datetime(2026, 3, 18, tzinfo=UTC),
        "created_at": datetime(2026, 3, 18, tzinfo=UTC),
    }
    defaults.update(overrides)
    entry = MagicMock(spec=DataBenchmark)
    for k, v in defaults.items():
        setattr(entry, k, v)
    return entry


def _mock_session(scalar_one_or_none=None, scalars_all=None):
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_one_or_none
    if scalars_all is not None:
        result_mock.scalars.return_value.all.return_value = scalars_all
    session.execute = AsyncMock(return_value=result_mock)
    return session


class TestNormalizeMetricKey:
    def test_basic(self):
        assert normalize_metric_key("Monthly Revenue") == "monthly_revenue"

    def test_special_chars(self):
        assert normalize_metric_key("  Revenue ($) — Q1  ") == "revenue_q1"

    def test_digits(self):
        assert normalize_metric_key("Q4 2024 Revenue") == "q4_2024_revenue"

    def test_empty(self):
        assert normalize_metric_key("") == ""

    def test_consecutive_separators(self):
        assert normalize_metric_key("a---b___c") == "a_b_c"


class TestFindBenchmark:
    @pytest.mark.asyncio
    async def test_by_metric_key(self, svc):
        bm = _make_benchmark()
        session = _mock_session(scalar_one_or_none=bm)
        result = await svc.find_benchmark(session, "conn-1", metric_key="monthly_revenue")
        assert result is bm

    @pytest.mark.asyncio
    async def test_by_raw_description(self, svc):
        bm = _make_benchmark()
        session = _mock_session(scalar_one_or_none=bm)
        result = await svc.find_benchmark(session, "conn-1", raw_description="Monthly Revenue")
        assert result is bm

    @pytest.mark.asyncio
    async def test_no_key_no_desc_returns_none(self, svc):
        session = _mock_session()
        result = await svc.find_benchmark(session, "conn-1")
        assert result is None
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_key_falls_through_to_desc(self, svc):
        bm = _make_benchmark()
        session = _mock_session(scalar_one_or_none=bm)
        result = await svc.find_benchmark(
            session, "conn-1", metric_key="", raw_description="Monthly Revenue"
        )
        assert result is bm

    @pytest.mark.asyncio
    async def test_key_takes_precedence(self, svc):
        bm = _make_benchmark()
        session = _mock_session(scalar_one_or_none=bm)
        result = await svc.find_benchmark(
            session, "conn-1", metric_key="my_key", raw_description="Different Desc"
        )
        assert result is bm

    @pytest.mark.asyncio
    async def test_not_found(self, svc):
        session = _mock_session(scalar_one_or_none=None)
        result = await svc.find_benchmark(session, "conn-1", metric_key="unknown")
        assert result is None


class TestCreateOrConfirm:
    @pytest.mark.asyncio
    async def test_new_agent_derived(self, svc):
        """New benchmark with agent_derived source gets confidence=0.5."""
        session = _mock_session(scalar_one_or_none=None)
        session.add = MagicMock()

        await svc.create_or_confirm(
            session,
            "conn-1",
            "total_users",
            "5000",
            value_numeric=5000.0,
            unit="count",
            source="agent_derived",
        )
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_user_confirmed(self, svc):
        """New benchmark with user_confirmed source gets confidence=0.8."""
        session = _mock_session(scalar_one_or_none=None)
        session.add = MagicMock()

        await svc.create_or_confirm(
            session,
            "conn-1",
            "total_users",
            "5000",
            source="user_confirmed",
        )
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_existing_bumps(self, svc):
        existing = _make_benchmark(confidence=0.5, times_confirmed=1, source="agent_derived")
        session = _mock_session(scalar_one_or_none=existing)

        await svc.create_or_confirm(
            session,
            "conn-1",
            "monthly_revenue",
            "130000",
            value_numeric=130000.0,
            source="agent_derived",
        )
        assert existing.times_confirmed == 2
        assert existing.confidence == 0.6
        assert existing.value == "130000"
        assert existing.value_numeric == 130000.0

    @pytest.mark.asyncio
    async def test_confirm_promotes_source(self, svc):
        existing = _make_benchmark(source="agent_derived")
        session = _mock_session(scalar_one_or_none=existing)

        await svc.create_or_confirm(
            session,
            "conn-1",
            "monthly_revenue",
            "125000",
            source="user_confirmed",
        )
        assert existing.source == "user_confirmed"

    @pytest.mark.asyncio
    async def test_confirm_caps_confidence(self, svc):
        existing = _make_benchmark(confidence=0.95, times_confirmed=10)
        session = _mock_session(scalar_one_or_none=existing)

        await svc.create_or_confirm(
            session,
            "conn-1",
            "monthly_revenue",
            "125000",
        )
        assert existing.confidence == 1.0

    @pytest.mark.asyncio
    async def test_spaces_in_key_normalize(self, svc):
        """metric_key with spaces gets normalized."""
        session = _mock_session(scalar_one_or_none=None)
        session.add = MagicMock()

        await svc.create_or_confirm(
            session,
            "conn-1",
            "Monthly Revenue",
            "125000",
        )
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_description_defaults_to_key(self, svc):
        """When metric_description is empty, it defaults to metric_key."""
        session = _mock_session(scalar_one_or_none=None)
        session.add = MagicMock()

        await svc.create_or_confirm(
            session,
            "conn-1",
            "total_users",
            "5000",
            metric_description="",
        )
        session.add.assert_called_once()


class TestFlagStale:
    @pytest.mark.asyncio
    async def test_not_found(self, svc):
        session = _mock_session(scalar_one_or_none=None)
        result = await svc.flag_stale(session, "conn-1", "unknown_metric")
        assert result is None

    @pytest.mark.asyncio
    async def test_reduces_confidence(self, svc):
        bm = _make_benchmark(confidence=0.8)
        session = _mock_session(scalar_one_or_none=bm)
        result = await svc.flag_stale(session, "conn-1", "monthly_revenue")
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_floor_at_zero(self, svc):
        bm = _make_benchmark(confidence=0.1)
        session = _mock_session(scalar_one_or_none=bm)
        result = await svc.flag_stale(session, "conn-1", "monthly_revenue")
        assert result.confidence == 0.0


class TestGetAllForConnection:
    @pytest.mark.asyncio
    async def test_returns_list(self, svc):
        items = [_make_benchmark(), _make_benchmark(id="bm2", metric_key="total_users")]
        session = _mock_session(scalars_all=items)
        result = await svc.get_all_for_connection(session, "conn-1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty(self, svc):
        session = _mock_session(scalars_all=[])
        result = await svc.get_all_for_connection(session, "conn-1")
        assert result == []
