"""M6 — "a connection is attached" is not "there is a database to query".

An analytics connection produces a :class:`ConnectionConfig` whose ``db_type``
carries the *vendor* id (``"ga4"``), because that is what the analytics adapter
dispatches on. Every caller that derives "can I offer ``query_database``?" from
``connection_config is not None`` therefore advertises SQL against a GA4 source;
when the model takes the offer, ``get_connector("ga4")`` raises
``ValueError: Unsupported adapter: ga4`` in the middle of the user's chat.

:func:`app.services.connection_service.is_queryable_database` is the correct
predicate. These tests pin it against configs built by the real ``to_config``
(not hand-rolled ones), and pin the consequence: the orchestrator tool list
derived from it offers no ``query_database`` for a GA4-only project.
"""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — registers every mapped class on Base.metadata
from app.agents.tools.orchestrator_tools import get_orchestrator_tools
from app.connectors.registry import get_connector
from app.models.base import Base
from app.models.connection import Connection
from app.models.project import Project
from app.models.user import User
from app.services.connection_service import ConnectionService, is_queryable_database


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    db = sm()
    try:
        yield db
    finally:
        await db.close()
        await engine.dispose()


async def _project(session: AsyncSession) -> str:
    user = User(id=str(uuid.uuid4()), email=f"u-{uuid.uuid4().hex[:8]}@test.com")
    project = Project(id=str(uuid.uuid4()), name="P", owner_id=user.id)
    session.add_all([user, project])
    await session.commit()
    return project.id


async def _ga4_config(session: AsyncSession):
    conn = Connection(
        id=str(uuid.uuid4()),
        project_id=await _project(session),
        name="Marketing GA4",
        source_type="ga4",
        db_type=None,
        db_host="",
        db_port=None,
        db_name=None,
        source_config_json=json.dumps({"property_ids": ["294380179"]}),
    )
    session.add(conn)
    await session.commit()
    return await ConnectionService().to_config(session, conn)


async def _postgres_config(session: AsyncSession):
    conn = Connection(
        id=str(uuid.uuid4()),
        project_id=await _project(session),
        name="prod-postgres",
        source_type="database",
        db_type="postgres",
        db_host="db.internal",
        db_port=5432,
        db_name="shop",
        db_user="reader",
    )
    session.add(conn)
    await session.commit()
    return await ConnectionService().to_config(session, conn)


class TestIsQueryableDatabase:
    async def test_no_connection_is_not_queryable(self):
        assert is_queryable_database(None) is False

    async def test_a_ga4_config_is_not_a_queryable_database(self, session: AsyncSession):
        config = await _ga4_config(session)
        # The premise: db_type really does carry the vendor id, which is why a
        # truthiness check on the config alone gets this wrong.
        assert config.db_type == "ga4"
        assert is_queryable_database(config) is False

    async def test_the_vendor_id_really_has_no_connector(self, session: AsyncSession):
        """Documents the crash the gate prevents, rather than asserting it abstractly."""
        config = await _ga4_config(session)
        with pytest.raises(ValueError, match="Unsupported adapter"):
            get_connector(config.db_type)

    async def test_a_database_config_is_queryable(self, session: AsyncSession):
        config = await _postgres_config(session)
        assert is_queryable_database(config) is True

    async def test_an_mcp_config_stays_queryable(self, session: AsyncSession):
        """Regression: MCP sources are dispatched through the connector registry."""
        conn = Connection(
            id=str(uuid.uuid4()),
            project_id=await _project(session),
            name="mcp-source",
            source_type="mcp",
            db_type="mcp",
            db_host="",
            db_port=None,
            db_name="",
            mcp_server_command="/usr/bin/thing",
        )
        session.add(conn)
        await session.commit()
        config = await ConnectionService().to_config(session, conn)
        assert is_queryable_database(config) is True


class TestOrchestratorToolGating:
    async def test_a_ga4_only_project_is_not_offered_query_database(self, session: AsyncSession):
        config = await _ga4_config(session)
        tools = get_orchestrator_tools(
            has_connection=is_queryable_database(config),
            has_analytics_sources=True,
        )
        names = {tool.name for tool in tools}
        assert "query_database" not in names, (
            "the orchestrator would offer SQL against a GA4 source, and "
            "get_connector('ga4') raises the moment the model takes the offer"
        )
        assert "query_analytics_source" in names

    async def test_a_database_project_is_still_offered_query_database(self, session: AsyncSession):
        config = await _postgres_config(session)
        tools = get_orchestrator_tools(has_connection=is_queryable_database(config))
        assert "query_database" in {tool.name for tool in tools}
