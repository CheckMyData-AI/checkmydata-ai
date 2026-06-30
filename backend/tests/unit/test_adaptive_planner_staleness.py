"""V3 — vision §7 #7: AdaptivePlanner must prepend KNOWLEDGE FRESHNESS WARNINGS
to the planner's system prompt when ``staleness_warning`` is supplied."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.adaptive_planner import AdaptivePlanner
from app.llm.base import LLMResponse, ToolCall


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.complete = AsyncMock()
    return router


def _plan_tool_call() -> ToolCall:
    return ToolCall(
        id="call-1",
        name="create_execution_plan",
        arguments={
            "stages": [
                {
                    "stage_id": "s1",
                    "description": "Fetch data",
                    "tool": "query_database",
                }
            ],
            "complexity_reason": "test",
        },
    )


class TestPlannerStalenessInjection:
    @pytest.mark.asyncio
    async def test_llm_plan_prepends_freshness_when_provided(self, mock_router):
        mock_router.complete.return_value = LLMResponse(
            content="",
            tool_calls=[_plan_tool_call()],
        )

        planner = AdaptivePlanner(mock_router)
        await planner._llm_plan(
            "complex question",
            table_map="",
            db_type="postgres",
            preferred_provider=None,
            model=None,
            staleness_warning="Schema not refreshed in 14 days.",
        )

        messages = mock_router.complete.call_args.kwargs["messages"]
        system_msg = next(m for m in messages if m.role == "system")
        assert "KNOWLEDGE FRESHNESS WARNINGS:" in system_msg.content
        assert "14 days" in system_msg.content

    @pytest.mark.asyncio
    async def test_llm_plan_omits_freshness_when_none(self, mock_router):
        mock_router.complete.return_value = LLMResponse(
            content="",
            tool_calls=[_plan_tool_call()],
        )

        planner = AdaptivePlanner(mock_router)
        await planner._llm_plan(
            "complex question",
            table_map="",
            db_type="postgres",
            preferred_provider=None,
            model=None,
            staleness_warning=None,
        )

        messages = mock_router.complete.call_args.kwargs["messages"]
        system_msg = next(m for m in messages if m.role == "system")
        assert "KNOWLEDGE FRESHNESS WARNINGS" not in system_msg.content

    @pytest.mark.asyncio
    async def test_replan_prepends_freshness(self, mock_router):
        from app.agents.stage_context import PlanStage, StageResult

        mock_router.complete.return_value = LLMResponse(
            content="",
            tool_calls=[_plan_tool_call()],
        )

        planner = AdaptivePlanner(mock_router)
        await planner.replan(
            "complex question",
            completed_stages={
                "s0": StageResult(stage_id="s0", status="success", summary="done"),
            },
            failed_stage=PlanStage(stage_id="s1", description="X", tool="query_database"),
            error="DB error",
            staleness_warning="Stale (7 days).",
        )

        messages = mock_router.complete.call_args.kwargs["messages"]
        system_msg = next(m for m in messages if m.role == "system")
        assert "KNOWLEDGE FRESHNESS WARNINGS:" in system_msg.content
        assert "Stale" in system_msg.content


class TestReplanDanglingDepFeedback:
    """P2: replan must accept carried-over deps and feed validation errors back."""

    @pytest.mark.asyncio
    async def test_replan_accepts_carried_over_dependency(self, mock_router):
        from app.agents.stage_context import PlanStage, StageResult

        mock_router.complete.return_value = LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="c",
                    name="create_execution_plan",
                    arguments={
                        "stages": [
                            {"stage_id": "fetch", "description": "fetch", "tool": "query_database"},
                            {
                                "stage_id": "agg",
                                "description": "aggregate carried cohort",
                                "tool": "process_data",
                                "depends_on": ["cohort_signups"],
                            },
                        ],
                        "complexity_reason": "t",
                    },
                )
            ],
        )

        planner = AdaptivePlanner(mock_router)
        plan = await planner.replan(
            "cohort question",
            completed_stages={
                "cohort_signups": StageResult(
                    stage_id="cohort_signups", status="success", summary="ok"
                ),
            },
            failed_stage=PlanStage(
                stage_id="cohort_activity", description="X", tool="query_database"
            ),
            error="GROUP BY violation",
        )

        # A dependency on the carried-over successful stage must NOT fail validation.
        assert plan is not None
        assert plan.get_stage("agg").depends_on == ["cohort_signups"]

    @pytest.mark.asyncio
    async def test_replan_feeds_validation_error_into_retry(self, mock_router):
        from app.agents.stage_context import PlanStage, StageResult

        bad = ToolCall(
            id="c1",
            name="create_execution_plan",
            arguments={
                "stages": [
                    {
                        "stage_id": "x",
                        "description": "d",
                        "tool": "query_database",
                        "depends_on": ["ghost"],
                    }
                ],
                "complexity_reason": "t",
            },
        )
        good = ToolCall(
            id="c2",
            name="create_execution_plan",
            arguments={
                "stages": [{"stage_id": "s1", "description": "fetch", "tool": "query_database"}],
                "complexity_reason": "t",
            },
        )
        mock_router.complete.side_effect = [
            LLMResponse(content="", tool_calls=[bad]),
            LLMResponse(content="", tool_calls=[good]),
        ]

        planner = AdaptivePlanner(mock_router)
        plan = await planner.replan(
            "q",
            completed_stages={"s0": StageResult(stage_id="s0", status="success", summary="ok")},
            failed_stage=PlanStage(stage_id="s0b", description="X", tool="query_database"),
            error="e",
        )

        assert plan is not None
        # The second attempt's prompt must carry the prior validation failure.
        second_msgs = mock_router.complete.call_args_list[1].kwargs["messages"]
        user_msg = next(m for m in second_msgs if m.role == "user")
        assert "ghost" in user_msg.content or "unknown stage" in user_msg.content.lower()


class TestPlannerUsageSink:
    """R2 / C3 — planner must forward its UsageSink to every LLM call."""

    @pytest.mark.asyncio
    async def test_llm_plan_forwards_usage_sink(self, mock_router):
        from app.llm.usage_sink import AccumUsageSink

        mock_router.complete.return_value = LLMResponse(
            content="",
            tool_calls=[_plan_tool_call()],
        )

        accum = AccumUsageSink()
        planner = AdaptivePlanner(mock_router, usage_sink=accum)
        await planner._llm_plan(
            "complex question",
            table_map="",
            db_type="postgres",
            preferred_provider=None,
            model=None,
        )

        assert mock_router.complete.call_args.kwargs.get("usage_sink") is accum

    @pytest.mark.asyncio
    async def test_replan_forwards_usage_sink(self, mock_router):
        from app.agents.stage_context import PlanStage, StageResult
        from app.llm.usage_sink import AccumUsageSink

        mock_router.complete.return_value = LLMResponse(
            content="",
            tool_calls=[_plan_tool_call()],
        )

        accum = AccumUsageSink()
        planner = AdaptivePlanner(mock_router, usage_sink=accum)
        await planner.replan(
            "complex question",
            completed_stages={
                "s0": StageResult(stage_id="s0", status="success", summary="done"),
            },
            failed_stage=PlanStage(stage_id="s1", description="X", tool="query_database"),
            error="DB error",
        )

        assert mock_router.complete.call_args.kwargs.get("usage_sink") is accum

    @pytest.mark.asyncio
    async def test_default_usage_sink_is_none(self, mock_router):
        """Existing callers without usage_sink keep the kwarg=None default."""
        mock_router.complete.return_value = LLMResponse(
            content="",
            tool_calls=[_plan_tool_call()],
        )

        planner = AdaptivePlanner(mock_router)
        await planner._llm_plan(
            "complex question",
            table_map="",
            db_type="postgres",
            preferred_provider=None,
            model=None,
        )

        assert mock_router.complete.call_args.kwargs.get("usage_sink") is None
