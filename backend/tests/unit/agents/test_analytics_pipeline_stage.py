"""The multi-stage pipeline must be able to execute an analytics stage (A1).

Before this, ``StageExecutor`` dispatched six tools and ``query_analytics_source``
was not among them, while the planner's vocabulary did not name it either. The
orchestrator knew: ``_run_complex_pipeline`` carried a T13 workaround that bounced
an *analytics-only* project to the flat loop. What the workaround could not cover
is the case the product is sold on — analytics **plus** a database, where the
pipeline ran and analytics was silently absent from it.

Every test here fails against that shape. ``TestTheStageIsReachable`` fails with
``Unknown tool``; ``TestRowsReachTheNextStage`` fails because no stage populated
``query_result``; ``TestTenantScope`` fails because the resolver did not exist.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest

from app.agents.base import AgentContext
from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext
from app.agents.stage_executor import StageExecutor
from app.agents.stage_validator import StageValidationOutcome, StageValidator
from app.connectors.base import ConnectionConfig
from app.core.workflow_tracker import WorkflowTracker

# ------------------------------------------------------------------
# Doubles
# ------------------------------------------------------------------


@dataclass
class _FakeAnalyticsResult:
    """Stands in for ``AnalyticsResult`` without importing the GA4 client stack.

    Only the fields the stage is allowed to read are present: a field the stage
    reads but this double omits raises ``AttributeError`` in the test rather
    than silently returning a Mock.
    """

    status: str = "success"
    answer: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None
    token_usage: dict[str, int] = field(default_factory=dict)


class _FakeConnection:
    """The three fields the stage needs off a resolved ``Connection``."""

    def __init__(self, cid: str = "conn-ga4", project_id: str = "proj-1") -> None:
        self.id = cid
        self.project_id = project_id
        self.source_type = "ga4"
        self.name = "Marketing GA4"


@pytest.fixture
def mock_tracker():
    return create_autospec(WorkflowTracker, instance=True)


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    return router


@pytest.fixture
def mock_analytics_agent():
    agent = MagicMock()
    agent.run = AsyncMock(return_value=_FakeAnalyticsResult())
    return agent


@pytest.fixture
def executor(mock_llm, mock_tracker, mock_analytics_agent):
    validator = MagicMock(spec=StageValidator)
    validator.validate = MagicMock(return_value=StageValidationOutcome(passed=True))
    return StageExecutor(
        sql_agent=AsyncMock(),
        knowledge_agent=AsyncMock(),
        llm_router=mock_llm,
        tracker=mock_tracker,
        validator=validator,
        analytics_agent=mock_analytics_agent,
    )


@pytest.fixture
def context(mock_llm, mock_tracker) -> AgentContext:
    return AgentContext(
        project_id="proj-1",
        connection_config=ConnectionConfig(db_type="postgres"),
        user_question="compare GA4 sessions with signups",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-test",
    )


def _analytics_stage(stage_id: str = "an1") -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description="fetch GA4 sessions per day",
        tool="query_analytics_source",
    )


def _plan(*stages: PlanStage) -> ExecutionPlan:
    return ExecutionPlan(plan_id="plan-test", question="q", stages=list(stages))


def _resolver_returns(conn: _FakeConnection | None = None, exc: Exception | None = None):
    """Patch the one shared resolver, so no test here opens a real session."""
    target = "app.services.connection_service.ConnectionService.resolve_analytics_connection"
    if exc is not None:
        return patch(target, new=AsyncMock(side_effect=exc))
    return patch(target, new=AsyncMock(return_value=conn or _FakeConnection()))


# ------------------------------------------------------------------
# REQ-1 — the stage is reachable at all
# ------------------------------------------------------------------


class TestTheStageIsReachable:
    @pytest.mark.asyncio
    async def test_dispatch_does_not_report_unknown_tool(self, executor, context):
        stage = _analytics_stage()
        with _resolver_returns():
            result = await executor._execute_stage(stage, StageContext(plan=_plan(stage)), context)

        assert result.error is None or "Unknown tool" not in result.error, (
            "query_analytics_source must be a dispatched tool, not an unknown one; "
            f"got status={result.status} error={result.error}"
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_the_analytics_agent_is_actually_called(
        self, executor, context, mock_analytics_agent
    ):
        stage = _analytics_stage()
        with _resolver_returns():
            await executor._execute_stage(stage, StageContext(plan=_plan(stage)), context)

        mock_analytics_agent.run.assert_awaited_once()
        kwargs = mock_analytics_agent.run.await_args.kwargs
        # The agent's signature is NOT BaseAgent.run(ctx, question=…): it needs
        # the resolved connection's identity, which is why the stage resolves
        # first instead of forwarding blindly.
        assert kwargs["connection_id"] == "conn-ga4"
        assert kwargs["source_type"] == "ga4"
        assert kwargs["source_name"] == "Marketing GA4"
        assert kwargs["question"], "the stage question must reach the agent"

    def test_the_tool_name_matches_the_orchestrator_tool(self):
        """One spelling. A stage case that disagrees with the tool is dead code."""
        from app.agents.tools.analytics_tools import QUERY_ANALYTICS_SOURCE_TOOL

        src = Path(inspect.getfile(StageExecutor)).read_text(encoding="utf-8")
        assert f'case "{QUERY_ANALYTICS_SOURCE_TOOL.name}"' in src, (
            "stage_executor must dispatch on exactly the tool name the "
            f"orchestrator offers ({QUERY_ANALYTICS_SOURCE_TOOL.name})"
        )


# ------------------------------------------------------------------
# REQ-3 — rows reach the next stage
# ------------------------------------------------------------------


class TestRowsReachTheNextStage:
    @pytest.mark.asyncio
    async def test_query_result_is_populated_from_columns_and_rows(
        self, executor, context, mock_analytics_agent
    ):
        mock_analytics_agent.run.return_value = _FakeAnalyticsResult(
            status="success",
            answer="Sessions rose 12%.",
            columns=["date", "sessions"],
            rows=[["2026-08-01", 1200], ["2026-08-02", 1344]],
        )
        stage = _analytics_stage()
        with _resolver_returns():
            result = await executor._execute_stage(stage, StageContext(plan=_plan(stage)), context)

        assert result.query_result is not None, (
            "without query_result a downstream process_data stage has nothing to "
            "align GA4 days against a daily aggregate from the database"
        )
        assert result.query_result.columns == ["date", "sessions"]
        assert result.query_result.rows == [["2026-08-01", 1200], ["2026-08-02", 1344]]
        assert result.query_result.row_count == 2, "row_count must be the real count, not 0"
        assert result.summary == "Sessions rose 12%."

    @pytest.mark.asyncio
    async def test_truncation_travels_with_the_rows(self, executor, context, mock_analytics_agent):
        mock_analytics_agent.run.return_value = _FakeAnalyticsResult(
            status="success", columns=["date"], rows=[["2026-08-01"]], truncated=True
        )
        stage = _analytics_stage()
        with _resolver_returns():
            result = await executor._execute_stage(stage, StageContext(plan=_plan(stage)), context)

        assert result.query_result is not None
        assert result.query_result.truncated is True, (
            "a capped read that arrives looking complete is the failure the "
            "analytics module exists to prevent; DataGate reads this flag"
        )

    @pytest.mark.asyncio
    async def test_a_text_only_answer_still_succeeds(self, executor, context, mock_analytics_agent):
        """No rows is not a failure — the agent may answer from coverage alone."""
        mock_analytics_agent.run.return_value = _FakeAnalyticsResult(
            status="success", answer="August is fully collected.", columns=[], rows=[]
        )
        stage = _analytics_stage()
        with _resolver_returns():
            result = await executor._execute_stage(stage, StageContext(plan=_plan(stage)), context)

        assert result.status == "success"
        assert result.summary == "August is fully collected."


# ------------------------------------------------------------------
# REQ-8 — the agent's three statuses map to three categories
# ------------------------------------------------------------------


class TestStatusMapping:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("agent_status", "expected_category"),
        [("no_result", "data_missing"), ("error", "configuration")],
    )
    async def test_non_success_maps_like_the_mcp_stage(
        self, executor, context, mock_analytics_agent, agent_status, expected_category
    ):
        mock_analytics_agent.run.return_value = _FakeAnalyticsResult(
            status=agent_status, answer="placeholder text", error="boom"
        )
        stage = _analytics_stage()
        with _resolver_returns():
            result = await executor._execute_stage(stage, StageContext(plan=_plan(stage)), context)

        assert result.status == "error"
        assert result.error_category == expected_category
        assert result.summary != "placeholder text", (
            "a no_result placeholder must never be surfaced as a real answer"
        )

    @pytest.mark.asyncio
    async def test_an_exception_is_caught_and_classified(
        self, executor, context, mock_analytics_agent
    ):
        mock_analytics_agent.run.side_effect = RuntimeError("vendor exploded")
        stage = _analytics_stage()
        with _resolver_returns():
            result = await executor._execute_stage(stage, StageContext(plan=_plan(stage)), context)

        assert result.status == "error"
        assert "vendor exploded" in (result.error or "")


# ------------------------------------------------------------------
# REQ-2 — the tenant check is the resolver's, and there is one resolver
# ------------------------------------------------------------------


class TestTenantScope:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("reason", ["not_found", "wrong_project", "none_connected"])
    async def test_an_unavailable_connection_is_a_configuration_failure(
        self, executor, context, reason
    ):
        from app.services.connection_service import AnalyticsConnectionUnavailableError

        stage = _analytics_stage()
        with _resolver_returns(exc=AnalyticsConnectionUnavailableError(reason)):
            result = await executor._execute_stage(stage, StageContext(plan=_plan(stage)), context)

        assert result.status == "error"
        assert result.error_category == "configuration", (
            "an unreachable analytics source is a configuration failure, not a "
            "transient one — retrying cannot make the connection appear"
        )

    @pytest.mark.asyncio
    async def test_the_stage_never_reaches_the_agent_without_a_resolved_connection(
        self, executor, context, mock_analytics_agent
    ):
        from app.services.connection_service import AnalyticsConnectionUnavailableError

        stage = _analytics_stage()
        with _resolver_returns(exc=AnalyticsConnectionUnavailableError("wrong_project")):
            await executor._execute_stage(stage, StageContext(plan=_plan(stage)), context)

        mock_analytics_agent.run.assert_not_awaited()

    def test_the_dispatcher_does_not_re_implement_the_project_check(self):
        """#267 was one check written per entry point, and one point lacked it.

        The dispatcher's analytics handler must delegate the scope decision to
        the shared resolver rather than comparing ``project_id`` itself.
        """
        from app.agents import tool_dispatcher

        src = Path(inspect.getfile(tool_dispatcher)).read_text(encoding="utf-8")
        start = src.index("async def _handle_query_analytics_source")
        # The handler may be the last method in the file, so a missing next
        # sibling means "to the end", not a test error.
        nxt = src.find("\n    async def ", start + 10)
        handler = src[start:] if nxt == -1 else src[start:nxt]

        assert "resolve_analytics_connection" in handler, (
            "the dispatcher must use the shared resolver so the tenant check "
            "exists in exactly one place"
        )
        assert "conn.project_id != context.project_id" not in handler, (
            "the project comparison belongs in the resolver, not copied here"
        )


# ------------------------------------------------------------------
# REQ-7 — the import stays lazy
# ------------------------------------------------------------------


class TestTheImportStaysLazy:
    def test_stage_executor_has_no_module_level_analytics_import(self):
        """``analytics_agent`` pulls in the Google client stack.

        ``tool_dispatcher`` imports it inside the handler for exactly this
        reason (tool_dispatcher.py:33-36). A module-level import here would put
        that cost on every orchestrator construction, including the flat loop.
        """
        src = Path(inspect.getfile(StageExecutor)).read_text(encoding="utf-8")
        offenders = [
            line
            for line in src.splitlines()
            if line.startswith(("from app.agents.analytics_agent", "import app.agents.analytics"))
        ]
        assert not offenders, (
            "analytics_agent must be imported inside the stage, not at module "
            f"level; found: {offenders}"
        )
