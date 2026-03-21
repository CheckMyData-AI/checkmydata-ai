"""Tests for BatchService CRUD operations."""

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.batch_service import BatchService


@pytest.fixture
def svc():
    return BatchService()


@pytest.mark.asyncio
class TestBatchCRUD:
    async def test_create_batch(self, db_session: AsyncSession, svc: BatchService):
        batch = await svc.create_batch(
            db_session,
            user_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
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
        batch = await svc.create_batch(
            db_session,
            user_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
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
        uid = str(uuid.uuid4())
        pid = str(uuid.uuid4())
        for i in range(3):
            await svc.create_batch(
                db_session,
                user_id=uid,
                project_id=pid,
                connection_id=str(uuid.uuid4()),
                title=f"Batch {i}",
                queries=[{"sql": "SELECT 1"}],
            )
        batches = await svc.list_batches(db_session, pid, uid)
        assert len(batches) == 3

    async def test_delete_batch(self, db_session: AsyncSession, svc: BatchService):
        batch = await svc.create_batch(
            db_session,
            user_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            title="Delete Me",
            queries=[],
        )
        assert await svc.delete_batch(db_session, batch.id) is True
        assert await svc.get_batch(db_session, batch.id) is None

    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession, svc: BatchService
    ):
        assert await svc.delete_batch(db_session, str(uuid.uuid4())) is False
