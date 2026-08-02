"""The ``_connect`` sentinel drives the top-level status, never a report row.

A connection-level failure (bad credential, adapter unbuildable) is journalled
under the reserved report name ``_connect``. It is not a vendor report, so it
must not appear in the per-report list the UI renders — otherwise the user sees
a row literally named ``_connect`` with a null grain. It must still reach the
top-level ``status``/``last_error``, because that failure is the whole reason
the connection has collected nothing.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.analytics import journal
from app.models.base import Base, enable_sqlite_fk
from app.models.connection import Connection
from app.models.project import Project
from app.services.analytics_collect_service import CONNECT_SENTINEL_REPORT
from app.services.connection_service import ConnectionService


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_fk(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def ga4_connection(db_session) -> Connection:
    project = Project(name="Sentinel")
    db_session.add(project)
    await db_session.commit()
    conn = Connection(
        project_id=project.id,
        name="GA4 prod",
        source_type="ga4",
        is_active=True,
        collection_enabled=True,
        collection_hour=3,
    )
    db_session.add(conn)
    await db_session.commit()
    return conn


async def test_connect_sentinel_is_not_listed_as_a_report(db_session, ga4_connection):
    await journal.record(
        db_session,
        connection_id=ga4_connection.id,
        report=CONNECT_SENTINEL_REPORT,
        period="2026-08-02",
        status="failed",
        error="GA4 prod: property not shared with the service account",
    )

    status = await ConnectionService().collection_status(db_session, ga4_connection)

    listed = [r["report"] for r in status["reports"]]
    assert CONNECT_SENTINEL_REPORT not in listed, (
        f"the reserved sentinel leaked into the per-report list the UI renders: {listed}"
    )


async def test_connect_sentinel_still_surfaces_as_the_connection_level_failure(
    db_session, ga4_connection
):
    reason = "GA4 prod: property not shared with the service account"
    await journal.record(
        db_session,
        connection_id=ga4_connection.id,
        report=CONNECT_SENTINEL_REPORT,
        period="2026-08-02",
        status="failed",
        error=reason,
    )

    status = await ConnectionService().collection_status(db_session, ga4_connection)

    # Filtering the sentinel out of the report list must not also hide the
    # failure — that would restore the exact bug it was introduced to fix,
    # where a broken credential reads as "never collected".
    assert status["status"] == "failed"
    assert status["last_error"] == reason
