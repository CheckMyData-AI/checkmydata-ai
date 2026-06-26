"""Unit tests for DbIndexService — is_indexed whitelist, get_index_age None-guard."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — registers all mapped classes
from app.models.base import Base
from app.services.db_index_service import DbIndexService

# ---------------------------------------------------------------------------
# Session fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    s = sm()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Helper fixture — stub with indexed_at = NULL
# ---------------------------------------------------------------------------


@pytest.fixture
def summary_with_null_indexed_at():
    """Return a stub with indexed_at=None to simulate a NULL db row.

    The model column is NOT NULL so we cannot persist this state via SQLite.
    We simulate the production edge-case (row inserted before the default was
    added, or via direct DB manipulation) using SimpleNamespace so that
    get_index_age's None-guard is exercised without touching the DB.
    """
    return SimpleNamespace(indexed_at=None, connection_id="c3", indexing_status="completed")


# ---------------------------------------------------------------------------
# H7 — is_indexed status whitelist
# ---------------------------------------------------------------------------


async def test_is_indexed_false_for_failed_only(db_session: AsyncSession):
    """A connection whose last status is 'failed' must NOT appear indexed (H7)."""
    svc = DbIndexService()
    await svc.set_indexing_status(db_session, "c1", "running")
    await svc.set_indexing_status(db_session, "c1", "failed")
    await db_session.commit()
    assert await svc.is_indexed(db_session, "c1") is False


async def test_is_indexed_true_for_completed_partial(db_session: AsyncSession):
    """A connection whose status is 'completed_partial' IS indexed (H7)."""
    svc = DbIndexService()
    await svc.set_indexing_status(db_session, "c2", "completed_partial")
    await db_session.commit()
    # set_indexing_status does not set indexed_at; upsert_summary does.
    # Manually set indexed_at so is_indexed can return True.
    summary = await svc.get_summary(db_session, "c2")
    assert summary is not None
    from datetime import UTC, datetime

    summary.indexed_at = datetime.now(UTC)
    await db_session.flush()
    await db_session.commit()
    assert await svc.is_indexed(db_session, "c2") is True


# ---------------------------------------------------------------------------
# M9 — get_index_age None-guard
# ---------------------------------------------------------------------------


async def test_get_index_age_none_when_indexed_at_null(
    db_session: AsyncSession,
    summary_with_null_indexed_at: SimpleNamespace,
):
    """get_index_age must return None (not raise AttributeError) when indexed_at is NULL (M9).

    The model column is NOT NULL so we cannot persist this state via SQLite.
    We simulate it by patching get_summary to return an object whose indexed_at is None —
    replicating the production invariant that get_index_age must handle gracefully.
    """
    from unittest.mock import AsyncMock, patch

    svc = DbIndexService()
    with patch.object(svc, "get_summary", new=AsyncMock(return_value=summary_with_null_indexed_at)):
        result = await svc.get_index_age(db_session, "c3")
    assert result is None  # no AttributeError on None.tzinfo
