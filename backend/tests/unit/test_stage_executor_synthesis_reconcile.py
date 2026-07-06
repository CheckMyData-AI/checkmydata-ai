"""Unit tests for reconciliation note injection in pipeline synthesis (ORCH-P01/T12).

Verifies that `StageExecutor._synthesize` appends a reconciliation note
to the LLM user message when two `query_database` stages have SQL results
whose grand totals reconcile — matching the flat-loop parity requirement.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest

from app.agents.base import AgentContext
from app.agents.stage_context import (
    ExecutionPlan,
    PlanStage,
    StageContext,
    StageResult,
)
from app.agents.stage_executor import StageExecutor
from app.agents.stage_validator import StageValidationOutcome, StageValidator
from app.connectors.base import ConnectionConfig, QueryResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _qr(columns: list[str], rows: list[list], row_count: int | None = None) -> QueryResult:
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=row_count if row_count is not None else len(rows),
    )


def _sql_stage(stage_id: str) -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description=f"Query {stage_id}",
        tool="query_database",
    )


def _make_plan(*stages: PlanStage) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-reconcile-test",
        question="What is total revenue?",
        stages=list(stages),
    )


@pytest.fixture
def mock_tracker():
    return create_autospec(WorkflowTracker, instance=True)


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    return router


@pytest.fixture
def mock_validator():
    v = MagicMock(spec=StageValidator)
    v.validate = MagicMock(return_value=StageValidationOutcome(passed=True))
    return v


@pytest.fixture
def executor(mock_llm, mock_tracker, mock_validator):
    return StageExecutor(
        sql_agent=AsyncMock(),
        knowledge_agent=AsyncMock(),
        llm_router=mock_llm,
        tracker=mock_tracker,
        validator=mock_validator,
    )


@pytest.fixture
def context(mock_llm, mock_tracker) -> AgentContext:
    return AgentContext(
        project_id="proj-reconcile",
        connection_config=ConnectionConfig(db_type="postgres"),
        user_question="What is total revenue?",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-reconcile-test",
    )


# ---------------------------------------------------------------------------
# Patch helper
# ---------------------------------------------------------------------------


@contextmanager
def patch_llm_call_with_retry(side_effect_fn):
    """Patch `llm_call_with_retry` in stage_executor to capture messages."""

    async def _fake_llm_call_with_retry(llm, *, messages, tools, **kwargs):
        return await side_effect_fn(messages=messages, tools=tools, **kwargs)

    with patch(
        "app.agents.stage_executor.llm_call_with_retry",
        side_effect=_fake_llm_call_with_retry,
    ):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineSynthesisReconciliationNote:
    """The synthesize step must inject a reconciliation guard when SQL stages reconcile."""

    async def test_pipeline_synthesis_includes_reconciliation_note_when_totals_match(
        self, executor, context, mock_llm
    ):
        """Two query_database stages with identical grand totals → reconciliation note injected."""
        # Both stages produce a `revenue` column summing to 12345.00.
        qr1 = _qr(["revenue"], [[1000.0], [2345.0], [9000.0]])  # sum = 12345
        qr2 = _qr(["revenue"], [[5000.0], [7345.0]])  # sum = 12345

        plan = _make_plan(_sql_stage("s1"), _sql_stage("s2"))
        stage_ctx = StageContext(plan=plan)
        stage_ctx.set_result("s1", StageResult(stage_id="s1", query="SELECT …", query_result=qr1))
        stage_ctx.set_result("s2", StageResult(stage_id="s2", query="SELECT …", query_result=qr2))

        # Stub LLM to echo the user message back so we can inspect it.
        captured_messages: list = []

        async def _echo_llm(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            return LLMResponse(content="ok", tool_calls=[], usage={})

        mock_llm.complete = AsyncMock(side_effect=_echo_llm)

        with patch_llm_call_with_retry(_echo_llm):
            answer, degraded = await executor._synthesize(stage_ctx, context)

        assert degraded is None
        # Find the user message content sent to the LLM.
        user_parts = [m.content for m in captured_messages if m.role == "user"]
        assert user_parts, "No user message was sent to the LLM"
        user_text = user_parts[-1]
        assert "RECONCIL" in user_text.upper(), (
            f"Expected reconciliation note in LLM user message, got:\n{user_text}"
        )

    async def test_pipeline_synthesis_no_reconciliation_note_with_single_sql_stage(
        self, executor, context, mock_llm
    ):
        """Single query_database stage → no reconciliation note."""
        qr1 = _qr(["revenue"], [[5000.0], [7345.0]])

        plan = _make_plan(_sql_stage("s1"))
        stage_ctx = StageContext(plan=plan)
        stage_ctx.set_result("s1", StageResult(stage_id="s1", query="SELECT …", query_result=qr1))

        captured_messages: list = []

        async def _echo_llm(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            return LLMResponse(content="ok", tool_calls=[], usage={})

        with patch_llm_call_with_retry(_echo_llm):
            answer, degraded = await executor._synthesize(stage_ctx, context)

        assert degraded is None
        user_parts = [m.content for m in captured_messages if m.role == "user"]
        assert user_parts
        user_text = user_parts[-1]
        assert "SQL RECONCILIATION" not in user_text, (
            "Should NOT inject reconciliation note for a single SQL stage"
        )

    async def test_pipeline_synthesis_no_reconciliation_note_with_no_sql_stages(
        self, executor, context, mock_llm
    ):
        """Zero query_database stages (no results) → no reconciliation note."""
        plan = _make_plan(PlanStage(stage_id="k1", description="Knowledge", tool="search_codebase"))
        stage_ctx = StageContext(plan=plan)
        # No results set.

        captured_messages: list = []

        async def _echo_llm(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            return LLMResponse(content="ok", tool_calls=[], usage={})

        with patch_llm_call_with_retry(_echo_llm):
            answer, degraded = await executor._synthesize(stage_ctx, context)

        assert degraded is None
        user_parts = [m.content for m in captured_messages if m.role == "user"]
        assert user_parts
        user_text = user_parts[-1]
        assert "SQL RECONCILIATION" not in user_text

    async def test_pipeline_synthesis_no_reconciliation_note_when_totals_differ(
        self, executor, context, mock_llm
    ):
        """Two SQL stages with DIFFERENT totals → reconciliation note NOT injected."""
        qr1 = _qr(["revenue"], [[1000.0]])  # sum = 1000
        qr2 = _qr(["revenue"], [[2000.0]])  # sum = 2000  (different)

        plan = _make_plan(_sql_stage("s1"), _sql_stage("s2"))
        stage_ctx = StageContext(plan=plan)
        stage_ctx.set_result("s1", StageResult(stage_id="s1", query_result=qr1))
        stage_ctx.set_result("s2", StageResult(stage_id="s2", query_result=qr2))

        captured_messages: list = []

        async def _echo_llm(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            return LLMResponse(content="ok", tool_calls=[], usage={})

        with patch_llm_call_with_retry(_echo_llm):
            answer, degraded = await executor._synthesize(stage_ctx, context)

        assert degraded is None
        user_parts = [m.content for m in captured_messages if m.role == "user"]
        assert user_parts
        user_text = user_parts[-1]
        assert "SQL RECONCILIATION" not in user_text
