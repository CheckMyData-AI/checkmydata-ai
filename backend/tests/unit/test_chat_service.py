"""Unit tests for ChatService – in-memory SQLite, no mocks."""

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.agent_learning  # noqa: F401
import app.models.benchmark  # noqa: F401
import app.models.code_db_sync  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.data_validation  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.saved_note  # noqa: F401
import app.models.session_note  # noqa: F401
import app.models.ssh_key  # noqa: F401
from app.models.base import Base
from app.models.project import Project
from app.models.user import User
from app.services.chat_service import ChatService

svc = ChatService()


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


async def _make_user(db: AsyncSession) -> User:
    u = User(
        email=f"{uuid.uuid4().hex[:8]}@test.com",
        display_name="Test User",
        auth_provider="email",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_create_with_defaults(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id)

        assert chat.id is not None
        assert chat.project_id == proj.id
        assert chat.title == "New Chat"
        assert chat.user_id is None
        assert chat.connection_id is None
        assert chat.created_at is not None

    @pytest.mark.asyncio
    async def test_create_with_all_params(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        chat = await svc.create_session(
            db,
            project_id=proj.id,
            title="Custom Title",
            user_id=user.id,
            connection_id=None,
        )

        assert chat.title == "Custom Title"
        assert chat.user_id == user.id
        assert chat.project_id == proj.id


class TestGetSession:
    @pytest.mark.asyncio
    async def test_returns_session_with_messages(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id, title="With Msgs")
        await svc.add_message(db, chat.id, "user", "Hello")
        await svc.add_message(db, chat.id, "assistant", "Hi back")

        fetched = await svc.get_session(db, chat.id)

        assert fetched is not None
        assert fetched.id == chat.id
        assert fetched.title == "With Msgs"
        assert len(fetched.messages) == 2
        assert fetched.messages[0].role == "user"
        assert fetched.messages[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_id(self, db):
        result = await svc.get_session(db, "nonexistent-id")
        assert result is None


class TestListSessions:
    @pytest.mark.asyncio
    async def test_returns_project_sessions(self, db):
        proj = await _make_project(db)
        proj2 = await _make_project(db)
        await svc.create_session(db, project_id=proj.id, title="A")
        await svc.create_session(db, project_id=proj.id, title="B")
        await svc.create_session(db, project_id=proj2.id, title="Other")

        sessions = await svc.list_sessions(db, project_id=proj.id)

        assert len(sessions) == 2
        titles = {s.title for s in sessions}
        assert titles == {"A", "B"}

    @pytest.mark.asyncio
    async def test_filters_by_user_id(self, db):
        proj = await _make_project(db)
        user = await _make_user(db)
        user2 = await _make_user(db)

        await svc.create_session(db, project_id=proj.id, title="User1", user_id=user.id)
        await svc.create_session(db, project_id=proj.id, title="User2", user_id=user2.id)
        await svc.create_session(db, project_id=proj.id, title="NoUser", user_id=None)

        sessions = await svc.list_sessions(db, project_id=proj.id, user_id=user.id)

        titles = {s.title for s in sessions}
        assert "User1" in titles
        assert "NoUser" in titles
        assert "User2" not in titles

    @pytest.mark.asyncio
    async def test_skip_and_limit(self, db):
        proj = await _make_project(db)
        for i in range(5):
            await svc.create_session(db, project_id=proj.id, title=f"S{i}")

        page = await svc.list_sessions(db, project_id=proj.id, skip=1, limit=2)

        assert len(page) == 2


class TestAddMessage:
    @pytest.mark.asyncio
    async def test_add_with_role_and_content(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id)

        msg = await svc.add_message(db, chat.id, "user", "Hello world")

        assert msg.id is not None
        assert msg.session_id == chat.id
        assert msg.role == "user"
        assert msg.content == "Hello world"
        assert msg.metadata_json is None
        assert msg.tool_calls_json is None
        assert msg.created_at is not None

    @pytest.mark.asyncio
    async def test_add_with_metadata_json_serialization(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id)
        meta = {"query": "SELECT 1", "row_count": 42}

        msg = await svc.add_message(db, chat.id, "assistant", "Result", metadata=meta)

        assert msg.metadata_json is not None
        parsed = json.loads(msg.metadata_json)
        assert parsed["query"] == "SELECT 1"
        assert parsed["row_count"] == 42

    @pytest.mark.asyncio
    async def test_add_with_tool_calls_json(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id)
        tc = json.dumps([{"name": "run_sql", "args": {"q": "SELECT 1"}}])

        msg = await svc.add_message(db, chat.id, "assistant", "Done", tool_calls_json=tc)

        assert msg.tool_calls_json == tc
        parsed = json.loads(msg.tool_calls_json)
        assert parsed[0]["name"] == "run_sql"


class TestGetHistoryAsMessages:
    @pytest.mark.asyncio
    async def test_empty_session(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id)

        history = await svc.get_history_as_messages(db, chat.id)

        assert history == []

    @pytest.mark.asyncio
    async def test_enriches_assistant_metadata(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id)

        meta = {
            "query": "SELECT name FROM users",
            "viz_type": "bar",
            "row_count": 10,
            "raw_result": {
                "columns": ["name", "age"],
                "rows": [["Alice", 30], ["Bob", 25], ["Carol", 28]],
            },
        }
        await svc.add_message(db, chat.id, "user", "Show users")
        await svc.add_message(db, chat.id, "assistant", "Here are the users", metadata=meta)

        history = await svc.get_history_as_messages(db, chat.id)

        assert len(history) == 2
        user_msg = history[0]
        assert user_msg.role == "user"
        assert user_msg.content == "Show users"

        asst_msg = history[1]
        assert asst_msg.role == "assistant"
        assert "SQL Query: SELECT name FROM users" in asst_msg.content
        assert "Visualization: bar" in asst_msg.content
        assert "Rows: 10" in asst_msg.content
        assert "Columns: name, age" in asst_msg.content
        assert "Sample data:" in asst_msg.content
        assert "[Context:" in asst_msg.content

    @pytest.mark.asyncio
    async def test_respects_limit(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id)

        for i in range(10):
            await svc.add_message(db, chat.id, "user", f"Msg {i}")

        history = await svc.get_history_as_messages(db, chat.id, limit=3)

        assert len(history) == 3
        assert history[0].content == "Msg 7"
        assert history[2].content == "Msg 9"

    @pytest.mark.asyncio
    async def test_nonexistent_session_returns_empty(self, db):
        history = await svc.get_history_as_messages(db, "nonexistent-id")
        assert history == []


class TestUpdateSessionTitle:
    @pytest.mark.asyncio
    async def test_update_success(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id, title="Old Title")

        updated = await svc.update_session_title(db, chat.id, "New Title")

        assert updated is not None
        assert updated.title == "New Title"
        assert updated.id == chat.id

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self, db):
        result = await svc.update_session_title(db, "nonexistent-id", "Whatever")
        assert result is None


class TestGetHistoryAsMessagesMalformed:
    @pytest.mark.asyncio
    async def test_with_malformed_metadata(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id)
        msg = await svc.add_message(db, chat.id, "assistant", "answer")
        msg.metadata_json = "not-json{"
        await db.commit()
        msgs = await svc.get_history_as_messages(db, chat.id)
        assert len(msgs) == 1

    @pytest.mark.asyncio
    async def test_nonexistent_session(self, db):
        msgs = await svc.get_history_as_messages(db, "nonexistent-id")
        assert msgs == []


class TestDeleteSession:
    @pytest.mark.asyncio
    async def test_delete_success(self, db):
        proj = await _make_project(db)
        chat = await svc.create_session(db, project_id=proj.id)
        await svc.add_message(db, chat.id, "user", "To be deleted")

        result = await svc.delete_session(db, chat.id)

        assert result is True
        assert await svc.get_session(db, chat.id) is None

    @pytest.mark.asyncio
    async def test_returns_false_for_missing(self, db):
        result = await svc.delete_session(db, "nonexistent-id")
        assert result is False
