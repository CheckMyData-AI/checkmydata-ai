"""Unit tests for RepositoryService."""

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
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.repository  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.project import Project
from app.services.repository_service import RepositoryService

svc = RepositoryService()


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


class TestRepositoryCreate:
    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        proj = await _make_project(db)
        repo = await svc.create(
            db,
            project_id=proj.id,
            name="backend",
            repo_url="git@github.com:org/backend.git",
        )
        assert repo.id is not None
        assert repo.name == "backend"
        assert repo.repo_url == "git@github.com:org/backend.git"
        assert repo.branch == "main"
        assert repo.provider == "git_ssh"
        assert repo.project_id == proj.id

    @pytest.mark.asyncio
    async def test_create_with_all_fields(self, db):
        proj = await _make_project(db)
        repo = await svc.create(
            db,
            project_id=proj.id,
            name="frontend",
            repo_url="https://github.com/org/frontend.git",
            branch="develop",
            provider="https",
            ssh_key_id="key-abc",
            auth_token_encrypted="enc-token",
        )
        assert repo.branch == "develop"
        assert repo.provider == "https"
        assert repo.ssh_key_id == "key-abc"
        assert repo.auth_token_encrypted == "enc-token"


class TestRepositoryGet:
    @pytest.mark.asyncio
    async def test_get_existing(self, db):
        proj = await _make_project(db)
        repo = await svc.create(db, project_id=proj.id, name="repo", repo_url="git@host:r.git")
        fetched = await svc.get(db, repo.id)
        assert fetched is not None
        assert fetched.id == repo.id

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db):
        result = await svc.get(db, "no-such-id")
        assert result is None


class TestRepositoryListByProject:
    @pytest.mark.asyncio
    async def test_returns_repos_for_project(self, db):
        p1 = await _make_project(db)
        p2 = await _make_project(db)
        await svc.create(db, project_id=p1.id, name="r1", repo_url="u1")
        await svc.create(db, project_id=p1.id, name="r2", repo_url="u2")
        await svc.create(db, project_id=p2.id, name="r3", repo_url="u3")

        repos = await svc.list_by_project(db, p1.id)
        assert len(repos) == 2
        names = {r.name for r in repos}
        assert names == {"r1", "r2"}

    @pytest.mark.asyncio
    async def test_empty_project(self, db):
        proj = await _make_project(db)
        repos = await svc.list_by_project(db, proj.id)
        assert len(repos) == 0


class TestRepositoryUpdate:
    @pytest.mark.asyncio
    async def test_update_fields(self, db):
        proj = await _make_project(db)
        repo = await svc.create(db, project_id=proj.id, name="old", repo_url="git@host:old.git")
        updated = await svc.update(db, repo.id, name="new", branch="release")
        assert updated is not None
        assert updated.name == "new"
        assert updated.branch == "release"

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, db):
        result = await svc.update(db, "missing-id", name="x")
        assert result is None


class TestRepositoryDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self, db):
        proj = await _make_project(db)
        repo = await svc.create(db, project_id=proj.id, name="del", repo_url="git@host:d.git")
        result = await svc.delete(db, repo.id)
        assert result is True
        assert await svc.get(db, repo.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db):
        result = await svc.delete(db, "no-id")
        assert result is False
