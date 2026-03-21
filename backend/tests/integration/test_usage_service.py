"""Tests for the UsageService -- token usage recording and analytics."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.usage_service import UsageService


@pytest.fixture
def svc():
    return UsageService()


@pytest.mark.asyncio
class TestRecordUsage:
    async def test_record_basic(self, db_session: AsyncSession, svc: UsageService):
        uid = str(uuid.uuid4())
        pid = str(uuid.uuid4())
        usage = await svc.record_usage(
            db_session,
            user_id=uid,
            project_id=pid,
            provider="openai",
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert usage.total_tokens == 150
        assert usage.provider == "openai"

    async def test_total_tokens_auto_calculated(self, db_session: AsyncSession, svc: UsageService):
        uid = str(uuid.uuid4())
        pid = str(uuid.uuid4())
        usage = await svc.record_usage(
            db_session,
            user_id=uid,
            project_id=pid,
            prompt_tokens=200,
            completion_tokens=100,
        )
        assert usage.total_tokens == 300

    async def test_explicit_total_overrides(self, db_session: AsyncSession, svc: UsageService):
        uid = str(uuid.uuid4())
        pid = str(uuid.uuid4())
        usage = await svc.record_usage(
            db_session,
            user_id=uid,
            project_id=pid,
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=999,
        )
        assert usage.total_tokens == 999

    async def test_record_with_cost(self, db_session: AsyncSession, svc: UsageService):
        uid = str(uuid.uuid4())
        pid = str(uuid.uuid4())
        usage = await svc.record_usage(
            db_session,
            user_id=uid,
            project_id=pid,
            prompt_tokens=100,
            completion_tokens=50,
            estimated_cost_usd=0.0015,
        )
        assert usage.estimated_cost_usd == 0.0015


@pytest.mark.asyncio
class TestPeriodComparison:
    async def test_empty_usage(self, db_session: AsyncSession, svc: UsageService):
        uid = str(uuid.uuid4())
        result = await svc.get_period_comparison(db_session, uid, days=30)
        assert result["current_period"]["total_tokens"] == 0
        assert result["current_period"]["request_count"] == 0
        assert result["period_days"] == 30

    async def test_with_usage_data(self, db_session: AsyncSession, svc: UsageService):
        uid = str(uuid.uuid4())
        pid = str(uuid.uuid4())
        await svc.record_usage(
            db_session,
            user_id=uid,
            project_id=pid,
            prompt_tokens=100,
            completion_tokens=50,
        )
        result = await svc.get_period_comparison(db_session, uid, days=30)
        assert result["current_period"]["request_count"] >= 1
        assert result["current_period"]["total_tokens"] >= 150
