"""T13 — the analytics source capability must be wired through the orchestrator.

T8 built ``AnalyticsAgent``, ``QUERY_ANALYTICS_SOURCE_TOOL``,
``ContextLoader.has_analytics_sources`` and the dispatcher handler, but the
orchestrator never consulted the probe, so the tool was never offered in
production and an analytics-only project looked like a project with **no data
source at all**.

These tests pin the wiring end to end:

1. an analytics-only project (GA4, no database, no repo, no KB) is treated as
   having a data source and is offered ``query_analytics_source``;
2. a project without an analytics connection is not;
3. a project with both a database and GA4 is offered both tools;
4. the direct-response route escalates to the tool loop for an analytics-only
   project instead of answering from prior knowledge;
5. **coverage** — every ``get_orchestrator_tools`` call site that learns about
   MCP also learns about analytics, every internal helper call that forwards
   ``has_mcp`` also forwards ``has_analytics``, and every helper signature that
   accepts ``has_mcp`` also accepts ``has_analytics``.  (5) is the mechanical
   guard that catches a *future* site being added for MCP but not analytics.

No network: the LLM router and the workflow tracker are mocked throughout.
"""

from __future__ import annotations

import ast
import inspect
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.agents.orchestrator as orchestrator_module
from app.agents.base import AgentContext
from app.agents.orchestrator import AgentResponse, OrchestratorAgent
from app.agents.prompts.orchestrator_prompt import NEEDS_DATA_SENTINEL
from app.agents.router import RouteResult
from app.agents.tools.orchestrator_tools import (
    get_orchestrator_tools as real_get_orchestrator_tools,
)
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse

# ---------------------------------------------------------------------------
# Shared doubles (same conventions as test_orchestrator_nondb_pipeline.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()
    t.has_ended = MagicMock(return_value=False)

    @asynccontextmanager
    async def fake_step(wf_id: str, step: str, detail: str = "", **kwargs: Any):
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
        user_question="How many sessions did we get from organic search last week?",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
        project_name="TestProject",
    )


def _route(complexity: str = "moderate", route: str = "explore") -> RouteResult:
    return RouteResult(
        route=route,
        complexity=complexity,
        approach="Look at the collected analytics data.",
        estimated_queries=1,
        needs_multiple_data_sources=False,
    )


_SENTINEL_RESPONSE = AgentResponse(answer="loop ran", response_type="text")


def _stub_sources(
    orch: OrchestratorAgent,
    *,
    has_kb: bool = False,
    has_mcp: bool = False,
    has_repo: bool = False,
    has_analytics: bool = False,
) -> list[Any]:
    """Patch every capability probe + context load so ``run`` needs no DB/LLM.

    Returns the list of ``patch`` context managers the caller enters.
    """
    return [
        patch.object(orch._ctx_loader, "has_knowledge_base", return_value=has_kb),
        patch.object(orch._ctx_loader, "has_mcp_sources", new=AsyncMock(return_value=has_mcp)),
        patch.object(orch._ctx_loader, "has_repo", return_value=has_repo),
        patch.object(
            orch._ctx_loader,
            "has_analytics_sources",
            new=AsyncMock(return_value=has_analytics),
        ),
        patch.object(orch._ctx_loader, "check_staleness", new=AsyncMock(return_value=None)),
        patch.object(orch._ctx_loader, "load_project_overview", new=AsyncMock(return_value="")),
        patch.object(orch._ctx_loader, "load_recent_learnings", new=AsyncMock(return_value="")),
        patch.object(orch._ctx_loader, "load_relevant_insights", new=AsyncMock(return_value="")),
        patch.object(
            orch._ctx_loader, "resolve_connection_id", new=AsyncMock(return_value="conn-1")
        ),
        patch.object(orch._ctx_loader, "build_table_map", new=AsyncMock(return_value="")),
        patch.object(orch, "_load_custom_rules_text", new=AsyncMock(return_value="")),
        patch.object(orch, "_check_pipeline_resume", new=AsyncMock(return_value=None)),
    ]


async def _run_and_capture_tools(
    orch: OrchestratorAgent,
    context: AgentContext,
    *,
    has_kb: bool = False,
    has_mcp: bool = False,
    has_repo: bool = False,
    has_analytics: bool = False,
) -> tuple[MagicMock, list[str], AsyncMock]:
    """Drive ``run`` down the unified loop with ``get_orchestrator_tools`` spied.

    The spy delegates to the real factory so the captured tool names are the
    real ones; ``_run_tool_loop`` is stubbed so no LLM is needed.
    """
    offered: list[str] = []

    def _spy(**kwargs: Any) -> list[Any]:
        tools = real_get_orchestrator_tools(**kwargs)
        offered.extend(t.name for t in tools)
        return tools

    tools_spy = MagicMock(side_effect=_spy)
    loop_mock = AsyncMock(return_value=_SENTINEL_RESPONSE)

    from contextlib import ExitStack

    with ExitStack() as stack:
        for cm in _stub_sources(
            orch,
            has_kb=has_kb,
            has_mcp=has_mcp,
            has_repo=has_repo,
            has_analytics=has_analytics,
        ):
            stack.enter_context(cm)
        stack.enter_context(
            patch("app.agents.orchestrator.route_request", new=AsyncMock(return_value=_route()))
        )
        stack.enter_context(patch("app.agents.orchestrator.get_orchestrator_tools", tools_spy))
        stack.enter_context(patch.object(orch, "_run_tool_loop", loop_mock))
        await orch.run(context)

    return tools_spy, offered, loop_mock


# ---------------------------------------------------------------------------
# 1-3: the tool is offered exactly when the project has an analytics source
# ---------------------------------------------------------------------------


class TestAnalyticsToolIsOffered:
    async def test_analytics_only_project_is_a_data_source_and_gets_the_tool(
        self, orch, mock_llm, mock_tracker
    ):
        """GA4 only — no database, no repo, no KB.

        The orchestrator must consult ``has_analytics_sources``, pass
        ``has_analytics_sources=True`` to ``get_orchestrator_tools``, and offer
        ``query_analytics_source``.
        """
        context = _make_context(mock_llm, mock_tracker, has_connection=False)

        tools_spy, offered, loop_mock = await _run_and_capture_tools(
            orch, context, has_analytics=True
        )

        tools_spy.assert_called_once()
        assert tools_spy.call_args.kwargs.get("has_analytics_sources") is True, (
            "get_orchestrator_tools must be called with has_analytics_sources=True; "
            f"got kwargs={tools_spy.call_args.kwargs}"
        )
        assert "query_analytics_source" in offered, (
            f"query_analytics_source must be offered, got {sorted(offered)}"
        )
        loop_mock.assert_awaited_once()
        assert loop_mock.await_args.kwargs.get("has_analytics") is True, (
            "_run_tool_loop must receive has_analytics=True; "
            f"got kwargs={loop_mock.await_args.kwargs}"
        )

    async def test_project_without_analytics_does_not_get_the_tool(
        self, orch, mock_llm, mock_tracker
    ):
        context = _make_context(mock_llm, mock_tracker, has_connection=True)

        tools_spy, offered, _ = await _run_and_capture_tools(orch, context, has_analytics=False)

        tools_spy.assert_called_once()
        assert tools_spy.call_args.kwargs.get("has_analytics_sources") is False
        assert "query_analytics_source" not in offered, (
            f"query_analytics_source must be absent, got {sorted(offered)}"
        )

    async def test_database_and_analytics_offers_both_tools(self, orch, mock_llm, mock_tracker):
        context = _make_context(mock_llm, mock_tracker, has_connection=True)

        _, offered, _ = await _run_and_capture_tools(orch, context, has_analytics=True)

        assert {"query_database", "query_analytics_source"} <= set(offered), (
            f"both tools must be offered, got {sorted(offered)}"
        )


# ---------------------------------------------------------------------------
# 4: an analytics-only project is not "no data source"
# ---------------------------------------------------------------------------


class TestAnalyticsCountsAsADataSource:
    async def test_complex_question_reaches_the_pipeline_gate(self, orch, mock_llm, mock_tracker):
        """``has_any_data_source`` must include analytics.

        Without it a complex question on an analytics-only project is handled as
        if the project had nothing connected.
        """
        context = _make_context(mock_llm, mock_tracker, has_connection=False)
        pipeline_mock = AsyncMock(return_value=_SENTINEL_RESPONSE)

        from contextlib import ExitStack

        with ExitStack() as stack:
            for cm in _stub_sources(orch, has_analytics=True):
                stack.enter_context(cm)
            stack.enter_context(
                patch(
                    "app.agents.orchestrator.route_request",
                    new=AsyncMock(return_value=_route(complexity="complex")),
                )
            )
            stack.enter_context(patch.object(orch, "_run_complex_pipeline", pipeline_mock))
            await orch.run(context)

        pipeline_mock.assert_awaited_once()
        assert pipeline_mock.await_args.kwargs.get("has_analytics") is True, (
            "_run_complex_pipeline must receive has_analytics=True; "
            f"got kwargs={pipeline_mock.await_args.kwargs}"
        )

    async def test_analytics_only_pipeline_bounces_to_the_flat_loop(
        self, orch, mock_llm, mock_tracker
    ):
        """The M0 ``StageExecutor`` has no analytics stage.

        A project whose only source is analytics must therefore be bounced to
        the flat loop (where ``query_analytics_source`` IS offered) instead of
        planning stages nothing can execute.
        """
        context = _make_context(mock_llm, mock_tracker, has_connection=False)
        fallback_mock = AsyncMock(return_value=_SENTINEL_RESPONSE)
        planner_mock = AsyncMock()

        with (
            patch.object(orch, "_fallback_to_unified", fallback_mock),
            patch(
                "app.agents.orchestrator.AdaptivePlanner",
                MagicMock(return_value=MagicMock(plan=planner_mock)),
            ),
        ):
            result = await orch._run_complex_pipeline(
                context,
                "wf-1",
                "",
                None,
                None,
                has_analytics=True,
            )

        fallback_mock.assert_awaited_once()
        planner_mock.assert_not_awaited()
        assert result is _SENTINEL_RESPONSE

    async def test_direct_route_escalates_when_analytics_is_the_only_source(
        self, orch, mock_llm, mock_tracker
    ):
        """``has_data_source`` in ``_run_direct_response`` must include analytics.

        Otherwise the C1 re-route escape is dead for analytics-only projects and
        the model answers traffic questions from prior knowledge.
        """
        context = _make_context(mock_llm, mock_tracker, has_connection=False)
        llm_mock = AsyncMock(
            return_value=LLMResponse(content=NEEDS_DATA_SENTINEL, tool_calls=[], usage={})
        )

        with patch.object(orch, "_llm_call_with_retry", llm_mock):
            resp = await orch._run_direct_response(
                context,
                "wf-1",
                has_connection=False,
                has_kb=False,
                has_mcp=False,
                has_repo=False,
                has_analytics=True,
            )

        assert resp is None, "the sentinel must re-route to the tool loop, not be answered"

    async def test_direct_prompt_tells_the_model_analytics_data_exists(
        self, orch, mock_llm, mock_tracker
    ):
        """``build_direct_response_prompt`` knows nothing about analytics.

        The orchestrator must therefore state the capability itself, otherwise
        the model is told it "can only have general conversations" and never
        emits the sentinel the test above relies on.
        """
        context = _make_context(mock_llm, mock_tracker, has_connection=False)
        llm_mock = AsyncMock(return_value=LLMResponse(content="Hi!", tool_calls=[], usage={}))

        with (
            patch.object(orch, "_llm_call_with_retry", llm_mock),
            patch.object(orch, "_stream_tokens", new=AsyncMock()),
        ):
            await orch._run_direct_response(
                context,
                "wf-1",
                has_connection=False,
                has_kb=False,
                has_mcp=False,
                has_repo=False,
                has_analytics=True,
            )

        system_prompt = llm_mock.await_args.kwargs["messages"][0].content
        assert "analytics" in system_prompt.lower()
        assert NEEDS_DATA_SENTINEL in system_prompt

    async def test_tool_loop_prompt_declares_the_analytics_capability(
        self, orch, mock_llm, mock_tracker
    ):
        """The base system prompt says "no database or knowledge base is
        connected … you can only have a general conversation" for an
        analytics-only project.  The orchestrator must correct that."""
        context = _make_context(mock_llm, mock_tracker, has_connection=False)
        llm_mock = AsyncMock(return_value=LLMResponse(content="Done.", tool_calls=[], usage={}))

        with (
            patch.object(orch, "_llm_call_with_retry", llm_mock),
            patch.object(orch, "_stream_tokens", new=AsyncMock()),
            patch.object(orch, "_validate_partial_answer", new=AsyncMock(return_value=True)),
        ):
            await orch._run_tool_loop(
                context,
                "wf-1",
                has_connection=False,
                db_type=None,
                has_kb=False,
                has_mcp=False,
                has_repo=False,
                has_analytics=True,
                table_map="",
                project_overview="",
                recent_learnings="",
                tools=real_get_orchestrator_tools(has_analytics_sources=True),
            )

        system_prompt = llm_mock.await_args.kwargs["messages"][0].content
        assert "query_analytics_source" in system_prompt, (
            "the tool-loop system prompt must declare the analytics capability"
        )


# ---------------------------------------------------------------------------
# 5: mechanical coverage — no site may learn about MCP but not analytics
# ---------------------------------------------------------------------------


def _orchestrator_ast() -> ast.Module:
    source = Path(inspect.getfile(orchestrator_module)).read_text(encoding="utf-8")
    return ast.parse(source)


def _callee_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


class TestAnalyticsWiringCoverage:
    """These tests fail when a future change teaches a site about MCP only."""

    def test_every_get_orchestrator_tools_call_passes_analytics(self):
        tree = _orchestrator_ast()
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _callee_name(node) == "get_orchestrator_tools"
        ]
        assert calls, "expected at least one get_orchestrator_tools call site"

        mcp_sites = [c for c in calls if any(kw.arg == "has_mcp_sources" for kw in c.keywords)]
        analytics_sites = [
            c for c in calls if any(kw.arg == "has_analytics_sources" for kw in c.keywords)
        ]
        missing = sorted(c.lineno for c in mcp_sites if c not in analytics_sites)
        assert len(analytics_sites) == len(mcp_sites), (
            "every get_orchestrator_tools call site that receives has_mcp_sources must "
            "also receive has_analytics_sources — "
            f"{len(mcp_sites)} MCP site(s) vs {len(analytics_sites)} analytics site(s); "
            f"missing has_analytics_sources at orchestrator.py line(s) {missing}"
        )

    def test_every_helper_call_forwarding_has_mcp_also_forwards_has_analytics(self):
        tree = _orchestrator_ast()
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kwargs = {kw.arg for kw in node.keywords}
            if "has_mcp" in kwargs and "has_analytics" not in kwargs:
                offenders.append(f"{_callee_name(node)}() at line {node.lineno}")
        assert not offenders, (
            "every orchestrator helper call that forwards has_mcp must also forward "
            f"has_analytics — offenders: {offenders}"
        )

    def test_every_helper_signature_taking_has_mcp_also_takes_has_analytics(self):
        tree = _orchestrator_ast()
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            names = {
                a.arg for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            }
            if "has_mcp" in names and "has_analytics" not in names:
                offenders.append(f"{node.name}() at line {node.lineno}")
        assert not offenders, (
            "every orchestrator helper that accepts has_mcp must also accept "
            f"has_analytics — offenders: {offenders}"
        )
