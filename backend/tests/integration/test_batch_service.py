"""Tests for BatchService CRUD operations."""

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.safety import SafetyGuard, SafetyLevel
from app.services.batch_service import BatchService
from tests.integration.conftest import make_connection, make_project, make_user


@pytest.fixture
def svc():
    return BatchService()


@pytest.mark.asyncio
class TestBatchCRUD:
    async def test_create_batch(self, db_session: AsyncSession, svc: BatchService):
        uid = await make_user(db_session)
        pid = await make_project(db_session, owner_id=uid)
        cid = await make_connection(db_session, project_id=pid)
        batch = await svc.create_batch(
            db_session,
            user_id=uid,
            project_id=pid,
            connection_id=cid,
            title="Test Batch",
            queries=[
                {"sql": "SELECT 1", "title": "Query 1"},
                {"sql": "SELECT 2", "title": "Query 2"},
            ],
        )
        assert batch.title == "Test Batch"
        assert batch.status == "pending"
        queries = json.loads(batch.queries_json)
        assert len(queries) == 2

    async def test_get_batch(self, db_session: AsyncSession, svc: BatchService):
        uid = await make_user(db_session)
        pid = await make_project(db_session, owner_id=uid)
        cid = await make_connection(db_session, project_id=pid)
        batch = await svc.create_batch(
            db_session,
            user_id=uid,
            project_id=pid,
            connection_id=cid,
            title="Find Me",
            queries=[{"sql": "SELECT 1", "title": "Q1"}],
        )
        found = await svc.get_batch(db_session, batch.id)
        assert found is not None
        assert found.title == "Find Me"

    async def test_get_nonexistent_batch(self, db_session: AsyncSession, svc: BatchService):
        found = await svc.get_batch(db_session, str(uuid.uuid4()))
        assert found is None

    async def test_list_batches(self, db_session: AsyncSession, svc: BatchService):
        uid = await make_user(db_session)
        pid = await make_project(db_session, owner_id=uid)
        cid = await make_connection(db_session, project_id=pid)
        for i in range(3):
            await svc.create_batch(
                db_session,
                user_id=uid,
                project_id=pid,
                connection_id=cid,
                title=f"Batch {i}",
                queries=[{"sql": "SELECT 1"}],
            )
        batches = await svc.list_batches(db_session, pid, uid)
        assert len(batches) == 3

    async def test_delete_batch(self, db_session: AsyncSession, svc: BatchService):
        uid = await make_user(db_session)
        pid = await make_project(db_session, owner_id=uid)
        cid = await make_connection(db_session, project_id=pid)
        batch = await svc.create_batch(
            db_session,
            user_id=uid,
            project_id=pid,
            connection_id=cid,
            title="Delete Me",
            queries=[],
        )
        assert await svc.delete_batch(db_session, batch.id) is True
        assert await svc.get_batch(db_session, batch.id) is None

    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession, svc: BatchService
    ):
        assert await svc.delete_batch(db_session, str(uuid.uuid4())) is False


@pytest.mark.asyncio
class TestBatchSafetyGuard:
    """C6 (F-SCHED-02): batch /execute must route raw SQL through SafetyGuard
    before running it against the connector."""

    async def test_read_only_blocks_ddl_without_executing(self, svc: BatchService):
        """A DROP TABLE on a read-only connection is rejected and never executed."""
        connector = AsyncMock()
        guard = SafetyGuard(SafetyLevel.READ_ONLY)

        entry = await svc._execute_single_query(
            idx=0,
            query_item={"sql": "DROP TABLE users", "title": "evil"},
            connector=connector,
            batch_id="b" * 16,
            total=1,
            wf_id="wf-1",
            guard=guard,
            db_type="postgres",
        )

        assert entry["status"] == "failed"
        assert "reason" not in entry or entry["error"]
        assert "read-only" in entry["error"].lower() or "blocked" in entry["error"].lower()
        connector.execute_query.assert_not_awaited()

    async def test_read_only_blocks_dml_without_executing(self, svc: BatchService):
        """A DELETE on a read-only connection is rejected and never executed."""
        connector = AsyncMock()
        guard = SafetyGuard(SafetyLevel.READ_ONLY)

        entry = await svc._execute_single_query(
            idx=0,
            query_item={"sql": "DELETE FROM accounts WHERE 1=1", "title": "wipe"},
            connector=connector,
            batch_id="b" * 16,
            total=1,
            wf_id="wf-1",
            guard=guard,
            db_type="postgres",
        )

        assert entry["status"] == "failed"
        connector.execute_query.assert_not_awaited()

    async def test_read_only_allows_select(self, svc: BatchService):
        """A plain SELECT on a read-only connection passes the guard and runs."""
        connector = AsyncMock()
        connector.execute_query.return_value = type(
            "R", (), {"columns": ["n"], "rows": [[1]], "row_count": 1}
        )()
        guard = SafetyGuard(SafetyLevel.READ_ONLY)

        entry = await svc._execute_single_query(
            idx=0,
            query_item={"sql": "SELECT 1 AS n", "title": "ok"},
            connector=connector,
            batch_id="b" * 16,
            total=1,
            wf_id="wf-1",
            guard=guard,
            db_type="postgres",
        )

        assert entry["status"] == "success"
        connector.execute_query.assert_awaited_once_with("SELECT 1 AS n")

    async def test_writable_connection_allows_dml(self, svc: BatchService):
        """On a writable connection (ALLOW_DML) an INSERT is permitted to run."""
        connector = AsyncMock()
        connector.execute_query.return_value = type(
            "R", (), {"columns": [], "rows": [], "row_count": 0}
        )()
        guard = SafetyGuard(SafetyLevel.ALLOW_DML)

        entry = await svc._execute_single_query(
            idx=0,
            query_item={"sql": "INSERT INTO t (a) VALUES (1)", "title": "ins"},
            connector=connector,
            batch_id="b" * 16,
            total=1,
            wf_id="wf-1",
            guard=guard,
            db_type="postgres",
        )

        assert entry["status"] == "success"
        connector.execute_query.assert_awaited_once()
