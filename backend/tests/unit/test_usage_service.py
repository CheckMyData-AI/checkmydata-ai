"""Unit tests for UsageService."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.batch_query  # noqa: F401
import app.models.chat_session  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.repository  # noqa: F401
import app.models.saved_note  # noqa: F401
import app.models.scheduled_query  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.token_usage  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.chat_session import ChatSession
from app.models.connection import Connection
from app.models.project import Project
from app.models.token_usage import TokenUsage
from app.models.user import User
from app.services.usage_service import UsageService

svc = UsageService()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_user(db: AsyncSession) -> User:
    u = User(
        email=f"user-{uuid.uuid4().hex[:6]}@test.com",
        password_hash="fake",
        display_name="Test",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_project(db: AsyncSession) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _make_connection(db: AsyncSession, project_id: str) -> Connection:
    c = Connection(
        project_id=project_id,
        name="test-conn",
        db_type="postgresql",
        db_port=5432,
        db_name="testdb",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _make_session(
    db: AsyncSession,
    project_id: str,
    user_id: str,
    connection_id: str | None = None,
) -> ChatSession:
    s = ChatSession(
        project_id=project_id,
        user_id=user_id,
        connection_id=connection_id,
        title="Test Session",
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _insert_usage(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int | None = None,
    cost: float | None = None,
    created_at: datetime | None = None,
) -> TokenUsage:
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens
    row = TokenUsage(
        user_id=user_id,
        project_id=project_id,
        provider="openai",
        model="gpt-4",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=cost,
    )
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


class TestRecordUsage:
    @pytest.mark.asyncio
    async def test_basic(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)

        row = await svc.record_usage(
            db,
            user_id=user.id,
            project_id=proj.id,
            provider="openai",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )

        assert row.id is not None
        assert row.user_id == user.id
        assert row.project_id == proj.id
        assert row.provider == "openai"
        assert row.model == "gpt-4"
        assert row.prompt_tokens == 100
        assert row.completion_tokens == 50

    @pytest.mark.asyncio
    async def test_calculates_total_tokens_when_none(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)

        row = await svc.record_usage(
            db,
            user_id=user.id,
            project_id=proj.id,
            prompt_tokens=200,
            completion_tokens=80,
        )
        assert row.total_tokens == 280

    @pytest.mark.asyncio
    async def test_explicit_total_tokens(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)

        row = await svc.record_usage(
            db,
            user_id=user.id,
            project_id=proj.id,
            prompt_tokens=200,
            completion_tokens=80,
            total_tokens=999,
        )
        assert row.total_tokens == 999

    @pytest.mark.asyncio
    async def test_with_cost(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)

        row = await svc.record_usage(
            db,
            user_id=user.id,
            project_id=proj.id,
            prompt_tokens=100,
            completion_tokens=50,
            estimated_cost_usd=0.0035,
        )
        assert row.estimated_cost_usd == pytest.approx(0.0035)

    @pytest.mark.asyncio
    async def test_with_session_and_message(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        chat = await _make_session(db, proj.id, user.id, conn.id)
        msg_id = str(uuid.uuid4())

        row = await svc.record_usage(
            db,
            user_id=user.id,
            project_id=proj.id,
            session_id=chat.id,
            message_id=msg_id,
            prompt_tokens=10,
            completion_tokens=5,
        )
        assert row.session_id == chat.id
        assert row.message_id == msg_id

    @pytest.mark.asyncio
    async def test_defaults_provider_and_model(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)

        row = await svc.record_usage(
            db,
            user_id=user.id,
            project_id=proj.id,
        )
        assert row.provider == "unknown"
        assert row.model == "unknown"
        assert row.prompt_tokens == 0
        assert row.completion_tokens == 0
        assert row.total_tokens == 0


class TestGetPeriodComparison:
    @pytest.mark.asyncio
    async def test_no_data_returns_zeros(self, db):
        user = await _make_user(db)

        result = await svc.get_period_comparison(db, user.id, days=30)

        assert result["period_days"] == 30
        assert result["current_period"]["total_tokens"] == 0
        assert result["current_period"]["request_count"] == 0
        assert result["previous_period"]["total_tokens"] == 0
        assert result["daily_breakdown"] == []

    @pytest.mark.asyncio
    async def test_with_current_period_data(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)

        now = datetime.now(UTC)
        await _insert_usage(
            db,
            user.id,
            proj.id,
            prompt_tokens=100,
            completion_tokens=50,
            created_at=now - timedelta(days=5),
        )
        await _insert_usage(
            db,
            user.id,
            proj.id,
            prompt_tokens=200,
            completion_tokens=100,
            created_at=now - timedelta(days=3),
        )

        result = await svc.get_period_comparison(db, user.id, days=30)

        assert result["current_period"]["prompt_tokens"] == 300
        assert result["current_period"]["completion_tokens"] == 150
        assert result["current_period"]["total_tokens"] == 450
        assert result["current_period"]["request_count"] == 2

    @pytest.mark.asyncio
    async def test_change_percent_calculation(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)

        now = datetime.now(UTC)
        await _insert_usage(
            db,
            user.id,
            proj.id,
            prompt_tokens=100,
            completion_tokens=0,
            created_at=now - timedelta(days=45),
        )
        await _insert_usage(
            db,
            user.id,
            proj.id,
            prompt_tokens=200,
            completion_tokens=0,
            created_at=now - timedelta(days=5),
        )

        result = await svc.get_period_comparison(db, user.id, days=30)

        assert result["change_percent"]["prompt_tokens"] == 100.0

    @pytest.mark.asyncio
    async def test_change_percent_no_previous(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)

        now = datetime.now(UTC)
        await _insert_usage(
            db,
            user.id,
            proj.id,
            prompt_tokens=500,
            completion_tokens=0,
            created_at=now - timedelta(days=5),
        )

        result = await svc.get_period_comparison(db, user.id, days=30)

        assert result["change_percent"]["prompt_tokens"] == 100.0
        assert result["change_percent"]["total_tokens"] == 100.0

    @pytest.mark.asyncio
    async def test_daily_breakdown(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)

        now = datetime.now(UTC)
        day1 = now - timedelta(days=5)
        day2 = now - timedelta(days=3)
        await _insert_usage(
            db, user.id, proj.id, prompt_tokens=100, completion_tokens=50, created_at=day1
        )
        await _insert_usage(
            db, user.id, proj.id, prompt_tokens=200, completion_tokens=100, created_at=day2
        )

        result = await svc.get_period_comparison(db, user.id, days=30)

        breakdown = result["daily_breakdown"]
        assert len(breakdown) == 2
        assert all("date" in d for d in breakdown)
        assert all("total_tokens" in d for d in breakdown)
        total = sum(d["total_tokens"] for d in breakdown)
        assert total == 450


class TestAggregatePeriod:
    @pytest.mark.asyncio
    async def test_returns_correct_sums(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)

        now = datetime.now(UTC)
        start = now - timedelta(days=10)
        await _insert_usage(
            db,
            user.id,
            proj.id,
            prompt_tokens=100,
            completion_tokens=50,
            cost=0.01,
            created_at=now - timedelta(days=5),
        )
        await _insert_usage(
            db,
            user.id,
            proj.id,
            prompt_tokens=200,
            completion_tokens=100,
            cost=0.02,
            created_at=now - timedelta(days=3),
        )
        await _insert_usage(
            db,
            user.id,
            proj.id,
            prompt_tokens=999,
            completion_tokens=999,
            created_at=now - timedelta(days=15),
        )

        result = await svc._aggregate_period(db, user.id, start, now)

        assert result["prompt_tokens"] == 300
        assert result["completion_tokens"] == 150
        assert result["total_tokens"] == 450
        assert result["request_count"] == 2
        assert result["estimated_cost_usd"] == pytest.approx(0.03, abs=1e-4)

    @pytest.mark.asyncio
    async def test_empty_period(self, db):
        user = await _make_user(db)

        now = datetime.now(UTC)
        result = await svc._aggregate_period(db, user.id, now - timedelta(days=30), now)

        assert result["prompt_tokens"] == 0
        assert result["total_tokens"] == 0
        assert result["request_count"] == 0
        assert result["estimated_cost_usd"] is None
