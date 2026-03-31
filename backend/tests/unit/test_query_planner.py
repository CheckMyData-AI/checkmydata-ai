"""Unit tests for app.agents.query_planner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.query_planner import (
    QueryPlanner,
    _validate_plan_structure,
    detect_complexity,
    detect_complexity_adaptive,
)
from app.agents.stage_context import ExecutionPlan
from app.llm.base import LLMResponse, ToolCall

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_llm_router(response: LLMResponse | None = None, side_effect=None):
    router = MagicMock()
    if side_effect:
        router.complete = AsyncMock(side_effect=side_effect)
    else:
        router.complete = AsyncMock(return_value=response)
    return router


def _plan_tool_call(stages: list[dict], reason: str = "complex") -> ToolCall:
    return ToolCall(
        id="call_1",
        name="create_execution_plan",
        arguments={"stages": stages, "complexity_reason": reason},
    )


VALID_STAGES = [
    {
        "stage_id": "s1",
        "description": "Fetch revenue",
        "tool": "query_database",
        "depends_on": [],
    },
    {
        "stage_id": "s2",
        "description": "Summarize",
        "tool": "synthesize",
        "depends_on": ["s1"],
    },
]


# ==================================================================
# detect_complexity
# ==================================================================


class TestDetectComplexity:
    def test_simple_question(self):
        assert detect_complexity("What is the total revenue?") is False

    def test_two_indicators_keyword_and_questions(self):
        q = "Compare the breakdown of sales by region? And the cost breakdown?"
        assert detect_complexity(q) is True

    def test_long_question_plus_keyword(self):
        q = "x " * 200 + "compare revenue by region"
        assert len(q) > 300
        assert detect_complexity(q) is True

    def test_multiple_question_marks_plus_keyword(self):
        q = "What is the revenue? And what is the cost? Then show me the profit."
        assert detect_complexity(q) is True

    def test_borderline_single_indicator(self):
        q = "Show me the pivot of sales"
        assert detect_complexity(q) is False

    def test_commas_plus_conjunction(self):
        q = "Show a, b, c, d, and e from the table"
        assert detect_complexity(q) is False  # only comma+and = 1 indicator

    def test_commas_plus_conjunction_plus_keyword(self):
        q = "Compare a, b, c, d, and e from the table"
        assert detect_complexity(q) is True

    def test_plain_short_question(self):
        assert detect_complexity("simple question") is False


# ==================================================================
# detect_complexity_adaptive
# ==================================================================


class TestDetectComplexityAdaptive:
    @pytest.mark.asyncio
    async def test_score_zero_no_llm(self):
        router = _make_llm_router()
        result = await detect_complexity_adaptive("What is total revenue?", router)
        assert result is False
        router.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_score_two_plus_no_llm(self):
        q = "Compare the breakdown of sales by region? And the cost?"
        router = _make_llm_router()
        result = await detect_complexity_adaptive(q, router)
        assert result is True
        router.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_score_one_calls_llm_complex(self):
        q = "Show me the pivot of sales"
        resp = LLMResponse(content='{"complex": true, "reason": "multi-step"}')
        router = _make_llm_router(resp)
        result = await detect_complexity_adaptive(q, router)
        assert result is True
        router.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_score_one_calls_llm_simple(self):
        q = "Show me the pivot of sales"
        resp = LLMResponse(content='{"complex": false, "reason": "simple lookup"}')
        router = _make_llm_router(resp)
        result = await detect_complexity_adaptive(q, router)
        assert result is False

    @pytest.mark.asyncio
    async def test_llm_error_returns_false(self):
        q = "Show me the pivot of sales"
        router = _make_llm_router(side_effect=RuntimeError("LLM down"))
        result = await detect_complexity_adaptive(q, router)
        assert result is False


# ==================================================================
# _validate_plan_structure
# ==================================================================


class TestValidatePlanStructure:
    def test_empty_stages(self):
        errors = _validate_plan_structure([])
        assert errors == ["Plan has no stages"]

    def test_invalid_tool(self):
        stages = [{"stage_id": "s1", "tool": "hack_database", "depends_on": []}]
        errors = _validate_plan_structure(stages)
        assert any("invalid tool" in e for e in errors)

    def test_unknown_dependency(self):
        stages = [
            {"stage_id": "s1", "tool": "query_database", "depends_on": ["ghost"]},
        ]
        errors = _validate_plan_structure(stages)
        assert any("unknown stage 'ghost'" in e for e in errors)

    def test_no_data_retrieval_stage(self):
        stages = [
            {"stage_id": "s1", "tool": "synthesize", "depends_on": []},
        ]
        errors = _validate_plan_structure(stages)
        assert any("data-retrieval" in e for e in errors)

    def test_circular_dependency(self):
        stages = [
            {"stage_id": "s1", "tool": "query_database", "depends_on": ["s2"]},
            {"stage_id": "s2", "tool": "synthesize", "depends_on": ["s1"]},
        ]
        errors = _validate_plan_structure(stages)
        assert any("circular" in e.lower() for e in errors)

    def test_valid_plan(self):
        errors = _validate_plan_structure(VALID_STAGES)
        assert errors == []

    def test_search_codebase_counts_as_retrieval(self):
        stages = [
            {"stage_id": "s1", "tool": "search_codebase", "depends_on": []},
            {"stage_id": "s2", "tool": "synthesize", "depends_on": ["s1"]},
        ]
        assert _validate_plan_structure(stages) == []


# ==================================================================
# QueryPlanner.plan
# ==================================================================


class TestQueryPlannerPlan:
    @pytest.mark.asyncio
    async def test_success(self):
        tc = _plan_tool_call(VALID_STAGES)
        resp = LLMResponse(content="", tool_calls=[tc])
        router = _make_llm_router(resp)
        planner = QueryPlanner(router)

        plan = await planner.plan("complex question", table_map="users(id, name)")
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.stages) == 2
        assert plan.stages[0].tool == "query_database"

    @pytest.mark.asyncio
    async def test_no_tool_calls_retries_then_none(self):
        resp = LLMResponse(content="I cannot plan")
        router = _make_llm_router(resp)
        planner = QueryPlanner(router)

        plan = await planner.plan("complex question")
        assert plan is None
        assert router.complete.await_count == 2

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self):
        router = _make_llm_router(side_effect=RuntimeError("boom"))
        planner = QueryPlanner(router)

        plan = await planner.plan("complex question")
        assert plan is None

    @pytest.mark.asyncio
    async def test_invalid_plan_retries(self):
        bad_tc = _plan_tool_call([{"stage_id": "s1", "tool": "synthesize", "depends_on": []}])
        good_tc = _plan_tool_call(VALID_STAGES)
        bad_resp = LLMResponse(content="", tool_calls=[bad_tc])
        good_resp = LLMResponse(content="", tool_calls=[good_tc])

        router = MagicMock()
        router.complete = AsyncMock(side_effect=[bad_resp, good_resp])
        planner = QueryPlanner(router)

        plan = await planner.plan("complex question")
        assert isinstance(plan, ExecutionPlan)
        assert router.complete.await_count == 2

    @pytest.mark.asyncio
    async def test_wrong_tool_name_returns_none(self):
        tc = ToolCall(id="call_1", name="wrong_tool", arguments={})
        resp = LLMResponse(content="", tool_calls=[tc])
        router = _make_llm_router(resp)
        planner = QueryPlanner(router)

        plan = await planner.plan("complex question")
        assert plan is None
