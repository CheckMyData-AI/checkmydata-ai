"""T8 — orchestrator gating and tenant isolation for the analytics source.

Three separate gates are proven here, because each one fails differently:

* :func:`~app.agents.tools.orchestrator_tools.get_orchestrator_tools` must not
  advertise ``query_analytics_source`` to a project that has no analytics
  connection — an advertised tool the model cannot use costs a wasted turn and
  an apology.
* :meth:`~app.agents.context_loader.ContextLoader.has_analytics_sources` is what
  decides that, and it must key off ``source_type``, not "any connection".
* The dispatcher must refuse a connection belonging to **another project** even
  when the model names its id explicitly (R3 tenant isolation). That check is
  not a nicety: ``connection_id`` arrives from an LLM, which means it arrives
  from whatever the user typed.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every mapper
from app.agents.analytics_agent import AnalyticsAgent, AnalyticsResult
from app.agents.base import AgentContext
from app.agents.context_loader import ContextLoader
from app.agents.tool_dispatcher import ToolDispatcher
from app.agents.tools.analytics_tools import (
    ANALYTICS_SOURCE_TYPES,
    QUERY_ANALYTICS_SOURCE_TOOL,
)
from app.agents.tools.mcp_tools import QUERY_MCP_SOURCE_TOOL
from app.agents.tools.orchestrator_tools import get_orchestrator_tools
from app.agents.validation import AgentResultValidator
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import ToolCall
from app.models.base import Base, enable_sqlite_fk
from app.models.connection import Connection
from app.models.project import Project
from app.services.connection_service import ConnectionService

# ---------------------------------------------------------------------------
# get_orchestrator_tools
# ---------------------------------------------------------------------------


def _tool_names(**kwargs: bool) -> set[str]:
    return {t.name for t in get_orchestrator_tools(**kwargs)}


class TestOrchestratorToolGating:
    def test_absent_without_analytics_sources(self) -> None:
        assert "query_analytics_source" not in _tool_names(
            has_connection=True,
            has_knowledge_base=True,
            has_mcp_sources=True,
            has_repo=True,
        )

    def test_present_with_analytics_sources(self) -> None:
        assert "query_analytics_source" in _tool_names(has_analytics_sources=True)

    def test_gate_is_independent_of_the_mcp_gate(self) -> None:
        """An MCP project must not get the analytics tool, and vice versa."""
        mcp_only = _tool_names(has_mcp_sources=True)
        analytics_only = _tool_names(has_analytics_sources=True)

        assert "query_mcp_source" in mcp_only
        assert "query_analytics_source" not in mcp_only
        assert "query_analytics_source" in analytics_only
        assert "query_mcp_source" not in analytics_only

    def test_default_is_off(self) -> None:
        assert "query_analytics_source" not in _tool_names()

    def test_tool_exposes_the_spec_parameters(self) -> None:
        params = {p.name: p for p in QUERY_ANALYTICS_SOURCE_TOOL.parameters}
        assert set(params) == {"question", "connection_id", "report", "date_from", "date_to"}
        assert params["question"].required is True
        assert all(not params[name].required for name in params if name != "question")


class TestMcpToolDescription:
    """C7 — the MCP tool must stop advertising itself for Google Analytics."""

    def test_no_longer_advertises_itself_for_google_analytics(self) -> None:
        desc = QUERY_MCP_SOURCE_TOOL.description
        assert "services like Google Analytics" not in desc
        assert "not natively supported" in desc.lower()

    def test_points_at_the_first_class_connector(self) -> None:
        desc = QUERY_MCP_SOURCE_TOOL.description
        assert "first-class" in desc
        assert "query_analytics_source" in desc


# ---------------------------------------------------------------------------
# ContextLoader.has_analytics_sources
# ---------------------------------------------------------------------------


def _loader() -> ContextLoader:
    tracker = MagicMock(spec=WorkflowTracker)
    tracker.emit = AsyncMock()
    return ContextLoader(vector_store=MagicMock(), tracker=tracker, mcp_cache={})


def _conn(source_type: str) -> Connection:
    return Connection(project_id="proj-1", name=f"{source_type}-conn", source_type=source_type)


class TestHasAnalyticsSources:
    @pytest.mark.parametrize("source_type", sorted(ANALYTICS_SOURCE_TYPES))
    async def test_true_for_every_analytics_vendor(
        self, source_type: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            ConnectionService,
            "list_by_project",
            AsyncMock(return_value=[_conn("database"), _conn(source_type)]),
        )
        assert await _loader().has_analytics_sources("proj-1") is True

    async def test_false_for_database_and_mcp_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ConnectionService,
            "list_by_project",
            AsyncMock(return_value=[_conn("database"), _conn("mcp")]),
        )
        assert await _loader().has_analytics_sources("proj-1") is False

    async def test_degrades_to_false_when_the_lookup_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            ConnectionService,
            "list_by_project",
            AsyncMock(side_effect=RuntimeError("db down")),
        )
        loader = _loader()
        assert await loader.has_analytics_sources("proj-1", "wf-1") is False

    async def test_result_is_cached_per_project(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lookup = AsyncMock(return_value=[_conn("ga4")])
        monkeypatch.setattr(ConnectionService, "list_by_project", lookup)
        loader = _loader()

        assert await loader.has_analytics_sources("proj-1") is True
        assert await loader.has_analytics_sources("proj-1") is True
        assert lookup.await_count == 1

    async def test_cache_is_not_shared_with_the_mcp_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A project with only MCP must not be reported as having analytics."""
        monkeypatch.setattr(
            ConnectionService, "list_by_project", AsyncMock(return_value=[_conn("mcp")])
        )
        loader = _loader()

        assert await loader.has_mcp_sources("proj-1") is True
        assert await loader.has_analytics_sources("proj-1") is False


# ---------------------------------------------------------------------------
# Dispatcher — tenant isolation
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sessionmaker_fixture():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_fk(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _make_connection(sm, *, source_type: str = "ga4") -> tuple[str, str]:
    """Create a project + connection; return ``(project_id, connection_id)``."""
    async with sm() as session:
        project = Project(name=f"p-{uuid.uuid4().hex[:6]}")
        session.add(project)
        await session.commit()
        conn = Connection(
            project_id=project.id, name="GA4 prod", source_type=source_type, collection_hour=3
        )
        session.add(conn)
        await session.commit()
        return project.id, conn.id


def _tracker() -> MagicMock:
    tracker = MagicMock(spec=WorkflowTracker)
    tracker.emit = AsyncMock()

    @asynccontextmanager
    async def _step(*_a, **_kw):
        yield

    tracker.step = MagicMock(side_effect=_step)
    return tracker


def _dispatcher(analytics_agent) -> ToolDispatcher:
    return ToolDispatcher(
        sql_agent=MagicMock(),
        knowledge_agent=MagicMock(),
        mcp_source_agent=MagicMock(),
        validator=AgentResultValidator(),
        tracker=_tracker(),
        wf_sql_results={},
        wf_enriched={},
        analytics_agent=analytics_agent,
    )


def _context(project_id: str) -> AgentContext:
    return AgentContext(
        project_id=project_id,
        connection_config=None,
        user_question="how many sessions last week?",
        chat_history=[],
        llm_router=MagicMock(),
        tracker=_tracker(),
        workflow_id="wf-1",
    )


def _call(**arguments: str) -> ToolCall:
    return ToolCall(id="tc-1", name="query_analytics_source", arguments=dict(arguments))


class TestDispatcherTenantIsolation:
    async def test_connection_from_another_project_is_refused(
        self, sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.models.base as base_mod

        monkeypatch.setattr(base_mod, "async_session_factory", sessionmaker_fixture)
        _other_project, conn_id = await _make_connection(sessionmaker_fixture)

        agent = MagicMock(spec=AnalyticsAgent)
        agent.run = AsyncMock(return_value=AnalyticsResult(status="success", answer="leaked data"))
        dispatcher = _dispatcher(agent)

        text, result = await dispatcher.dispatch(
            _call(question="q", connection_id=conn_id),
            _context("some-other-project"),
            "wf-1",
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

        assert result is None
        assert "does not belong to this project" in text
        assert "leaked data" not in text
        agent.run.assert_not_awaited()

    async def test_unknown_connection_id_is_refused(
        self, sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.models.base as base_mod

        monkeypatch.setattr(base_mod, "async_session_factory", sessionmaker_fixture)
        agent = MagicMock(spec=AnalyticsAgent)
        agent.run = AsyncMock()
        dispatcher = _dispatcher(agent)

        text, result = await dispatcher.dispatch(
            _call(question="q", connection_id="does-not-exist"),
            _context("proj-1"),
            "wf-1",
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

        assert result is None
        assert "not found" in text.lower()
        agent.run.assert_not_awaited()

    async def test_non_analytics_connection_is_refused(
        self, sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A database connection id must not be answered from the fact tables."""
        import app.models.base as base_mod

        monkeypatch.setattr(base_mod, "async_session_factory", sessionmaker_fixture)
        project_id, conn_id = await _make_connection(sessionmaker_fixture, source_type="database")

        agent = MagicMock(spec=AnalyticsAgent)
        agent.run = AsyncMock()
        dispatcher = _dispatcher(agent)

        text, result = await dispatcher.dispatch(
            _call(question="q", connection_id=conn_id),
            _context(project_id),
            "wf-1",
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

        assert result is None
        assert "not found" in text.lower() or "not an analytics" in text.lower()
        agent.run.assert_not_awaited()

    async def test_project_without_analytics_connections_is_told_so(
        self, sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.models.base as base_mod

        monkeypatch.setattr(base_mod, "async_session_factory", sessionmaker_fixture)
        project_id, _ = await _make_connection(sessionmaker_fixture, source_type="database")

        agent = MagicMock(spec=AnalyticsAgent)
        agent.run = AsyncMock()
        dispatcher = _dispatcher(agent)

        text, result = await dispatcher.dispatch(
            _call(question="q"), _context(project_id), "wf-1", {}
        )

        assert result is None
        assert "no analytics" in text.lower()
        agent.run.assert_not_awaited()

    async def test_owned_connection_reaches_the_agent(
        self, sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.models.base as base_mod

        monkeypatch.setattr(base_mod, "async_session_factory", sessionmaker_fixture)
        project_id, conn_id = await _make_connection(sessionmaker_fixture)

        agent = MagicMock(spec=AnalyticsAgent)
        agent.run = AsyncMock(
            return_value=AnalyticsResult(
                status="success",
                answer="1,234 sessions last week.",
                token_usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            )
        )
        dispatcher = _dispatcher(agent)
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        text, result = await dispatcher.dispatch(
            _call(question="sessions?", connection_id=conn_id), _context(project_id), "wf-1", usage
        )

        assert isinstance(result, AnalyticsResult)
        assert "1,234 sessions" in text
        assert usage["total_tokens"] == 7
        kwargs = agent.run.await_args.kwargs
        assert kwargs["connection_id"] == conn_id
        assert kwargs["source_type"] == "ga4"

    async def test_validation_failure_is_surfaced_not_swallowed(
        self, sessionmaker_fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``no_result`` from the agent must never reach the user as an answer."""
        import app.models.base as base_mod

        monkeypatch.setattr(base_mod, "async_session_factory", sessionmaker_fixture)
        project_id, conn_id = await _make_connection(sessionmaker_fixture)

        agent = MagicMock(spec=AnalyticsAgent)
        agent.run = AsyncMock(
            return_value=AnalyticsResult(
                status="no_result", answer="Reached maximum iterations for analytics tool calls."
            )
        )
        dispatcher = _dispatcher(agent)

        text, _result = await dispatcher.dispatch(
            _call(question="q", connection_id=conn_id), _context(project_id), "wf-1", {}
        )

        assert "Reached maximum iterations" not in text
        assert "analytics" in text.lower()
