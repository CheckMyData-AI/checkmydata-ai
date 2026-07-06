"""ORCH-A03: route/complexity/estimated_queries written into context.extra + RequestMetrics.

Tests that after routing:
1. context.extra carries "route", "complexity", "estimated_queries" from route_result.
2. _record_request_metrics receives the REAL complexity (not "unknown") and estimated_queries.
3. The complex-pipeline path also captures complexity/estimated_queries in its metrics row.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.orchestrator import OrchestratorAgent
from app.agents.router import RouteResult
from app.core.metrics import RequestMetrics
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse

# ---------------------------------------------------------------------------
# Shared test doubles
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-test")
    t.end = AsyncMock()
    t.emit = AsyncMock()
    t.has_ended = MagicMock(return_value=False)

    @asynccontextmanager
    async def fake_step(wf_id, step, detail="", **kwargs):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


@pytest.fixture()
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    router.get_context_window = MagicMock(return_value=128_000)
    router._sink = None
    return router


@pytest.fixture()
def mock_vs():
    vs = MagicMock()
    collection = MagicMock()
    collection.count = MagicMock(return_value=0)
    vs.get_or_create_collection = MagicMock(return_value=collection)
    return vs


@pytest.fixture()
def orch(mock_llm, mock_vs, mock_tracker):
    return OrchestratorAgent(
        llm_router=mock_llm,
        vector_store=mock_vs,
        workflow_tracker=mock_tracker,
    )


@pytest.fixture()
def base_context(mock_llm, mock_tracker):
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="How many users signed up last week?",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-test",
        project_name="TestProject",
    )


# ---------------------------------------------------------------------------
# Helper — a RouteResult that goes to the unified path (no connection_config)
# ---------------------------------------------------------------------------

_COMPLEX_ROUTE_RESULT = RouteResult(
    route="query",
    complexity="complex",
    approach="Run a multi-table SQL query.",
    estimated_queries=4,
    needs_multiple_data_sources=False,
)


# ---------------------------------------------------------------------------
# T4-1: complexity / estimated_queries reach the metrics row (unified path)
# ---------------------------------------------------------------------------


class TestComplexityWrittenToContextExtra:
    """After routing, context.extra must carry the 3 router signals so the
    metrics helper receives the REAL values instead of "unknown"/0."""

    @pytest.mark.asyncio
    async def test_complexity_written_to_context_extra(
        self,
        orch,
        mock_llm,
        mock_tracker,
        base_context,
    ):
        """Unified path: _record_request_metrics gets complexity='complex' and
        estimated_queries=4, NOT "unknown"/0."""

        # Patch route_request to return a known RouteResult
        route_res = _COMPLEX_ROUTE_RESULT
        with patch(
            "app.agents.orchestrator.route_request",
            new=AsyncMock(return_value=route_res),
        ):
            # LLM returns a simple no-tool answer so the loop exits cleanly
            mock_llm.complete = AsyncMock(return_value=LLMResponse(content="42 users signed up."))

            # Capture RequestMetrics rows passed to record_request
            recorded: list[RequestMetrics] = []

            with patch("app.core.metrics.get_metrics_collector") as gmc:
                collector = MagicMock()
                collector.record_request.side_effect = recorded.append
                gmc.return_value = collector

                # Stub out the heavy ContextLoader methods that hit the DB
                with (
                    patch.object(orch._ctx_loader, "has_knowledge_base", return_value=False),
                    patch.object(
                        orch._ctx_loader, "has_mcp_sources", new=AsyncMock(return_value=False)
                    ),
                    patch.object(orch._ctx_loader, "has_repo", return_value=False),
                    patch.object(
                        orch._ctx_loader,
                        "check_staleness",
                        new=AsyncMock(return_value=None),
                    ),
                    patch.object(
                        orch._ctx_loader,
                        "load_project_overview",
                        new=AsyncMock(return_value=None),
                    ),
                    patch.object(
                        orch._ctx_loader,
                        "load_recent_learnings",
                        new=AsyncMock(return_value=""),
                    ),
                    patch.object(
                        orch._ctx_loader,
                        "load_relevant_insights",
                        new=AsyncMock(return_value=""),
                    ),
                ):
                    await orch.run(base_context)

        assert recorded, "No RequestMetrics row was recorded — _record_request_metrics not called"
        row = recorded[-1]  # last row = the final metrics call

        assert row.complexity == "complex", (
            f"Expected complexity='complex', got '{row.complexity}' — "
            "route_result.complexity is not being written into context.extra"
        )
        assert row.estimated_queries == 4, (
            f"Expected estimated_queries=4, got {row.estimated_queries}"
        )


# ---------------------------------------------------------------------------
# T4-2: route signal survives into metrics on the complex (pipeline) path
# ---------------------------------------------------------------------------


class TestRouteSignalSurvivesIntoPipelineMetrics:
    """Complex pipeline path: RequestMetrics carries the router's complexity
    and estimated_queries, not the hard-coded fallback "complex"/0."""

    @pytest.mark.asyncio
    async def test_route_signal_survives_into_metrics_on_complex_path(
        self,
        orch,
        mock_llm,
        mock_tracker,
    ):
        from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
        from app.connectors.base import ConnectionConfig

        conn_cfg = MagicMock(spec=ConnectionConfig)
        conn_cfg.db_type = "postgresql"
        conn_cfg.connection_id = "conn-1"

        ctx = AgentContext(
            project_id="proj-1",
            connection_config=conn_cfg,
            user_question="Compare monthly active users across three products.",
            chat_history=[],
            llm_router=mock_llm,
            tracker=mock_tracker,
            workflow_id="wf-test",
            project_name="TestProject",
        )

        # route_result → use_complex_pipeline=True (complexity=complex)
        route_res = RouteResult(
            route="query",
            complexity="complex",
            approach="Multi-stage pipeline.",
            estimated_queries=5,
            needs_multiple_data_sources=False,
        )

        plan = ExecutionPlan(
            plan_id="plan-1",
            question="Compare MAUs",
            stages=[
                PlanStage(
                    stage_id="s1",
                    description="Get MAU per product",
                    tool="query_database",
                    depends_on=[],
                )
            ],
        )
        stage_ctx = StageContext(plan=plan)
        stage_ctx.results["s1"] = StageResult(
            stage_id="s1",
            status="success",
            summary="MAU data",
        )

        from app.agents.stage_executor import _StageExecutorResult

        exec_result = _StageExecutorResult(
            stage_ctx=stage_ctx,
            status="completed",
            final_answer="Users: ...",
        )

        recorded: list[RequestMetrics] = []

        with (
            patch("app.agents.orchestrator.route_request", new=AsyncMock(return_value=route_res)),
            patch.object(orch._ctx_loader, "has_knowledge_base", return_value=False),
            patch.object(orch._ctx_loader, "has_mcp_sources", new=AsyncMock(return_value=False)),
            patch.object(orch._ctx_loader, "has_repo", return_value=False),
            patch.object(orch._ctx_loader, "check_staleness", new=AsyncMock(return_value=None)),
            patch.object(orch._ctx_loader, "load_recent_learnings", new=AsyncMock(return_value="")),
            patch.object(
                orch._ctx_loader, "load_relevant_insights", new=AsyncMock(return_value="")
            ),
            patch.object(orch, "_load_table_map", new=AsyncMock(return_value="users(id, name)")),
            # Patch AdaptivePlanner.plan at the class level (local var in _run_complex_pipeline)
            patch("app.agents.orchestrator.AdaptivePlanner.plan", new=AsyncMock(return_value=plan)),
            # Patch StageExecutor.execute at the class level
            patch(
                "app.agents.orchestrator.StageExecutor.execute",
                new=AsyncMock(return_value=exec_result),
            ),
            # Suppress DB-touching helpers
            patch.object(
                orch, "_create_pipeline_run", new=AsyncMock(return_value=MagicMock(id="run-1"))
            ),
            patch.object(orch, "_extract_pipeline_learnings", new=AsyncMock(return_value=None)),
            patch.object(orch, "_persist_stage_results", new=AsyncMock(return_value=None)),
            patch.object(orch, "_end_pipeline_workflow", new=AsyncMock(return_value=None)),
            patch("app.core.metrics.get_metrics_collector") as gmc,
        ):
            collector = MagicMock()
            collector.record_request.side_effect = recorded.append
            gmc.return_value = collector

            await orch.run(ctx)

        assert recorded, "No RequestMetrics row recorded on complex pipeline path"
        row = recorded[-1]

        assert row.complexity == "complex", f"Expected complexity='complex', got '{row.complexity}'"
        assert row.estimated_queries == 5, (
            f"Expected estimated_queries=5, got {row.estimated_queries}"
        )
