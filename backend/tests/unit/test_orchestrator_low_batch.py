"""Regression tests for T13 low-batch fixes: ORCH-A05, V02, PR03, R03, R04.

Each test corresponds to one audit finding:

- A05+R04: planner-fallback uses ``dataclasses.replace`` and preserves all extra
  fields including the original ``complexity``.
- V02 (budget): three per-stage retry loops share one counter → total executions
  bounded by ``max_retries + 1`` not ``~7×``.
- V02 (deadline): a past-deadline blocks retries without another execute call.
- R03: ``_heuristic_queries`` ORs in a count that raises ``estimated_queries``
  when the LLM under-estimates multi-step questions.
- PR03: analysis-stage system prompt contains language-mirroring instruction.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base import AgentContext
from app.agents.router import _heuristic_queries, _parse_route_response
from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
from app.agents.stage_executor import StageExecutor, _RetryBudget
from app.core.workflow_tracker import WorkflowTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_tracker() -> WorkflowTracker:
    t = MagicMock(spec=WorkflowTracker)
    t.emit = AsyncMock()
    t.step = MagicMock()
    t.step.return_value.__aenter__ = AsyncMock(return_value=None)
    t.step.return_value.__aexit__ = AsyncMock(return_value=False)
    return t


def _stub_context(**extra_kwargs: Any) -> AgentContext:
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="revenue by country and by month then compare vs last year",
        chat_history=[],
        llm_router=MagicMock(),
        tracker=_stub_tracker(),
        workflow_id="wf-1",
        **extra_kwargs,
    )


def _make_stage(stage_id: str = "s1", max_retries: int = 2) -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description="test stage",
        tool="query_database",
        max_retries=max_retries,
    )


def _make_executor() -> StageExecutor:
    return StageExecutor(
        sql_agent=MagicMock(),
        knowledge_agent=MagicMock(),
        llm_router=MagicMock(),
        tracker=_stub_tracker(),
    )


# ---------------------------------------------------------------------------
# ORCH-A05 + R04: fallback preserves all extra fields via dataclasses.replace
# ---------------------------------------------------------------------------


class TestPlannerFallbackPreservesExtra:
    """A05: replace() used → no field silently dropped.
    R04: original complexity key preserved across fallback re-entry.
    """

    @pytest.mark.asyncio
    async def test_planner_fallback_preserves_extra(self) -> None:
        """Force a planner failure and assert the re-entered context keeps
        all extra fields including the original complexity and custom keys.
        """
        from app.agents.orchestrator import OrchestratorAgent

        # Build a minimal orchestrator double.
        llm_mock = MagicMock()
        tracker = _stub_tracker()
        orch = OrchestratorAgent.__new__(OrchestratorAgent)
        orch._llm = llm_mock
        orch._tracker = tracker
        orch._results_cache: dict = {}

        # Record what context gets passed to the recursive run() call.
        captured: list[AgentContext] = []

        async def _fake_run(context: AgentContext, **_kw: Any):  # type: ignore[return]
            if context.extra.get("_skip_complexity"):
                captured.append(context)
                # Return a minimal AgentResponse to stop recursion.
                from app.agents.orchestrator import AgentResponse

                return AgentResponse(
                    answer="ok",
                    response_type="direct",
                    token_usage={},
                )
            # First call: run _fallback_to_unified directly
            return await orch._fallback_to_unified(
                context,
                wf_id=context.workflow_id,
                reason="Testing fallback",
            )

        orch.run = _fake_run  # type: ignore[method-assign]

        ctx = _stub_context(
            extra={
                "complexity": "complex",
                "session_id": "s1",
                "custom_key": "keep",
            }
        )

        await orch.run(ctx)

        assert len(captured) == 1
        re_entered = captured[0]
        # A05: no field dropped — all structural fields preserved
        assert re_entered.project_id == ctx.project_id
        assert re_entered.user_question == ctx.user_question
        assert re_entered.workflow_id == ctx.workflow_id
        # R04: original complexity preserved
        assert re_entered.extra.get("complexity") == "complex"
        # A05: custom extra key preserved
        assert re_entered.extra.get("custom_key") == "keep"
        # fallback flag set
        assert re_entered.extra.get("_skip_complexity") is True


# ---------------------------------------------------------------------------
# ORCH-V02: shared retry budget bounding total executions
# ---------------------------------------------------------------------------


class TestStageRetryBudgetIsShared:
    """V02: total sub-agent invocations bounded by shared budget."""

    @pytest.mark.asyncio
    async def test_stage_retry_budget_is_shared(self) -> None:
        """With max_retries=2 the combined execute+validation+data-gate
        invocation count must be <= max_retries + 1 = 3, not ~7.
        """
        executor = _make_executor()
        stage = _make_stage(max_retries=2)
        plan = ExecutionPlan(plan_id="p1", question="q", stages=[stage])
        stage_ctx = StageContext(plan=plan, pipeline_run_id="r1")
        ctx = _stub_context()

        call_count = 0

        async def _failing_execute(s, sc, c, *, error_context=None):
            nonlocal call_count
            call_count += 1
            return StageResult(
                stage_id=s.stage_id,
                status="error",
                error="always fails",
                error_category="transient",
            )

        executor._execute_stage = _failing_execute  # type: ignore[method-assign]

        budget = _RetryBudget(max_retries=2, deadline=None)
        await executor._execute_with_retries(stage, stage_ctx, ctx, budget=budget)
        # budget consumed: execute_with_retries drew from it.
        # Now simulate validation retry drawing from the same budget.
        from app.agents.stage_validator import StageValidationOutcome

        validation = StageValidationOutcome(passed=False, errors=["bad"])
        await executor._retry_failed_validation(stage, stage_ctx, ctx, validation, budget=budget)

        # Total calls must not exceed max_retries + 1
        assert call_count <= 3, (
            f"Expected ≤3 total executions with shared budget, got {call_count}"
        )


class TestDeadlineCheckedInsideRetryLoop:
    """V02: a past deadline aborts the retry loop without another execute call."""

    @pytest.mark.asyncio
    async def test_deadline_checked_inside_retry_loop(self) -> None:
        executor = _make_executor()
        stage = _make_stage(max_retries=2)
        plan = ExecutionPlan(plan_id="p1", question="q", stages=[stage])
        stage_ctx = StageContext(plan=plan, pipeline_run_id="r1")
        ctx = _stub_context()

        call_count = 0

        async def _execute_stub(s, sc, c, *, error_context=None):
            nonlocal call_count
            call_count += 1
            return StageResult(
                stage_id=s.stage_id,
                status="error",
                error="fail",
                error_category="transient",
            )

        executor._execute_stage = _execute_stub  # type: ignore[method-assign]

        # Deadline in the past — the budget should block immediately.
        past_deadline = time.monotonic() - 1.0
        budget = _RetryBudget(max_retries=2, deadline=past_deadline)

        from app.agents.stage_validator import StageValidationOutcome

        validation = StageValidationOutcome(passed=False, errors=["bad"])
        result = await executor._retry_failed_validation(
            stage, stage_ctx, ctx, validation, budget=budget
        )

        assert result is None
        assert call_count == 0, (
            f"Expected 0 execute calls past deadline, got {call_count}"
        )


# ---------------------------------------------------------------------------
# ORCH-R03: heuristic OR-in for estimated_queries
# ---------------------------------------------------------------------------


class TestRouterHeuristicOrsIn:
    """R03: multi-step question → estimated_queries raised by heuristic."""

    def test_heuristic_counts_conjunctions(self) -> None:
        q = "revenue by country and by month then compare vs last year"
        count = _heuristic_queries(q)
        # "by " appears twice, " and ", " then ", "compare", " vs " → ≥ 3
        assert count >= 3

    def test_heuristic_cap(self) -> None:
        q = "a and b then c compare d by e vs f over time each g"
        assert _heuristic_queries(q) <= 5

    def test_parse_route_response_low_estimate(self) -> None:
        """The parser itself is pure — it does NOT apply the heuristic."""
        raw = (
            '{"route":"query","complexity":"simple","approach":"","estimated_queries":1,'
            '"needs_multiple_data_sources":false}'
        )
        result = _parse_route_response(raw, has_connection=True, has_knowledge_base=False,
                                       has_mcp_sources=False, has_repo=False)
        # The parser returns the raw LLM value; heuristic is applied in route_request.
        assert result.estimated_queries == 1

    @pytest.mark.asyncio
    async def test_route_request_heuristic_raises_estimate(self) -> None:
        """route_request applies the heuristic after parse → calibrated value."""
        from app.agents.router import route_request
        from app.llm.base import LLMResponse

        question = "revenue by country and by month then compare vs last year"
        llm_mock = AsyncMock()
        llm_mock.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"route":"query","complexity":"simple","approach":"","'
                        'estimated_queries":1,"needs_multiple_data_sources":false}',
                tool_calls=[],
                usage={},
                model="test",
                provider="test",
            )
        )
        result = await route_request(
            question,
            llm_mock,
            has_connection=True,
        )
        # Heuristic should raise above the LLM's 1
        assert result.estimated_queries >= 3


# ---------------------------------------------------------------------------
# PR03: analysis-stage system prompt contains language-mirroring instruction
# ---------------------------------------------------------------------------


class TestAnalysisStageLanguageCaveat:
    """PR03: the analysis-stage system prompt must include language-mirroring."""

    def test_analysis_stage_prompt_has_language_instruction(self) -> None:
        import inspect

        from app.agents.stage_executor import StageExecutor

        src = inspect.getsource(StageExecutor._run_analysis_stage)
        assert "language" in src.lower(), (
            "_run_analysis_stage system prompt missing language-mirroring caveat"
        )
        assert "user" in src.lower()
