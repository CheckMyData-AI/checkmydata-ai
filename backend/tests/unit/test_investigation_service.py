"""Unit tests for InvestigationService."""

import json
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
from app.services.investigation_service import InvestigationService

svc = InvestigationService()


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


class TestCreateInvestigation:
    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            trigger_message_id=str(uuid.uuid4()),
            original_query="SELECT count(*) FROM orders",
            user_complaint_type="numbers_too_high",
            user_expected_value="1000",
        )
        assert inv.id is not None
        assert inv.status == "collecting_info"
        assert inv.phase == "collect_info"
        assert inv.user_complaint_type == "numbers_too_high"

    @pytest.mark.asyncio
    async def test_create_with_all_fields(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(
            db,
            connection_id=conn.id,
            session_id=sess.id,
            trigger_message_id=str(uuid.uuid4()),
            original_query="SELECT sum(amount) FROM payments",
            original_result_summary='{"sum": 5000000}',
            user_complaint_type="numbers_too_high",
            user_complaint_detail="Amount is in cents",
            user_expected_value="$50,000",
            problematic_column="amount",
        )
        assert inv.original_result_summary == '{"sum": 5000000}'
        assert inv.problematic_column == "amount"


class TestUpdatePhase:
    @pytest.mark.asyncio
    async def test_update_phase_with_log(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1")

        updated = await svc.update_phase(
            db, inv.id, "investigating", "investigate", "Checking column formats"
        )
        assert updated is not None
        assert updated.status == "investigating"
        assert updated.phase == "investigate"

        log = json.loads(updated.investigation_log_json)
        assert len(log) == 1
        assert log[0]["detail"] == "Checking column formats"

    @pytest.mark.asyncio
    async def test_update_phase_appends_to_log(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1")
        await svc.update_phase(db, inv.id, "investigating", "investigate", "Step 1")
        updated = await svc.update_phase(db, inv.id, "investigating", "investigate", "Step 2")

        log = json.loads(updated.investigation_log_json)
        assert len(log) == 2

    @pytest.mark.asyncio
    async def test_update_phase_nonexistent(self, db):
        result = await svc.update_phase(db, "no-id", "investigating", "investigate")
        assert result is None


class TestRecordFinding:
    @pytest.mark.asyncio
    async def test_record_finding(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(
            db, conn.id, sess.id, str(uuid.uuid4()), "SELECT sum(amount) FROM payments"
        )

        updated = await svc.record_finding(
            db,
            inv.id,
            corrected_query="SELECT sum(amount) / 100 FROM payments",
            root_cause="Amount stored in cents, not dollars",
            root_cause_category="data_format",
        )
        assert updated is not None
        assert updated.status == "presenting_fix"
        assert updated.corrected_query == "SELECT sum(amount) / 100 FROM payments"
        assert updated.root_cause_category == "data_format"

    @pytest.mark.asyncio
    async def test_record_finding_nonexistent(self, db):
        result = await svc.record_finding(db, "no-id")
        assert result is None


class TestCompleteInvestigation:
    @pytest.mark.asyncio
    async def test_complete(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1")
        await svc.record_finding(db, inv.id, root_cause="Fixed")
        completed = await svc.complete_investigation(
            db,
            inv.id,
            learnings_created=["l1", "l2"],
            notes_created=["n1"],
        )
        assert completed is not None
        assert completed.status == "resolved"
        assert completed.completed_at is not None
        assert json.loads(completed.learnings_created_json) == ["l1", "l2"]

    @pytest.mark.asyncio
    async def test_complete_nonexistent(self, db):
        result = await svc.complete_investigation(db, "no-id")
        assert result is None


class TestFailInvestigation:
    @pytest.mark.asyncio
    async def test_fail(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1")
        failed = await svc.fail_investigation(db, inv.id, "Could not determine root cause")
        assert failed is not None
        assert failed.status == "failed"
        assert failed.root_cause == "Could not determine root cause"


class TestGetMethods:
    @pytest.mark.asyncio
    async def test_get_investigation(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1")
        fetched = await svc.get_investigation(db, inv.id)
        assert fetched is not None
        assert fetched.id == inv.id

    @pytest.mark.asyncio
    async def test_get_active_investigation(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        await svc.create_investigation(db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1")
        active = await svc.get_active_investigation(db, sess.id)
        assert active is not None

    @pytest.mark.asyncio
    async def test_no_active_after_resolved(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1")
        await svc.complete_investigation(db, inv.id)

        active = await svc.get_active_investigation(db, sess.id)
        assert active is None


class TestUpdatePhaseEdgeCases:
    @pytest.mark.asyncio
    async def test_update_phase_with_corrupted_log_json(self, db):
        """When investigation_log_json is invalid JSON, it should reset to empty list."""
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1")
        inv.investigation_log_json = "not valid json!!!"
        await db.flush()

        updated = await svc.update_phase(
            db, inv.id, "investigating", "investigate", "Step after corruption"
        )
        log = json.loads(updated.investigation_log_json)
        assert len(log) == 1
        assert log[0]["detail"] == "Step after corruption"


class TestRecordFindingEdgeCases:
    @pytest.mark.asyncio
    async def test_record_finding_with_result_json(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1")
        updated = await svc.record_finding(
            db,
            inv.id,
            corrected_result_json='{"total": 50000}',
        )
        assert updated is not None
        assert updated.corrected_result_json == '{"total": 50000}'


class TestCompleteInvestigationEdgeCases:
    @pytest.mark.asyncio
    async def test_complete_with_benchmarks(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        sess = await _make_session(db, proj.id)

        inv = await svc.create_investigation(db, conn.id, sess.id, str(uuid.uuid4()), "SELECT 1")
        completed = await svc.complete_investigation(
            db, inv.id, benchmarks_updated=["b1", "b2"]
        )
        assert completed is not None
        assert json.loads(completed.benchmarks_updated_json) == ["b1", "b2"]


class TestFailInvestigationEdgeCases:
    @pytest.mark.asyncio
    async def test_fail_nonexistent(self, db):
        result = await svc.fail_investigation(db, "no-such-id", "reason")
        assert result is None
