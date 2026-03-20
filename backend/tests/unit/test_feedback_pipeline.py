"""Unit tests for FeedbackPipeline."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.agent_learning  # noqa: F401
import app.models.benchmark  # noqa: F401
import app.models.chat_session  # noqa: F401
import app.models.code_db_sync  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.data_validation  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.saved_note  # noqa: F401
import app.models.session_note  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.chat_session import ChatSession
from app.models.connection import Connection
from app.models.project import Project
from app.services.data_validation_service import DataValidationService
from app.services.feedback_pipeline import FeedbackPipeline

validation_svc = DataValidationService()
pipeline = FeedbackPipeline()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_project(db: AsyncSession) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _make_connection(db: AsyncSession, project_id: str) -> Connection:
    c = Connection(
        project_id=project_id,
        name=f"conn-{uuid.uuid4().hex[:6]}",
        db_type="postgresql",
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_user="user",
        db_password_encrypted="fake",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _make_session(db: AsyncSession, project_id: str) -> ChatSession:
    s = ChatSession(project_id=project_id, title="test")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


class TestConfirmedVerdict:
    @pytest.mark.asyncio
    async def test_confirmed_creates_benchmark(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb = await validation_svc.record_validation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            message_id=str(uuid.uuid4()),
            query="SELECT count(*) FROM orders",
            verdict="confirmed",
            metric_description="Total orders",
            agent_value="1500",
        )

        result = await pipeline.process(db, fb, proj.id)
        assert result["benchmark_updated"] is True
        assert "confirmed" in result["resolution"].lower()

        refreshed = await validation_svc.get_by_id(db, fb.id)
        assert refreshed.resolved is True


class TestApproximateVerdict:
    @pytest.mark.asyncio
    async def test_approximate_creates_benchmark_and_note(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb = await validation_svc.record_validation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            message_id=str(uuid.uuid4()),
            query="SELECT sum(amount) FROM payments",
            verdict="approximate",
            metric_description="Total payments",
            agent_value="15200",
            user_expected_value="15000",
        )

        result = await pipeline.process(db, fb, proj.id)
        assert result["benchmark_updated"] is True
        assert len(result["notes_created"]) == 1
        assert "approximate" in result["resolution"].lower()

    @pytest.mark.asyncio
    async def test_approximate_without_expected_value_no_note(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb = await validation_svc.record_validation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            message_id=str(uuid.uuid4()),
            query="SELECT count(*) FROM users",
            verdict="approximate",
            metric_description="User count",
            agent_value="500",
        )

        result = await pipeline.process(db, fb, proj.id)
        assert result["benchmark_updated"] is True
        assert len(result["notes_created"]) == 0


class TestRejectedVerdict:
    @pytest.mark.asyncio
    async def test_rejected_creates_learning_and_note(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb = await validation_svc.record_validation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            message_id=str(uuid.uuid4()),
            query="SELECT sum(amount) FROM transactions",
            verdict="rejected",
            metric_description="Total revenue",
            agent_value="5000000",
            user_expected_value="$50,000",
            rejection_reason="Amount is in cents, not dollars",
        )

        result = await pipeline.process(db, fb, proj.id)
        assert len(result["notes_created"]) >= 1
        assert len(result["learnings_created"]) >= 1
        assert "rejected" in result["resolution"].lower()

    @pytest.mark.asyncio
    async def test_rejected_with_filter_reason(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb = await validation_svc.record_validation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            message_id=str(uuid.uuid4()),
            query="SELECT count(*) FROM payments",
            verdict="rejected",
            metric_description="Active payments",
            agent_value="10000",
            user_expected_value="5000",
            rejection_reason="Missing filter for status column",
        )

        result = await pipeline.process(db, fb, proj.id)
        assert len(result["learnings_created"]) >= 1


class TestUnknownVerdict:
    @pytest.mark.asyncio
    async def test_unknown_does_nothing_special(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb = await validation_svc.record_validation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            message_id=str(uuid.uuid4()),
            query="SELECT 1",
            verdict="unknown",
        )

        result = await pipeline.process(db, fb, proj.id)
        assert result["benchmark_updated"] is False
        assert len(result["learnings_created"]) == 0
        assert len(result["notes_created"]) == 0
