"""Unit tests for SessionNotesService."""

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
from app.models.connection import Connection
from app.models.project import Project
from app.services.session_notes_service import SessionNotesService

svc = SessionNotesService()


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


class TestCreateNote:
    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="orders",
            note="Amount column stores cents, not dollars.",
        )
        assert note.id is not None
        assert note.category == "data_observation"
        assert note.subject == "orders"
        assert note.confidence == 0.7
        assert note.is_verified is False
        assert note.is_active is True

    @pytest.mark.asyncio
    async def test_invalid_category_raises(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        with pytest.raises(ValueError, match="Invalid note category"):
            await svc.create_note(
                db,
                connection_id=conn.id,
                project_id=proj.id,
                category="invalid_cat",
                subject="x",
                note="y",
            )

    @pytest.mark.asyncio
    async def test_exact_duplicate_bumps_confidence(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note1 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="users",
            note="Status 1 = active, 0 = inactive.",
        )
        conf1 = note1.confidence

        note2 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="users",
            note="Status 1 = active, 0 = inactive.",
        )
        assert note2.id == note1.id
        assert note2.confidence > conf1


class TestFuzzyDedup:
    @pytest.mark.asyncio
    async def test_similar_note_merged(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note1 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="payments",
            note="Amount is stored in cents.",
        )
        note2 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="payments",
            note="The amount is stored in cents!",
        )
        assert note2.id == note1.id

    @pytest.mark.asyncio
    async def test_very_different_note_not_merged(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note1 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="payments",
            note="Amount is stored in cents.",
        )
        note2 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="payments",
            note="Use LEFT JOIN when querying payment methods.",
        )
        assert note2.id != note1.id


class TestGetNotesForContext:
    @pytest.mark.asyncio
    async def test_filters_by_connection_and_confidence(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="orders",
            note="High conf note",
            confidence=0.9,
        )
        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="orders",
            note="Very low conf note that should be totally different",
            confidence=0.1,
        )

        notes = await svc.get_notes_for_context(db, conn.id, min_confidence=0.3)
        assert len(notes) == 1
        assert "High conf" in notes[0].note

    @pytest.mark.asyncio
    async def test_filters_by_table_names(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Order status 1 = completed",
        )
        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="users",
            note="User is_active is boolean",
        )

        notes = await svc.get_notes_for_context(db, conn.id, table_names=["orders"])
        assert all("orders" in n.subject.lower() or "order" in n.note.lower() for n in notes)


class TestCompileNotesPrompt:
    @pytest.mark.asyncio
    async def test_empty_returns_empty(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        prompt = await svc.compile_notes_prompt(db, conn.id)
        assert prompt == ""

    @pytest.mark.asyncio
    async def test_compiles_prompt_with_notes(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Status 1 = completed",
            confidence=0.9,
        )
        prompt = await svc.compile_notes_prompt(db, conn.id)
        assert "AGENT NOTES" in prompt
        assert "Business Logic" in prompt
        assert "orders" in prompt


class TestVerifyAndDeactivate:
    @pytest.mark.asyncio
    async def test_verify_note(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="column_mapping",
            subject="t",
            note="Col x maps to y",
        )
        assert note.is_verified is False
        original_confidence = note.confidence

        verified = await svc.verify_note(db, note.id)
        assert verified is not None
        assert verified.is_verified is True
        assert verified.confidence > original_confidence

    @pytest.mark.asyncio
    async def test_verify_nonexistent(self, db):
        result = await svc.verify_note(db, "no-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_deactivate_note(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="x",
            note="Some observation",
        )
        result = await svc.deactivate_note(db, note.id)
        assert result is not None
        assert result.is_active is False


class TestDeleteAllForConnection:
    @pytest.mark.asyncio
    async def test_delete_all(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="a",
            note="Note 1",
        )
        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="b",
            note="Note 2 is entirely different from note 1",
        )

        count = await svc.delete_all_for_connection(db, conn.id)
        assert count == 2

        remaining = await svc.get_notes_for_context(db, conn.id, min_confidence=0.0)
        assert len(remaining) == 0
