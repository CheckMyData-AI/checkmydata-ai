"""Unit tests for NoteService."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

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
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.project import Project
from app.models.user import User
from app.services.note_service import NoteService

svc = NoteService()


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


class TestNoteCreate:
    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        note = await svc.create(
            db,
            project_id=proj.id,
            user_id=user.id,
            title="My Query",
            sql_query="SELECT 1",
        )
        assert note.id is not None
        assert note.title == "My Query"
        assert note.sql_query == "SELECT 1"
        assert note.project_id == proj.id
        assert note.user_id == user.id
        assert note.connection_id is None
        assert note.comment is None
        assert note.last_result_json is None

    @pytest.mark.asyncio
    async def test_create_with_result_and_comment(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        note = await svc.create(
            db,
            project_id=proj.id,
            user_id=user.id,
            title="With Data",
            sql_query="SELECT * FROM t",
            comment="Important query",
            last_result_json='{"columns":["a"],"rows":[[1]],"total_rows":1}',
        )
        assert note.comment == "Important query"
        assert note.last_result_json is not None


class TestNoteGet:
    @pytest.mark.asyncio
    async def test_get_existing(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        note = await svc.create(
            db, project_id=proj.id, user_id=user.id, title="Get", sql_query="SELECT 1"
        )
        fetched = await svc.get(db, note.id)
        assert fetched is not None
        assert fetched.id == note.id

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, db):
        result = await svc.get(db, "no-such-id")
        assert result is None


class TestNoteListByProject:
    @pytest.mark.asyncio
    async def test_scope_mine_returns_only_own_notes(self, db):
        proj = await _make_project(db)
        u1 = await _make_user(db)
        u2 = await _make_user(db)

        await svc.create(db, project_id=proj.id, user_id=u1.id, title="Mine", sql_query="SELECT 1")
        await svc.create(
            db, project_id=proj.id, user_id=u2.id, title="Theirs", sql_query="SELECT 2"
        )

        notes = await svc.list_by_project(db, proj.id, u1.id, scope="mine")
        assert len(notes) == 1
        assert notes[0].title == "Mine"

    @pytest.mark.asyncio
    async def test_scope_shared_returns_others_shared_notes(self, db):
        proj = await _make_project(db)
        u1 = await _make_user(db)
        u2 = await _make_user(db)

        await svc.create(
            db,
            project_id=proj.id,
            user_id=u1.id,
            title="My Private",
            sql_query="SELECT 1",
            is_shared=False,
        )
        await svc.create(
            db,
            project_id=proj.id,
            user_id=u2.id,
            title="Other Shared",
            sql_query="SELECT 2",
            is_shared=True,
        )
        await svc.create(
            db,
            project_id=proj.id,
            user_id=u2.id,
            title="Other Private",
            sql_query="SELECT 3",
            is_shared=False,
        )
        await svc.create(
            db,
            project_id=proj.id,
            user_id=u1.id,
            title="My Shared",
            sql_query="SELECT 4",
            is_shared=True,
        )

        notes = await svc.list_by_project(db, proj.id, u1.id, scope="shared")
        titles = {n.title for n in notes}
        assert titles == {"Other Shared"}

    @pytest.mark.asyncio
    async def test_scope_all_returns_own_plus_shared(self, db):
        proj = await _make_project(db)
        u1 = await _make_user(db)
        u2 = await _make_user(db)

        await svc.create(db, project_id=proj.id, user_id=u1.id, title="Mine", sql_query="SELECT 1")
        await svc.create(
            db,
            project_id=proj.id,
            user_id=u2.id,
            title="Other Shared",
            sql_query="SELECT 2",
            is_shared=True,
        )
        await svc.create(
            db,
            project_id=proj.id,
            user_id=u2.id,
            title="Other Private",
            sql_query="SELECT 3",
            is_shared=False,
        )

        notes = await svc.list_by_project(db, proj.id, u1.id, scope="all")
        titles = {n.title for n in notes}
        assert titles == {"Mine", "Other Shared"}

    @pytest.mark.asyncio
    async def test_list_filters_across_projects(self, db):
        p1 = await _make_project(db)
        p2 = await _make_project(db)
        user = await _make_user(db)

        await svc.create(db, project_id=p1.id, user_id=user.id, title="P1", sql_query="SELECT 1")
        await svc.create(db, project_id=p2.id, user_id=user.id, title="P2", sql_query="SELECT 2")

        notes = await svc.list_by_project(db, p1.id, user.id)
        assert len(notes) == 1
        assert notes[0].title == "P1"

    @pytest.mark.asyncio
    async def test_list_empty_project(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        notes = await svc.list_by_project(db, proj.id, user.id)
        assert notes == []


class TestNoteUpdate:
    @pytest.mark.asyncio
    async def test_update_allowed_fields(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        note = await svc.create(
            db, project_id=proj.id, user_id=user.id, title="Old", sql_query="SELECT 1"
        )
        updated = await svc.update(
            db, note.id, title="New Title", comment="Added comment", is_shared=True
        )
        assert updated is not None
        assert updated.title == "New Title"
        assert updated.comment == "Added comment"
        assert updated.is_shared is True

    @pytest.mark.asyncio
    async def test_update_disallowed_fields_ignored(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        note = await svc.create(
            db, project_id=proj.id, user_id=user.id, title="Safe", sql_query="SELECT 1"
        )
        original_query = note.sql_query
        original_project = note.project_id
        updated = await svc.update(db, note.id, sql_query="DROP TABLE users", project_id="hacked")
        assert updated is not None
        assert updated.sql_query == original_query
        assert updated.project_id == original_project

    @pytest.mark.asyncio
    async def test_update_missing_returns_none(self, db):
        result = await svc.update(db, "bad-id", title="x")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_sets_updated_at(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        note = await svc.create(
            db, project_id=proj.id, user_id=user.id, title="TS", sql_query="SELECT 1"
        )
        old_updated = note.updated_at
        updated = await svc.update(db, note.id, title="TS Changed")
        assert updated is not None
        assert updated.updated_at >= old_updated


class TestNoteUpdateResult:
    @pytest.mark.asyncio
    async def test_sets_result_and_timestamps(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        note = await svc.create(
            db, project_id=proj.id, user_id=user.id, title="T", sql_query="SELECT 1"
        )
        assert note.last_executed_at is None
        assert note.last_result_json is None

        result_json = '{"columns":["x"],"rows":[[42]],"total_rows":1}'
        updated = await svc.update_result(db, note.id, result_json)
        assert updated is not None
        assert updated.last_result_json == result_json
        assert updated.last_executed_at is not None
        assert updated.updated_at is not None

    @pytest.mark.asyncio
    async def test_clears_result_with_none(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        note = await svc.create(
            db,
            project_id=proj.id,
            user_id=user.id,
            title="T",
            sql_query="SELECT 1",
            last_result_json='{"old":"data"}',
        )
        updated = await svc.update_result(db, note.id, None)
        assert updated is not None
        assert updated.last_result_json is None
        assert updated.last_executed_at is not None

    @pytest.mark.asyncio
    async def test_update_result_missing_returns_none(self, db):
        result = await svc.update_result(db, "bad-id", '{"data":1}')
        assert result is None


class TestNoteDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        note = await svc.create(
            db, project_id=proj.id, user_id=user.id, title="Del", sql_query="SELECT 1"
        )
        result = await svc.delete(db, note.id)
        assert result is True
        assert await svc.get(db, note.id) is None

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, db):
        result = await svc.delete(db, "no-id")
        assert result is False
