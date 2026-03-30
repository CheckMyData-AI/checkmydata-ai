"""Unit tests for LogsService — query logic, aggregation, pagination."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register all models
from app.models.base import Base
from app.models.project import Project
from app.models.request_trace import RequestTrace, TraceSpan
from app.models.user import User
from app.services.logs_service import LogsService

svc = LogsService()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _user(db: AsyncSession) -> User:
    u = User(
        email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        password_hash="fake",
        display_name="Tester",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _project(db: AsyncSession) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _trace(
    db: AsyncSession,
    project_id: str,
    user_id: str,
    *,
    status: str = "completed",
    question: str = "test?",
    tokens: int = 100,
    llm_calls: int = 1,
    db_queries: int = 0,
    duration_ms: float = 500.0,
    cost: float | None = None,
    created_at: datetime | None = None,
) -> RequestTrace:
    t = RequestTrace(
        project_id=project_id,
        user_id=user_id,
        workflow_id=str(uuid.uuid4()),
        question=question,
        status=status,
        total_tokens=tokens,
        total_llm_calls=llm_calls,
        total_db_queries=db_queries,
        total_duration_ms=duration_ms,
        estimated_cost_usd=cost,
    )
    if created_at:
        t.created_at = created_at
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _span(
    db: AsyncSession,
    trace_id: str,
    *,
    span_type: str = "llm_call",
    name: str = "orchestrator:llm_call",
    status: str = "completed",
    order: int = 0,
    duration_ms: float | None = 100.0,
) -> TraceSpan:
    s = TraceSpan(
        trace_id=trace_id,
        span_type=span_type,
        name=name,
        status=status,
        order_index=order,
        duration_ms=duration_ms,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


class TestGetUsers:
    @pytest.mark.asyncio
    async def test_empty(self, db):
        proj = await _project(db)
        result = await svc.get_users(db, proj.id, days=30)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_user_with_count(self, db):
        proj = await _project(db)
        user = await _user(db)
        await _trace(db, proj.id, user.id)
        await _trace(db, proj.id, user.id)

        result = await svc.get_users(db, proj.id, days=30)
        assert len(result) == 1
        assert result[0]["user_id"] == user.id
        assert result[0]["request_count"] == 2
        assert result[0]["display_name"] == "Tester"


class TestListRequests:
    @pytest.mark.asyncio
    async def test_pagination(self, db):
        proj = await _project(db)
        user = await _user(db)
        for _ in range(5):
            await _trace(db, proj.id, user.id)

        result = await svc.list_requests(db, proj.id, page=1, page_size=3)
        assert result["total"] == 5
        assert len(result["items"]) == 3
        assert result["page"] == 1

        result2 = await svc.list_requests(db, proj.id, page=2, page_size=3)
        assert len(result2["items"]) == 2

    @pytest.mark.asyncio
    async def test_filter_by_status(self, db):
        proj = await _project(db)
        user = await _user(db)
        await _trace(db, proj.id, user.id, status="completed")
        await _trace(db, proj.id, user.id, status="failed")

        result = await svc.list_requests(db, proj.id, status="failed")
        assert result["total"] == 1
        assert result["items"][0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_filter_by_user(self, db):
        proj = await _project(db)
        u1 = await _user(db)
        u2 = await _user(db)
        await _trace(db, proj.id, u1.id)
        await _trace(db, proj.id, u2.id)

        result = await svc.list_requests(db, proj.id, user_id=u1.id)
        assert result["total"] == 1


class TestGetTraceDetail:
    @pytest.mark.asyncio
    async def test_not_found(self, db):
        proj = await _project(db)
        result = await svc.get_trace_detail(db, proj.id, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_trace_with_spans(self, db):
        proj = await _project(db)
        user = await _user(db)
        t = await _trace(db, proj.id, user.id)
        await _span(db, t.id, span_type="llm_call", order=0)
        await _span(db, t.id, span_type="db_query", name="execute_query", order=1)

        result = await svc.get_trace_detail(db, proj.id, t.id)
        assert result is not None
        assert result["trace"]["id"] == t.id
        assert len(result["spans"]) == 2
        assert result["spans"][0]["span_type"] == "llm_call"
        assert result["spans"][1]["span_type"] == "db_query"

    @pytest.mark.asyncio
    async def test_wrong_project(self, db):
        proj = await _project(db)
        proj2 = await _project(db)
        user = await _user(db)
        t = await _trace(db, proj.id, user.id)

        result = await svc.get_trace_detail(db, proj2.id, t.id)
        assert result is None


class TestGetSummary:
    @pytest.mark.asyncio
    async def test_empty_summary(self, db):
        proj = await _project(db)
        result = await svc.get_summary(db, proj.id, days=7)
        assert result["total_requests"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_summary_counts(self, db):
        proj = await _project(db)
        user = await _user(db)
        await _trace(db, proj.id, user.id, status="completed", tokens=200, llm_calls=2, db_queries=1, cost=0.01)
        await _trace(db, proj.id, user.id, status="failed", tokens=50, llm_calls=1, cost=0.005)

        result = await svc.get_summary(db, proj.id, days=7)
        assert result["total_requests"] == 2
        assert result["successful"] == 1
        assert result["failed"] == 1
        assert result["total_llm_calls"] == 3
        assert result["total_db_queries"] == 1
        assert result["total_tokens"] == 250
