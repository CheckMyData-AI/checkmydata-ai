"""Tests for BenchmarkService and normalize_metric_key."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.benchmark_service import BenchmarkService, normalize_metric_key


class TestNormalizeMetricKey:
    def test_basic_normalization(self):
        result = normalize_metric_key("Total Revenue for March 2024")
        assert result == "total_revenue_for_march_2024"

    def test_strips_whitespace(self):
        assert normalize_metric_key("  Total Users  ") == "total_users"

    def test_replaces_special_chars(self):
        assert normalize_metric_key("Revenue ($) - Q1") == "revenue_q1"

    def test_lowercase(self):
        assert normalize_metric_key("MONTHLY ACTIVE USERS") == "monthly_active_users"

    def test_numeric_preservation(self):
        assert normalize_metric_key("Top 10 Products") == "top_10_products"

    def test_empty_string(self):
        assert normalize_metric_key("") == ""


@pytest.fixture
def svc():
    return BenchmarkService()


@pytest.mark.asyncio
class TestBenchmarkCRUD:
    async def test_create_benchmark(self, db_session: AsyncSession, svc: BenchmarkService):
        conn_id = str(uuid.uuid4())
        bm = await svc.create_or_confirm(
            db_session,
            connection_id=conn_id,
            metric_key="total_revenue",
            value="$1,000,000",
            value_numeric=1_000_000.0,
            unit="USD",
            source="user_confirmed",
        )
        assert bm.metric_key == "total_revenue"
        assert bm.confidence == 0.8

    async def test_confirm_increases_confidence(
        self, db_session: AsyncSession, svc: BenchmarkService
    ):
        conn_id = str(uuid.uuid4())
        bm1 = await svc.create_or_confirm(
            db_session,
            connection_id=conn_id,
            metric_key="daily_users",
            value="5000",
            source="agent_derived",
        )
        assert bm1.confidence == 0.5

        bm2 = await svc.create_or_confirm(
            db_session,
            connection_id=conn_id,
            metric_key="daily_users",
            value="5000",
            source="agent_derived",
        )
        assert bm2.confidence == 0.6
        assert bm2.times_confirmed == 2

    async def test_find_benchmark(self, db_session: AsyncSession, svc: BenchmarkService):
        conn_id = str(uuid.uuid4())
        await svc.create_or_confirm(
            db_session,
            connection_id=conn_id,
            metric_key="churn_rate",
            value="5%",
        )
        found = await svc.find_benchmark(db_session, conn_id, metric_key="churn_rate")
        assert found is not None
        assert found.value == "5%"

    async def test_find_by_raw_description(self, db_session: AsyncSession, svc: BenchmarkService):
        conn_id = str(uuid.uuid4())
        await svc.create_or_confirm(
            db_session,
            connection_id=conn_id,
            metric_key="monthly_revenue",
            value="$500k",
        )
        found = await svc.find_benchmark(db_session, conn_id, raw_description="Monthly Revenue")
        assert found is not None

    async def test_flag_stale_reduces_confidence(
        self, db_session: AsyncSession, svc: BenchmarkService
    ):
        conn_id = str(uuid.uuid4())
        bm = await svc.create_or_confirm(
            db_session,
            connection_id=conn_id,
            metric_key="conversion_rate",
            value="3%",
            source="user_confirmed",
        )
        initial_conf = bm.confidence

        stale = await svc.flag_stale(db_session, conn_id, "conversion_rate")
        assert stale is not None
        assert stale.confidence < initial_conf

    async def test_get_all_filters_by_min_confidence(
        self, db_session: AsyncSession, svc: BenchmarkService
    ):
        conn_id = str(uuid.uuid4())
        await svc.create_or_confirm(
            db_session,
            connection_id=conn_id,
            metric_key="high_conf",
            value="100",
            source="user_confirmed",
        )
        await svc.create_or_confirm(
            db_session,
            connection_id=conn_id,
            metric_key="low_conf",
            value="50",
            source="agent_derived",
        )
        await svc.flag_stale(db_session, conn_id, "low_conf")
        await svc.flag_stale(db_session, conn_id, "low_conf")

        all_bm = await svc.get_all_for_connection(db_session, conn_id, min_confidence=0.3)
        keys = {b.metric_key for b in all_bm}
        assert "high_conf" in keys
