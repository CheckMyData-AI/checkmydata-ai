"""Regression tests for the failed-doc regeneration queue on ProjectCache.

A partial doc-generation failure (under generate_docs_max_failure_ratio) lets
the index run complete, but those paths fall out of future git diffs. The
ProjectCacheService failed-doc queue is what lets the next run re-process them
so the knowledge base doesn't keep permanent holes.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.user import User
from app.services.project_cache_service import ProjectCacheService


@pytest_asyncio.fixture
async def project_id(db_session: AsyncSession) -> str:
    user = User(
        id=str(uuid.uuid4()),
        email=f"user-{uuid.uuid4().hex[:6]}@test.example",
        password_hash="x",
        display_name="Test",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name="Test project",
        owner_id=user.id,
        repo_url="git@example.com:foo/bar.git",
    )
    db_session.add(project)
    await db_session.flush()
    return project.id


@pytest.mark.asyncio
async def test_failed_paths_round_trip(db_session: AsyncSession, project_id: str):
    svc = ProjectCacheService()
    assert await svc.get_failed_doc_paths(db_session, project_id) == []

    await svc.set_failed_doc_paths(db_session, project_id, ["b.py", "a.py", "a.py"])
    # Stored sorted + deduped.
    assert await svc.get_failed_doc_paths(db_session, project_id) == ["a.py", "b.py"]


@pytest.mark.asyncio
async def test_failed_paths_cleared(db_session: AsyncSession, project_id: str):
    svc = ProjectCacheService()
    await svc.set_failed_doc_paths(db_session, project_id, ["a.py"])
    await svc.set_failed_doc_paths(db_session, project_id, [])
    assert await svc.get_failed_doc_paths(db_session, project_id) == []


@pytest.mark.asyncio
async def test_failed_paths_coexist_with_knowledge_save(db_session: AsyncSession, project_id: str):
    """Setting failed paths before any cache.save must not clobber later saves."""
    svc = ProjectCacheService()
    await svc.set_failed_doc_paths(db_session, project_id, ["x.py"])
    # A subsequent knowledge save (knowledge=None) must keep the failed queue.
    await svc.save(db_session, project_id, knowledge=None, profile=None)
    assert await svc.get_failed_doc_paths(db_session, project_id) == ["x.py"]
