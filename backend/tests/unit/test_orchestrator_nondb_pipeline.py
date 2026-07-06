"""T9 — ORCH-R01 + ORCH-P04: non-DB complex questions must enter the pipeline;
_quick_data_plan must pick the correct fallback tool per capability.

Tests:
1. test_complex_knowledge_question_uses_pipeline — has_kb=True, has_connection=False,
   complex route → _run_complex_pipeline is awaited (today it is NOT).
2. test_complex_repo_question_uses_pipeline — has_repo=True, no DB → pipeline.
3. test_complex_db_question_still_uses_pipeline — regression: has_connection=True
   path unchanged.
4. test_quick_data_plan_uses_search_codebase — fallback_tool="search_codebase"
   → stage tool is "search_codebase".
5. test_quick_data_plan_uses_analyze_git — fallback_tool="analyze_git".
6. test_quick_data_plan_default_is_query_database — no arg → "query_database".
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.adaptive_planner import AdaptivePlanner
from app.agents.base import AgentContext
from app.agents.orchestrator import AgentResponse, OrchestratorAgent
from app.agents.router import RouteResult
from app.core.workflow_tracker import WorkflowTracker

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()
    t.has_ended = MagicMock(return_value=False)

    @asynccontextmanager
    async def fake_step(wf_id, step, detail="", **kwargs):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    router.get_context_window = MagicMock(return_value=128_000)
    return router


@pytest.fixture
def mock_vs():
    vs = MagicMock()
    collection = MagicMock()
    collection.count = MagicMock(return_value=0)
    vs.get_or_create_collection = MagicMock(return_value=collection)
    return vs


@pytest.fixture
def orch(mock_llm, mock_vs, mock_tracker):
    return OrchestratorAgent(
        llm_router=mock_llm,
        vector_store=mock_vs,
        workflow_tracker=mock_tracker,
    )


def _make_context(mock_llm, mock_tracker, *, has_connection: bool = False) -> AgentContext:
    from app.connectors.base import ConnectionConfig

    conn = None
    if has_connection:
        conn = ConnectionConfig(
            connection_id="conn-1",
            db_type="postgres",
            db_host="localhost",
            db_port=5432,
            db_name="mydb",
            db_user="user",
            db_password="pass",
        )
    return AgentContext(
        project_id="test-proj",
        connection_config=conn,
        user_question="How does the authentication module work and what are the main flows?",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
        project_name="TestProject",
    )


def _complex_knowledge_route() -> RouteResult:
    return RouteResult(
        route="knowledge",
        complexity="complex",
        approach="Multi-stage knowledge search",
        estimated_queries=3,
        needs_multiple_data_sources=False,
    )


def _complex_db_route() -> RouteResult:
    return RouteResult(
        route="query",
        complexity="complex",
        approach="Multi-stage DB analysis",
        estimated_queries=3,
        needs_multiple_data_sources=False,
    )


_SENTINEL_RESPONSE = AgentResponse(
    answer="pipeline ran",
    response_type="text",
)


# ---------------------------------------------------------------------------
# T1: complex KB question (no DB) → pipeline
# ---------------------------------------------------------------------------


class TestComplexNonDbQuestionUsesPipeline:
    @pytest.mark.asyncio
    async def test_complex_knowledge_question_uses_pipeline(self, orch, mock_llm, mock_tracker):
        """ORCH-R01: has_kb=True, no connection, complex route must call
        _run_complex_pipeline (not fall through to _run_unified_agent)."""
        context = _make_context(mock_llm, mock_tracker, has_connection=False)

        pipeline_mock = AsyncMock(return_value=_SENTINEL_RESPONSE)

        with (
            patch(
                "app.agents.orchestrator.route_request",
                new=AsyncMock(return_value=_complex_knowledge_route()),
            ),
            patch.object(
                orch._ctx_loader,
                "has_knowledge_base",
                return_value=True,
            ),
            patch.object(
                orch._ctx_loader,
                "has_mcp_sources",
                new=AsyncMock(return_value=False),
            ),
            patch.object(
                orch._ctx_loader,
                "has_repo",
                return_value=False,
            ),
            patch.object(
                orch._ctx_loader,
                "check_staleness",
                new=AsyncMock(return_value=None),
            ),
            patch.object(orch, "_run_complex_pipeline", pipeline_mock),
            patch.object(orch, "_check_pipeline_resume", new=AsyncMock(return_value=None)),
        ):
            result = await orch.run(context)

        pipeline_mock.assert_awaited_once()
        assert result is _SENTINEL_RESPONSE

    @pytest.mark.asyncio
    async def test_complex_repo_question_uses_pipeline(self, orch, mock_llm, mock_tracker):
        """ORCH-R01: has_repo=True, no connection, complex route must call
        _run_complex_pipeline."""
        context = _make_context(mock_llm, mock_tracker, has_connection=False)

        pipeline_mock = AsyncMock(return_value=_SENTINEL_RESPONSE)

        with (
            patch(
                "app.agents.orchestrator.route_request",
                new=AsyncMock(return_value=_complex_knowledge_route()),
            ),
            patch.object(
                orch._ctx_loader,
                "has_knowledge_base",
                return_value=False,
            ),
            patch.object(
                orch._ctx_loader,
                "has_mcp_sources",
                new=AsyncMock(return_value=False),
            ),
            patch.object(
                orch._ctx_loader,
                "has_repo",
                return_value=True,
            ),
            patch.object(
                orch._ctx_loader,
                "check_staleness",
                new=AsyncMock(return_value=None),
            ),
            patch.object(orch, "_run_complex_pipeline", pipeline_mock),
            patch.object(orch, "_check_pipeline_resume", new=AsyncMock(return_value=None)),
        ):
            result = await orch.run(context)

        pipeline_mock.assert_awaited_once()
        assert result is _SENTINEL_RESPONSE

    @pytest.mark.asyncio
    async def test_complex_db_question_still_uses_pipeline(self, orch, mock_llm, mock_tracker):
        """Regression: has_connection=True path must still reach the pipeline."""
        context = _make_context(mock_llm, mock_tracker, has_connection=True)

        pipeline_mock = AsyncMock(return_value=_SENTINEL_RESPONSE)

        with (
            patch(
                "app.agents.orchestrator.route_request",
                new=AsyncMock(return_value=_complex_db_route()),
            ),
            patch.object(
                orch._ctx_loader,
                "has_knowledge_base",
                return_value=False,
            ),
            patch.object(
                orch._ctx_loader,
                "has_mcp_sources",
                new=AsyncMock(return_value=False),
            ),
            patch.object(
                orch._ctx_loader,
                "has_repo",
                return_value=False,
            ),
            patch.object(
                orch._ctx_loader,
                "check_staleness",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                orch._ctx_loader,
                "resolve_connection_id",
                new=AsyncMock(return_value="conn-1"),
            ),
            patch.object(
                orch._ctx_loader,
                "build_table_map",
                new=AsyncMock(return_value="users(id, email)"),
            ),
            patch.object(orch, "_run_complex_pipeline", pipeline_mock),
            patch.object(orch, "_check_pipeline_resume", new=AsyncMock(return_value=None)),
        ):
            result = await orch.run(context)

        pipeline_mock.assert_awaited_once()
        assert result is _SENTINEL_RESPONSE

    @pytest.mark.asyncio
    async def test_no_data_source_does_not_use_pipeline(self, orch, mock_llm, mock_tracker):
        """Guard: when no data source exists at all, pipeline must NOT be called
        (the unified loop handles the no-source degenerate case)."""
        context = _make_context(mock_llm, mock_tracker, has_connection=False)

        pipeline_mock = AsyncMock(return_value=_SENTINEL_RESPONSE)
        unified_mock = AsyncMock(return_value=_SENTINEL_RESPONSE)

        with (
            patch(
                "app.agents.orchestrator.route_request",
                new=AsyncMock(return_value=_complex_knowledge_route()),
            ),
            patch.object(
                orch._ctx_loader,
                "has_knowledge_base",
                return_value=False,
            ),
            patch.object(
                orch._ctx_loader,
                "has_mcp_sources",
                new=AsyncMock(return_value=False),
            ),
            patch.object(
                orch._ctx_loader,
                "has_repo",
                return_value=False,
            ),
            patch.object(
                orch._ctx_loader,
                "check_staleness",
                new=AsyncMock(return_value=None),
            ),
            patch.object(orch, "_run_complex_pipeline", pipeline_mock),
            patch.object(orch, "_run_unified_agent", unified_mock),
            patch.object(orch, "_check_pipeline_resume", new=AsyncMock(return_value=None)),
        ):
            await orch.run(context)

        pipeline_mock.assert_not_awaited()
        unified_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# T2: _quick_data_plan fallback tool (ORCH-P04)
# ---------------------------------------------------------------------------


class TestQuickDataPlanFallbackTool:
    def test_quick_data_plan_default_is_query_database(self):
        """Default call (no fallback_tool) must produce query_database stage."""
        plan = AdaptivePlanner._quick_data_plan("some question")
        assert len(plan.stages) == 1
        assert plan.stages[0].tool == "query_database"

    def test_quick_data_plan_uses_search_codebase(self):
        """ORCH-P04: passing fallback_tool='search_codebase' must use that tool."""
        plan = AdaptivePlanner._quick_data_plan("some question", fallback_tool="search_codebase")
        assert len(plan.stages) == 1
        assert plan.stages[0].tool == "search_codebase"

    def test_quick_data_plan_uses_analyze_git(self):
        """ORCH-P04: passing fallback_tool='analyze_git' must use that tool."""
        plan = AdaptivePlanner._quick_data_plan("git history question", fallback_tool="analyze_git")
        assert len(plan.stages) == 1
        assert plan.stages[0].tool == "analyze_git"

    def test_quick_data_plan_uses_query_mcp_source(self):
        """ORCH-P04: passing fallback_tool='query_mcp_source' must use that tool."""
        plan = AdaptivePlanner._quick_data_plan("mcp question", fallback_tool="query_mcp_source")
        assert len(plan.stages) == 1
        assert plan.stages[0].tool == "query_mcp_source"

    @pytest.mark.asyncio
    async def test_plan_passes_fallback_tool_to_quick_plan_on_llm_failure(self):
        """AdaptivePlanner.plan(fallback_tool='search_codebase') — when LLM
        planning fails (returns None), the quick-plan stage must use that tool."""
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=MagicMock(tool_calls=[]))

        planner = AdaptivePlanner(mock_router)

        with patch.object(planner, "_llm_plan", new=AsyncMock(return_value=None)):
            plan = await planner.plan(
                "How does auth work?",
                fallback_tool="search_codebase",
            )

        assert plan.stages[0].tool == "search_codebase"

    @pytest.mark.asyncio
    async def test_plan_default_fallback_tool_on_llm_failure(self):
        """AdaptivePlanner.plan() with no fallback_tool → default query_database."""
        mock_router = MagicMock()
        planner = AdaptivePlanner(mock_router)

        with patch.object(planner, "_llm_plan", new=AsyncMock(return_value=None)):
            plan = await planner.plan("How many users?")

        assert plan.stages[0].tool == "query_database"
