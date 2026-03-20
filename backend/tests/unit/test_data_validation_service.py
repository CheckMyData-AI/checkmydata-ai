"""Unit tests for DataValidationService."""

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

svc = DataValidationService()


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


class TestRecordValidation:
    @pytest.mark.asyncio
    async def test_record_basic(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb = await svc.record_validation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            message_id=str(uuid.uuid4()),
            query="SELECT count(*) FROM orders",
            verdict="confirmed",
        )
        assert fb.id is not None
        assert fb.verdict == "confirmed"
        assert fb.resolved is False

    @pytest.mark.asyncio
    async def test_record_with_rejection(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb = await svc.record_validation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            message_id=str(uuid.uuid4()),
            query="SELECT sum(amount) FROM payments",
            verdict="rejected",
            rejection_reason="Numbers are in cents, not dollars",
            user_expected_value="$1,500",
            agent_value="150000",
        )
        assert fb.verdict == "rejected"
        assert fb.rejection_reason == "Numbers are in cents, not dollars"


class TestGetMethods:
    @pytest.mark.asyncio
    async def test_get_by_id(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb = await svc.record_validation(
            db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1", "confirmed"
        )
        fetched = await svc.get_by_id(db, fb.id)
        assert fetched is not None
        assert fetched.id == fb.id

    @pytest.mark.asyncio
    async def test_get_by_id_nonexistent(self, db):
        result = await svc.get_by_id(db, "no-such-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_message_id(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)
        msg_id = str(uuid.uuid4())

        await svc.record_validation(db, conn.id, sess.id, msg_id, "SELECT 1", "confirmed")
        result = await svc.get_by_message_id(db, msg_id)
        assert result is not None
        assert result.message_id == msg_id


class TestGetUnresolved:
    @pytest.mark.asyncio
    async def test_returns_unresolved_only(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb1 = await svc.record_validation(
            db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1", "rejected"
        )
        await svc.record_validation(
            db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 2", "confirmed"
        )
        await svc.resolve(db, fb1.id, "Fixed")

        unresolved = await svc.get_unresolved(db, conn.id)
        assert len(unresolved) == 1
        assert unresolved[0].verdict == "confirmed"


class TestResolve:
    @pytest.mark.asyncio
    async def test_resolve(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        fb = await svc.record_validation(
            db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1", "rejected"
        )
        resolved = await svc.resolve(db, fb.id, "Learning created")
        assert resolved is not None
        assert resolved.resolved is True
        assert resolved.resolution == "Learning created"

    @pytest.mark.asyncio
    async def test_resolve_nonexistent(self, db):
        result = await svc.resolve(db, "no-id", "test")
        assert result is None


class TestAccuracyStats:
    @pytest.mark.asyncio
    async def test_empty_stats(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        stats = await svc.get_accuracy_stats(db, conn.id)
        assert stats["total"] == 0
        assert stats["confirmation_rate"] is None

    @pytest.mark.asyncio
    async def test_stats_with_data(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        await svc.record_validation(db, conn.id, sess.id, str(uuid.uuid4()), "q1", "confirmed")
        await svc.record_validation(db, conn.id, sess.id, str(uuid.uuid4()), "q2", "confirmed")
        await svc.record_validation(db, conn.id, sess.id, str(uuid.uuid4()), "q3", "rejected")

        stats = await svc.get_accuracy_stats(db, conn.id)
        assert stats["total"] == 3
        assert stats["confirmed"] == 2
        assert stats["rejected"] == 1
        assert stats["confirmation_rate"] is not None
        assert 60 < stats["confirmation_rate"] < 70
