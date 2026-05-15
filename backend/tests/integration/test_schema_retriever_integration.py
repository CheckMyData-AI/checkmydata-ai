"""Integration tests for the M4 schema retriever flow.

Exercises :class:`SchemaRetriever` end-to-end against real :class:`DbIndex`
ORM rows persisted via the shared ``db_session`` fixture. We deliberately
don't drive the full :meth:`DbIndexPipeline.run` here — the pipeline helper
only translates rows into a retriever call, and the rest is BM25 plumbing
covered by unit tests.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.schema_retriever import SchemaRetriever
from app.models.connection import Connection
from app.models.db_index import DbIndex
from app.models.project import Project
from app.models.user import User
from app.services.db_index_service import DbIndexService


@pytest_asyncio.fixture
async def connection_id(db_session: AsyncSession) -> str:
    """Create a user + project + connection so db_index FKs resolve."""
    user = User(
        id=str(uuid.uuid4()),
        email=f"u-{uuid.uuid4().hex[:6]}@test.example",
        password_hash="x",
        display_name="Test",
    )
    db_session.add(user)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        name="Test",
        owner_id=user.id,
        repo_url="git@example.com:foo/bar.git",
    )
    db_session.add(project)
    await db_session.flush()

    conn = Connection(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="test-conn",
        db_type="postgres",
        db_host="localhost",
        db_port=5432,
        db_name="testdb",
        db_user="user",
    )
    db_session.add(conn)
    await db_session.flush()
    return conn.id


@pytest_asyncio.fixture
async def seeded_index(db_session: AsyncSession, connection_id: str) -> str:
    """Seed db_index with a realistic 6-table fixture and return the conn id."""
    rows = [
        dict(
            table_name="users",
            business_description="application users and their profile data",
            column_notes_json='{"id": "primary key", "email": "login email"}',
            is_active=True,
            relevance_score=4,
        ),
        dict(
            table_name="orders",
            business_description="customer orders for the checkout flow",
            column_notes_json='{"id": "order id", "user_id": "fk users"}',
            is_active=True,
            relevance_score=4,
        ),
        dict(
            table_name="payments",
            business_description="payment transactions linked to orders",
            column_notes_json='{"order_id": "fk orders", "provider": "stripe paypal"}',
            is_active=True,
            relevance_score=3,
        ),
        dict(
            table_name="subscriptions",
            business_description="recurring subscription plans for SaaS billing",
            column_notes_json='{"user_id": "fk users", "plan": "subscription tier"}',
            is_active=True,
            relevance_score=3,
        ),
        dict(
            table_name="audit_log",
            business_description="security audit events",
            column_notes_json="{}",
            is_active=False,
            relevance_score=1,
        ),
        dict(
            table_name="events",
            business_description="analytics page view events",
            column_notes_json='{"event_name": "string"}',
            is_active=True,
            relevance_score=2,
        ),
    ]
    for r in rows:
        db_session.add(DbIndex(id=str(uuid.uuid4()), connection_id=connection_id, **r))
    await db_session.flush()
    return connection_id


@pytest.mark.asyncio
async def test_retriever_builds_from_db_index_rows(
    db_session: AsyncSession, seeded_index: str, tmp_path
):
    """Read DbIndex rows the same way the pipeline does, then build + query."""
    svc = DbIndexService()
    entries = await svc.get_index(db_session, seeded_index)
    assert len(entries) == 6, "fixture should provide 6 db_index rows"

    retriever = SchemaRetriever(data_dir=tmp_path / "bm25")
    retriever.build(seeded_index, indexed_sha="sha-1", entries=entries)
    assert retriever.has_index(seeded_index) is True

    # 1. Question about subscriptions ranks 'subscriptions' first.
    hits = retriever.query(seeded_index, "show me active SaaS subscriptions", k=5)
    assert hits, "expected at least one hit for subscription question"
    assert hits[0]["metadata"]["table_name"] == "subscriptions"

    # 2. Question about payment providers ranks 'payments' first.
    hits = retriever.query(seeded_index, "stripe paypal provider", k=5)
    assert hits
    assert hits[0]["metadata"]["table_name"] == "payments"

    # 3. Inactive 'audit_log' is filtered out by default.
    hits = retriever.query(
        seeded_index, "security audit events", k=5, only_active=True
    )
    names = [h["metadata"]["table_name"] for h in hits]
    assert "audit_log" not in names

    # 4. Same query with ``only_active=False`` does surface audit_log.
    hits = retriever.query(
        seeded_index, "security audit events", k=5, only_active=False
    )
    names = [h["metadata"]["table_name"] for h in hits]
    assert "audit_log" in names


@pytest.mark.asyncio
async def test_retriever_handles_empty_connection(
    db_session: AsyncSession, connection_id: str, tmp_path
):
    """Empty db_index → empty retriever, no error."""
    svc = DbIndexService()
    entries = await svc.get_index(db_session, connection_id)
    assert entries == []

    retriever = SchemaRetriever(data_dir=tmp_path / "bm25")
    retriever.build(connection_id, indexed_sha="empty", entries=entries)

    # BM25Index persists a sentinel snapshot for empty corpora so freshness
    # can still be tracked; queries still return zero hits.
    assert retriever.has_index(connection_id) is True
    assert retriever.query(connection_id, "anything") == []
