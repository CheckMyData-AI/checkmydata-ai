"""Unit tests for ProjectService."""

from datetime import UTC, datetime

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
from app.models.connection import Connection
from app.models.project import Project
from app.services.project_service import ProjectService

svc = ProjectService()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


class TestProjectCreate:
    @pytest.mark.asyncio
    async def test_create_returns_project_with_id(self, db):
        project = await svc.create(db, name="Analytics")
        assert project.id is not None
        assert len(project.id) == 36
        assert project.name == "Analytics"

    @pytest.mark.asyncio
    async def test_create_sets_defaults(self, db):
        project = await svc.create(db, name="Defaults")
        assert project.description == ""
        assert project.created_at is not None

    @pytest.mark.asyncio
    async def test_create_with_optional_fields(self, db):
        project = await svc.create(
            db,
            name="Full",
            description="A project with all fields",
            repo_url="git@github.com:org/repo.git",
            repo_branch="develop",
        )
        assert project.description == "A project with all fields"
        assert project.repo_url == "git@github.com:org/repo.git"
        assert project.repo_branch == "develop"


class TestProjectGet:
    @pytest.mark.asyncio
    async def test_get_existing_project(self, db):
        created = await svc.create(db, name="GetMe")
        fetched = await svc.get(db, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "GetMe"

    @pytest.mark.asyncio
    async def test_get_loads_connections(self, db):
        project = await svc.create(db, name="WithConn")
        conn = Connection(
            project_id=project.id,
            name="pg-local",
            db_type="postgresql",
            db_host="localhost",
            db_port=5432,
            db_name="testdb",
        )
        db.add(conn)
        await db.commit()

        fetched = await svc.get(db, project.id)
        assert fetched is not None
        assert len(fetched.connections) == 1
        assert fetched.connections[0].name == "pg-local"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, db):
        result = await svc.get(db, "no-such-uuid")
        assert result is None


class TestProjectListAll:
    @pytest.mark.asyncio
    async def test_list_all_returns_all_projects(self, db):
        await svc.create(db, name="Alpha")
        await svc.create(db, name="Beta")
        await svc.create(db, name="Gamma")

        projects = await svc.list_all(db)
        assert len(projects) == 3
        names = {p.name for p in projects}
        assert names == {"Alpha", "Beta", "Gamma"}

    @pytest.mark.asyncio
    async def test_list_all_ordered_by_created_at_desc(self, db):
        p_old = Project(name="Older", created_at=datetime(2026, 1, 1, tzinfo=UTC))
        db.add(p_old)
        await db.commit()
        await db.refresh(p_old)

        p_new = Project(name="Newer", created_at=datetime(2026, 6, 1, tzinfo=UTC))
        db.add(p_new)
        await db.commit()
        await db.refresh(p_new)

        projects = await svc.list_all(db)
        assert len(projects) == 2
        assert projects[0].name == "Newer"
        assert projects[1].name == "Older"

    @pytest.mark.asyncio
    async def test_list_all_empty(self, db):
        projects = await svc.list_all(db)
        assert projects == []


class TestProjectUpdate:
    @pytest.mark.asyncio
    async def test_update_name(self, db):
        project = await svc.create(db, name="Original")
        updated = await svc.update(db, project.id, name="Renamed")
        assert updated is not None
        assert updated.name == "Renamed"

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self, db):
        project = await svc.create(db, name="Multi")
        updated = await svc.update(db, project.id, name="Updated", description="New desc")
        assert updated is not None
        assert updated.name == "Updated"
        assert updated.description == "New desc"

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_none(self, db):
        result = await svc.update(db, "no-such-id", name="X")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_ignores_none_values(self, db):
        project = await svc.create(db, name="Keep", description="Original desc")
        updated = await svc.update(db, project.id, name=None, description="Changed")
        assert updated is not None
        assert updated.name == "Keep"
        assert updated.description == "Changed"

    @pytest.mark.asyncio
    async def test_update_rejects_owner_id_mass_assignment(self, db):
        """T04 — mass-assignment on sensitive columns must be blocked."""
        project = await svc.create(db, name="MA")
        orig_owner = project.owner_id

        updated = await svc.update(
            db,
            project.id,
            name="Safe",
            owner_id="attacker-user-id",
        )
        assert updated is not None
        assert updated.name == "Safe"
        assert updated.owner_id == orig_owner, (
            "owner_id must not be changed via mass-assignment"
        )

    @pytest.mark.asyncio
    async def test_update_rejects_unknown_fields(self, db):
        project = await svc.create(db, name="Ignore")
        updated = await svc.update(db, project.id, no_such_field="x")
        assert updated is not None
        assert not hasattr(updated, "no_such_field") or getattr(
            updated, "no_such_field", None
        ) != "x"

    @pytest.mark.asyncio
    async def test_update_rejects_protected_timestamp_fields(self, db):
        from datetime import UTC, datetime
        project = await svc.create(db, name="TS")
        hijack = datetime(1999, 1, 1, tzinfo=UTC)
        orig_created = project.created_at

        updated = await svc.update(db, project.id, created_at=hijack, updated_at=hijack)
        assert updated is not None
        assert updated.created_at == orig_created


class TestProjectDelete:
    @pytest.mark.asyncio
    async def test_delete_existing_project(self, db):
        project = await svc.create(db, name="ToDelete")
        result = await svc.delete(db, project.id)
        assert result is True
        assert await svc.get(db, project.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, db):
        result = await svc.delete(db, "nonexistent-uuid")
        assert result is False
