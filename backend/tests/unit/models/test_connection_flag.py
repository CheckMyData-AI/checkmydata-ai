"""Unit tests for Connection.send_sample_data_to_llm flag (T14).

Covers:
  - Default True on new connections.
  - Explicit False is persisted.
  - ConnectionService.to_config propagates the flag into ConnectionConfig.
"""

from __future__ import annotations

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
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.connection import Connection
from app.models.project import Project
from app.services.connection_service import ConnectionService

svc = ConnectionService()


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


class TestSendSampleDataFlag:
    @pytest.mark.asyncio
    async def test_default_true(self, db: AsyncSession):
        """A new connection should default send_sample_data_to_llm to True."""
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="test-default",
            db_type="postgres",
            db_host="127.0.0.1",
            db_port=5432,
            db_name="mydb",
        )
        assert conn.send_sample_data_to_llm is True

    @pytest.mark.asyncio
    async def test_explicit_false_persisted(self, db: AsyncSession):
        """Passing send_sample_data_to_llm=False should persist as False."""
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="test-optout",
            db_type="postgres",
            db_host="127.0.0.1",
            db_port=5432,
            db_name="mydb",
            send_sample_data_to_llm=False,
        )
        assert conn.send_sample_data_to_llm is False

        # Reload from DB to confirm persistence, not just in-memory default.
        from sqlalchemy import select

        row = (await db.execute(select(Connection).where(Connection.id == conn.id))).scalar_one()
        assert row.send_sample_data_to_llm is False

    @pytest.mark.asyncio
    async def test_to_config_propagates_true(self, db: AsyncSession):
        """to_config should set send_sample_data_to_llm=True on ConnectionConfig."""
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="test-config-true",
            db_type="postgres",
            db_host="127.0.0.1",
            db_port=5432,
            db_name="mydb",
        )
        config = await svc.to_config(db, conn)
        assert config.send_sample_data_to_llm is True

    @pytest.mark.asyncio
    async def test_to_config_propagates_false(self, db: AsyncSession):
        """to_config should set send_sample_data_to_llm=False when opt-out is stored."""
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="test-config-false",
            db_type="postgres",
            db_host="127.0.0.1",
            db_port=5432,
            db_name="mydb",
            send_sample_data_to_llm=False,
        )
        config = await svc.to_config(db, conn)
        assert config.send_sample_data_to_llm is False
