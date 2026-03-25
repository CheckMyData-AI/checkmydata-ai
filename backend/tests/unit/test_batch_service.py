"""Unit tests for BatchService."""

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

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
from app.connectors.base import ConnectionConfig, QueryResult
from app.models.base import Base
from app.models.connection import Connection
from app.models.project import Project
from app.models.saved_note import SavedNote
from app.models.user import User
from app.services.batch_service import BatchService
from app.services.batch_service import _conn_svc as _conn_svc_ref

svc = BatchService()


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


async def _make_note(
    db: AsyncSession, project_id: str, user_id: str, title: str = "Note", sql: str = "SELECT 1"
) -> SavedNote:
    n = SavedNote(
        project_id=project_id,
        user_id=user_id,
        title=title,
        sql_query=sql,
    )
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return n


class TestCreateBatch:
    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        queries = [{"sql": "SELECT 1", "title": "Q1"}]
        batch = await svc.create_batch(db, user.id, proj.id, conn.id, "My Batch", queries)

        assert batch.id is not None
        assert batch.user_id == user.id
        assert batch.project_id == proj.id
        assert batch.connection_id == conn.id
        assert batch.title == "My Batch"
        assert batch.status == "pending"
        assert batch.results_json is None
        assert batch.completed_at is None

    @pytest.mark.asyncio
    async def test_create_with_note_ids_loads_notes(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        note1 = await _make_note(db, proj.id, user.id, "Note A", "SELECT a FROM t")
        note2 = await _make_note(db, proj.id, user.id, "Note B", "SELECT b FROM t")

        queries = [{"sql": "SELECT 0", "title": "Manual"}]
        batch = await svc.create_batch(
            db, user.id, proj.id, conn.id, "With Notes", queries, note_ids=[note1.id, note2.id]
        )

        stored = json.loads(batch.queries_json)
        assert len(stored) == 3
        assert stored[0]["sql"] == "SELECT 0"
        assert stored[1]["sql"] == "SELECT a FROM t"
        assert stored[1]["title"] == "Note A"
        assert stored[2]["sql"] == "SELECT b FROM t"
        assert stored[2]["title"] == "Note B"

    @pytest.mark.asyncio
    async def test_create_stores_queries_json_correctly(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        queries = [
            {"sql": "SELECT 1", "title": "First"},
            {"sql": "SELECT 2", "title": "Second"},
        ]
        batch = await svc.create_batch(db, user.id, proj.id, conn.id, "JSON Test", queries)

        parsed = json.loads(batch.queries_json)
        assert parsed == queries

    @pytest.mark.asyncio
    async def test_create_with_note_ids_stores_note_ids_json(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        note = await _make_note(db, proj.id, user.id)

        batch = await svc.create_batch(
            db, user.id, proj.id, conn.id, "NoteIDs", [], note_ids=[note.id]
        )

        assert batch.note_ids_json is not None
        assert json.loads(batch.note_ids_json) == [note.id]

    @pytest.mark.asyncio
    async def test_create_without_note_ids_has_null_note_ids_json(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        batch = await svc.create_batch(db, user.id, proj.id, conn.id, "No Notes", [])
        assert batch.note_ids_json is None


class TestGetBatch:
    @pytest.mark.asyncio
    async def test_get_existing(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        batch = await svc.create_batch(
            db, user.id, proj.id, conn.id, "Get", [{"sql": "SELECT 1", "title": "Q"}]
        )

        fetched = await svc.get_batch(db, batch.id)
        assert fetched is not None
        assert fetched.id == batch.id
        assert fetched.title == "Get"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, db):
        result = await svc.get_batch(db, "nonexistent-id")
        assert result is None


class TestListBatches:
    @pytest.mark.asyncio
    async def test_filters_by_project_and_user(self, db):
        u1 = await _make_user(db)
        u2 = await _make_user(db)
        p1 = await _make_project(db)
        p2 = await _make_project(db)
        c1 = await _make_connection(db, p1.id)
        c2 = await _make_connection(db, p2.id)

        await svc.create_batch(db, u1.id, p1.id, c1.id, "U1P1", [{"sql": "SELECT 1", "title": "Q"}])
        await svc.create_batch(db, u2.id, p1.id, c1.id, "U2P1", [{"sql": "SELECT 2", "title": "Q"}])
        await svc.create_batch(db, u1.id, p2.id, c2.id, "U1P2", [{"sql": "SELECT 3", "title": "Q"}])

        batches = await svc.list_batches(db, p1.id, u1.id)
        assert len(batches) == 1
        assert batches[0].title == "U1P1"

    @pytest.mark.asyncio
    async def test_respects_limit(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        for i in range(5):
            await svc.create_batch(
                db, user.id, proj.id, conn.id, f"B{i}", [{"sql": f"SELECT {i}", "title": f"Q{i}"}]
            )

        batches = await svc.list_batches(db, proj.id, user.id, limit=3)
        assert len(batches) == 3

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        batches = await svc.list_batches(db, proj.id, user.id)
        assert batches == []


class TestDeleteBatch:
    @pytest.mark.asyncio
    async def test_delete_existing(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        batch = await svc.create_batch(
            db, user.id, proj.id, conn.id, "Del", [{"sql": "SELECT 1", "title": "Q"}]
        )

        result = await svc.delete_batch(db, batch.id)
        assert result is True
        assert await svc.get_batch(db, batch.id) is None

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, db):
        result = await svc.delete_batch(db, "no-such-id")
        assert result is False


class TestExecuteBatch:
    """Tests for BatchService.execute_batch — the core execution loop."""

    @pytest.fixture
    def mock_tracker(self):
        with patch("app.services.batch_service.tracker") as t:
            t.begin = AsyncMock(return_value="wf-1")
            t.emit = AsyncMock()
            t.end = AsyncMock()
            yield t

    @pytest.fixture
    def mock_conn_svc(self):
        with (
            patch.object(_conn_svc_ref, "get", new_callable=AsyncMock) as mock_get,
            patch.object(_conn_svc_ref, "to_config", new_callable=AsyncMock) as mock_config,
        ):
            yield mock_get, mock_config

    @pytest.fixture
    def mock_connector(self):
        connector = AsyncMock()
        connector.connect = AsyncMock()
        connector.disconnect = AsyncMock()
        with patch("app.services.batch_service.get_connector", return_value=connector):
            yield connector

    @pytest.fixture
    def mock_session_factory(self, db):
        @asynccontextmanager
        async def _factory():
            yield db

        with patch("app.services.batch_service.async_session_factory", _factory):
            yield

    async def _setup(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        return user, proj, conn

    @pytest.mark.asyncio
    async def test_batch_not_found_logs_and_returns(self, db, mock_tracker, mock_session_factory):
        await svc.execute_batch("nonexistent-id", "conn-id", parallel=False)
        mock_tracker.begin.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_not_found_marks_failed(
        self, db, mock_tracker, mock_conn_svc, mock_session_factory
    ):
        user, proj, conn = await self._setup(db)
        batch = await svc.create_batch(
            db, user.id, proj.id, conn.id, "Test", [{"sql": "SELECT 1", "title": "Q"}]
        )

        mock_get, _ = mock_conn_svc
        mock_get.return_value = None

        await svc.execute_batch(batch.id, conn.id, parallel=False)

        await db.refresh(batch)
        assert batch.status == "failed"
        assert batch.completed_at is not None
        results = json.loads(batch.results_json)
        assert results[0]["error"] == "Connection not found"

    @pytest.mark.asyncio
    async def test_all_queries_succeed(
        self, db, mock_tracker, mock_conn_svc, mock_connector, mock_session_factory
    ):
        user, proj, conn = await self._setup(db)
        batch = await svc.create_batch(
            db,
            user.id,
            proj.id,
            conn.id,
            "Success",
            [{"sql": "SELECT 1", "title": "Q1"}, {"sql": "SELECT 2", "title": "Q2"}],
        )

        mock_get, mock_config = mock_conn_svc
        mock_get.return_value = conn
        mock_config.return_value = ConnectionConfig(db_type="postgresql")

        mock_connector.execute_query.return_value = QueryResult(
            columns=["id"], rows=[[1], [2]], row_count=2
        )

        await svc.execute_batch(batch.id, conn.id, user_id=user.id, parallel=False)

        await db.refresh(batch)
        assert batch.status == "completed"
        assert batch.completed_at is not None
        results = json.loads(batch.results_json)
        assert len(results) == 2
        assert all(r["status"] == "success" for r in results)
        assert results[0]["columns"] == ["id"]
        assert results[0]["total_rows"] == 2
        assert "duration_ms" in results[0]

    @pytest.mark.asyncio
    async def test_all_queries_fail(
        self, db, mock_tracker, mock_conn_svc, mock_connector, mock_session_factory
    ):
        user, proj, conn = await self._setup(db)
        batch = await svc.create_batch(
            db,
            user.id,
            proj.id,
            conn.id,
            "AllFail",
            [{"sql": "BAD SQL", "title": "Q1"}, {"sql": "WORSE SQL", "title": "Q2"}],
        )

        mock_get, mock_config = mock_conn_svc
        mock_get.return_value = conn
        mock_config.return_value = ConnectionConfig(db_type="postgresql")

        mock_connector.execute_query.side_effect = RuntimeError("syntax error")

        await svc.execute_batch(batch.id, conn.id, parallel=False)

        await db.refresh(batch)
        assert batch.status == "failed"
        results = json.loads(batch.results_json)
        assert len(results) == 2
        assert all(r["status"] == "failed" for r in results)
        assert "syntax error" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_partial_failure(
        self, db, mock_tracker, mock_conn_svc, mock_connector, mock_session_factory
    ):
        user, proj, conn = await self._setup(db)
        batch = await svc.create_batch(
            db,
            user.id,
            proj.id,
            conn.id,
            "Partial",
            [{"sql": "SELECT 1", "title": "Good"}, {"sql": "BAD", "title": "Bad"}],
        )

        mock_get, mock_config = mock_conn_svc
        mock_get.return_value = conn
        mock_config.return_value = ConnectionConfig(db_type="postgresql")

        mock_connector.execute_query.side_effect = [
            QueryResult(columns=["v"], rows=[[1]], row_count=1),
            RuntimeError("fail"),
        ]

        await svc.execute_batch(batch.id, conn.id, parallel=False)

        await db.refresh(batch)
        assert batch.status == "partially_failed"
        results = json.loads(batch.results_json)
        assert results[0]["status"] == "success"
        assert results[1]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_row_cap_applied(
        self, db, mock_tracker, mock_conn_svc, mock_connector, mock_session_factory
    ):
        user, proj, conn = await self._setup(db)
        batch = await svc.create_batch(
            db,
            user.id,
            proj.id,
            conn.id,
            "BigResult",
            [{"sql": "SELECT *", "title": "Q"}],
        )

        mock_get, mock_config = mock_conn_svc
        mock_get.return_value = conn
        mock_config.return_value = ConnectionConfig(db_type="postgresql")

        big_rows = [[i] for i in range(600)]
        mock_connector.execute_query.return_value = QueryResult(
            columns=["n"], rows=big_rows, row_count=600
        )

        await svc.execute_batch(batch.id, conn.id, parallel=False)

        await db.refresh(batch)
        results = json.loads(batch.results_json)
        assert len(results[0]["rows"]) == 500
        assert results[0]["total_rows"] == 600

    @pytest.mark.asyncio
    async def test_tracker_events_emitted(
        self, db, mock_tracker, mock_conn_svc, mock_connector, mock_session_factory
    ):
        user, proj, conn = await self._setup(db)
        batch = await svc.create_batch(
            db,
            user.id,
            proj.id,
            conn.id,
            "Events",
            [{"sql": "SELECT 1", "title": "Q1"}],
        )

        mock_get, mock_config = mock_conn_svc
        mock_get.return_value = conn
        mock_config.return_value = ConnectionConfig(db_type="postgresql")

        mock_connector.execute_query.return_value = QueryResult(
            columns=["v"], rows=[[1]], row_count=1
        )

        await svc.execute_batch(batch.id, conn.id, parallel=False)

        mock_tracker.begin.assert_called_once()
        assert mock_tracker.emit.call_count == 2
        mock_tracker.end.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_missing_sql_key_uses_empty_string(
        self, db, mock_tracker, mock_conn_svc, mock_connector, mock_session_factory
    ):
        user, proj, conn = await self._setup(db)
        batch = await svc.create_batch(
            db,
            user.id,
            proj.id,
            conn.id,
            "NoSQL",
            [{"title": "No SQL key"}],
        )

        mock_get, mock_config = mock_conn_svc
        mock_get.return_value = conn
        mock_config.return_value = ConnectionConfig(db_type="postgresql")

        mock_connector.execute_query.return_value = QueryResult(columns=[], rows=[], row_count=0)

        await svc.execute_batch(batch.id, conn.id, parallel=False)

        mock_connector.execute_query.assert_called_once_with("")

    @pytest.mark.asyncio
    async def test_connector_disconnect_called_even_on_failure(
        self, db, mock_tracker, mock_conn_svc, mock_connector, mock_session_factory
    ):
        user, proj, conn = await self._setup(db)
        batch = await svc.create_batch(
            db,
            user.id,
            proj.id,
            conn.id,
            "DisconnectTest",
            [{"sql": "SELECT 1", "title": "Q"}],
        )

        mock_get, mock_config = mock_conn_svc
        mock_get.return_value = conn
        mock_config.return_value = ConnectionConfig(db_type="postgresql")

        mock_connector.execute_query.side_effect = RuntimeError("boom")

        await svc.execute_batch(batch.id, conn.id, parallel=False)

        mock_connector.disconnect.assert_called_once()
