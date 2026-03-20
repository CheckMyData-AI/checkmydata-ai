"""Integration test: full feedback loop.

Flow: user validates data -> feedback pipeline creates learning/note/benchmark ->
next session can use the stored knowledge.
"""

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
from app.services.benchmark_service import BenchmarkService
from app.services.data_validation_service import DataValidationService
from app.services.feedback_pipeline import FeedbackPipeline
from app.services.session_notes_service import SessionNotesService


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


class TestFullFeedbackLoop:
    @pytest.mark.asyncio
    async def test_rejection_creates_learning_and_note_used_later(self, db):
        """
        Simulates the full cycle:
        1. User receives a query result
        2. User flags it as incorrect (rejected)
        3. FeedbackPipeline creates a learning + note
        4. SessionNotesService can compile a prompt containing that note
        5. BenchmarkService shows stale benchmark
        """
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        validation_svc = DataValidationService()
        pipeline = FeedbackPipeline()
        notes_svc = SessionNotesService()
        benchmark_svc = BenchmarkService()

        # Step 1: Record agent result as a benchmark first
        await benchmark_svc.create_or_confirm(
            db, conn.id, "total_orders", "10000", value_numeric=10000.0
        )

        # Step 2: User validates the result as rejected
        fb = await validation_svc.record_validation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            message_id=str(uuid.uuid4()),
            query="SELECT count(*) FROM orders",
            verdict="rejected",
            metric_description="Total orders",
            agent_value="10000",
            user_expected_value="5000",
            rejection_reason="Missing filter for deleted orders",
        )

        # Step 3: FeedbackPipeline processes
        result = await pipeline.process(db, fb, proj.id)
        assert len(result["notes_created"]) >= 1
        assert len(result["learnings_created"]) >= 1

        # Step 4: Verify the feedback is now resolved
        resolved_fb = await validation_svc.get_by_id(db, fb.id)
        assert resolved_fb.resolved is True

        # Step 5: Session notes now contain the observation
        prompt = await notes_svc.compile_notes_prompt(db, conn.id)
        assert "REJECTED" in prompt or "Total" in prompt

        # Step 6: The benchmark for 'total_orders' should now have lower confidence
        bm = await benchmark_svc.find_benchmark(db, conn.id, metric_key="total_orders")
        assert bm is not None
        assert bm.confidence < 0.5  # was 0.5, flagged -0.3 = 0.2

    @pytest.mark.asyncio
    async def test_confirmation_strengthens_benchmark(self, db):
        """
        1. Agent derives a benchmark
        2. User confirms
        3. Benchmark gets upgraded to user_confirmed with higher confidence
        """
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        validation_svc = DataValidationService()
        pipeline = FeedbackPipeline()
        benchmark_svc = BenchmarkService()

        # Agent-derived benchmark
        bm = await benchmark_svc.create_or_confirm(
            db, conn.id, "monthly_revenue", "50000", value_numeric=50000.0
        )
        assert bm.source == "agent_derived"
        original_confidence = bm.confidence

        # User confirms
        fb = await validation_svc.record_validation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            message_id=str(uuid.uuid4()),
            query="SELECT sum(revenue) FROM sales WHERE month = 3",
            verdict="confirmed",
            metric_description="Monthly Revenue",
            agent_value="50000",
        )

        result = await pipeline.process(db, fb, proj.id)
        assert result["benchmark_updated"] is True

        # Check benchmark was upgraded
        updated_bm = await benchmark_svc.find_benchmark(db, conn.id, metric_key="monthly_revenue")
        assert updated_bm.source == "user_confirmed"
        assert updated_bm.confidence > original_confidence
        assert updated_bm.times_confirmed == 2

    @pytest.mark.asyncio
    async def test_accuracy_stats_reflect_all_feedback(self, db):
        """Multiple feedback entries create accurate stats."""
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        validation_svc = DataValidationService()
        pipeline = FeedbackPipeline()

        for verdict in ["confirmed", "confirmed", "approximate", "rejected"]:
            fb = await validation_svc.record_validation(
                db,
                connection_id=conn.id,
                session_id=sess.id,
                message_id=str(uuid.uuid4()),
                query=f"SELECT 1 -- {verdict}",
                verdict=verdict,
                metric_description=f"Test {verdict}",
                agent_value="100",
                rejection_reason="test" if verdict == "rejected" else None,
            )
            await pipeline.process(db, fb, proj.id)

        stats = await validation_svc.get_accuracy_stats(db, conn.id)
        assert stats["total"] == 4
        assert stats["confirmed"] == 2
        assert stats["approximate"] == 1
        assert stats["rejected"] == 1
        # confirmation_rate = (2 confirmed + 1 approximate) / (2 + 1 + 1 rejected) = 75%
        assert stats["confirmation_rate"] == 75.0
        assert stats["resolved"] == 4
