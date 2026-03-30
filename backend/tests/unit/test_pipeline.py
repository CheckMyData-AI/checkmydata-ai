"""Tests for the multi-stage query pipeline.

Covers: QueryPlanner, StageExecutor, StageContext, StageValidator,
complexity detection, persistence, error recovery, and resume.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.query_planner import QueryPlanner, _validate_plan_structure, detect_complexity
from app.agents.stage_context import (
    ExecutionPlan,
    PlanStage,
    StageContext,
    StageResult,
    StageValidation,
)
from app.agents.stage_executor import StageExecutor
from app.agents.stage_validator import StageValidationOutcome, StageValidator
from app.connectors.base import ConnectionConfig, QueryResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-pipeline")
    t.end = AsyncMock()
    t.emit = AsyncMock()

    @asynccontextmanager
    async def fake_step(wf_id, step, detail="", **kwargs):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    return router


@pytest.fixture
def sample_plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-1",
        question="Find renewals and match to users",
        stages=[
            PlanStage(
                stage_id="find_renewals",
                description="Find renewal transactions",
                tool="query_database",
                validation=StageValidation(expected_columns=["product_id", "renewal_type"]),
                checkpoint=True,
            ),
            PlanStage(
                stage_id="match_users",
                description="Match renewals to users",
                tool="query_database",
                depends_on=["find_renewals"],
                validation=StageValidation(
                    cross_stage_checks=["row_count <= find_renewals.row_count * 2"],
                ),
            ),
            PlanStage(
                stage_id="synthesize",
                description="Build summary",
                tool="synthesize",
                depends_on=["find_renewals", "match_users"],
            ),
        ],
        complexity_reason="Multi-step query with cross-referencing",
    )


@pytest.fixture
def mock_context(mock_llm, mock_tracker) -> AgentContext:
    return AgentContext(
        project_id="proj-1",
        connection_config=ConnectionConfig(db_type="postgres"),
        user_question="test question",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-pipeline",
        extra={"session_id": "sess-1"},
    )


# ------------------------------------------------------------------
# Complexity Detection
# ------------------------------------------------------------------


class TestComplexityDetection:
    def test_simple_query(self):
        assert detect_complexity("Show me total revenue") is False

    def test_short_query_with_one_keyword(self):
        assert detect_complexity("Compare revenue by month") is False

    def test_complex_long_query_with_keywords(self):
        q = (
            "Find products renewed by subscription vs top-up, "
            "match to unique users, compute average check, "
            "product duration, and create a summary table. "
            "Comment on findings." * 3
        )
        assert detect_complexity(q) is True

    def test_multiple_questions(self):
        q = "What are the top products? How do they compare to last month? What trends do you see?"
        assert detect_complexity(q) is True

    def test_step_based_query(self):
        q = (
            "Step 1: find all users who signed up last month, "
            "including their emails, names, and regions. "
            "Step 2: match them to orders, compute totals, "
            "and calculate average order value. "
            "Then create a summary table with breakdown by region, "
            "and also compare to the previous month's performance."
        )
        assert detect_complexity(q) is True


# ------------------------------------------------------------------
# Plan Validation
# ------------------------------------------------------------------


class TestPlanValidation:
    def test_valid_plan(self):
        stages = [
            {"stage_id": "a", "tool": "query_database"},
            {"stage_id": "b", "tool": "synthesize", "depends_on": ["a"]},
        ]
        assert _validate_plan_structure(stages) == []

    def test_empty_plan(self):
        errors = _validate_plan_structure([])
        assert "no stages" in errors[0].lower()

    def test_invalid_tool(self):
        stages = [{"stage_id": "a", "tool": "magic_tool"}]
        errors = _validate_plan_structure(stages)
        assert any("invalid tool" in e.lower() for e in errors)

    def test_missing_dependency(self):
        stages = [
            {"stage_id": "a", "tool": "query_database", "depends_on": ["nonexistent"]},
        ]
        errors = _validate_plan_structure(stages)
        assert any("unknown stage" in e.lower() for e in errors)

    def test_circular_dependency(self):
        stages = [
            {"stage_id": "a", "tool": "query_database", "depends_on": ["b"]},
            {"stage_id": "b", "tool": "query_database", "depends_on": ["a"]},
        ]
        errors = _validate_plan_structure(stages)
        assert any("circular" in e.lower() for e in errors)

    def test_no_data_retrieval(self):
        stages = [{"stage_id": "a", "tool": "synthesize"}]
        errors = _validate_plan_structure(stages)
        assert any("data-retrieval" in e.lower() for e in errors)


# ------------------------------------------------------------------
# StageContext
# ------------------------------------------------------------------


class TestStageContext:
    def test_set_and_get_result(self, sample_plan):
        ctx = StageContext(plan=sample_plan)
        sr = StageResult(stage_id="find_renewals", status="success", summary="found 100 rows")
        ctx.set_result("find_renewals", sr)
        assert ctx.get_result("find_renewals") is sr
        assert ctx.get_result("nonexistent") is None

    def test_build_context_for_stage(self, sample_plan):
        ctx = StageContext(plan=sample_plan)
        qr = QueryResult(columns=["product_id", "renewal_type"], rows=[[1, "sub"]], row_count=1)
        ctx.set_result(
            "find_renewals",
            StageResult(
                stage_id="find_renewals",
                status="success",
                query="SELECT ...",
                query_result=qr,
                summary="ok",
            ),
        )
        text = ctx.build_context_for_stage("match_users")
        assert "find_renewals" in text
        assert "product_id" in text
        assert "[DEPENDENCY]" in text

    def test_persistence_roundtrip(self, sample_plan):
        ctx = StageContext(plan=sample_plan, pipeline_run_id="run-1")
        qr = QueryResult(columns=["a", "b"], rows=[[1, 2], [3, 4]], row_count=2)
        ctx.set_result(
            "find_renewals",
            StageResult(
                stage_id="find_renewals",
                status="success",
                query="SELECT 1",
                query_result=qr,
            ),
        )
        ctx.user_feedback = [{"stage_id": "find_renewals", "feedback_text": "looks good"}]

        d = ctx.to_persistence_dict()
        restored = StageContext.from_persistence(
            plan=sample_plan,
            stage_results_raw=d,
            user_feedback=ctx.user_feedback,
            current_stage_idx=1,
            pipeline_run_id="run-1",
        )

        assert restored.get_result("find_renewals") is not None
        assert restored.get_result("find_renewals").status == "success"
        assert restored.user_feedback[0]["feedback_text"] == "looks good"
        assert restored.current_stage_idx == 1

    def test_empty_context_for_first_stage(self, sample_plan):
        ctx = StageContext(plan=sample_plan)
        text = ctx.build_context_for_stage("find_renewals")
        assert text == ""


# ------------------------------------------------------------------
# StageValidator
# ------------------------------------------------------------------


class TestStageValidator:
    def test_success_with_expected_columns(self, sample_plan):
        v = StageValidator()
        qr = QueryResult(
            columns=["product_id", "renewal_type", "amount"],
            rows=[[1, "sub", 10]],
            row_count=1,
        )
        sr = StageResult(stage_id="find_renewals", status="success", query_result=qr)
        ctx = StageContext(plan=sample_plan)
        outcome = v.validate(sample_plan.stages[0], sr, ctx)
        assert outcome.passed is True

    def test_fail_missing_columns(self, sample_plan):
        v = StageValidator()
        qr = QueryResult(columns=["amount"], rows=[[10]], row_count=1)
        sr = StageResult(stage_id="find_renewals", status="success", query_result=qr)
        ctx = StageContext(plan=sample_plan)
        outcome = v.validate(sample_plan.stages[0], sr, ctx)
        assert outcome.passed is False
        assert any("missing" in e.lower() for e in outcome.errors)

    def test_warn_row_count_bounds(self):
        stage = PlanStage(
            stage_id="test",
            description="test",
            tool="query_database",
            validation=StageValidation(min_rows=10, max_rows=100),
        )
        v = StageValidator()
        qr = QueryResult(columns=["a"], rows=[], row_count=0)
        sr = StageResult(stage_id="test", status="success", query_result=qr)
        ctx = StageContext(plan=ExecutionPlan(plan_id="p", question="q", stages=[stage]))
        outcome = v.validate(stage, sr, ctx)
        assert outcome.passed is True  # bounds are warnings, not failures
        assert len(outcome.warnings) >= 1

    def test_error_status_fails(self, sample_plan):
        v = StageValidator()
        sr = StageResult(stage_id="find_renewals", status="error", error="SQL syntax error")
        ctx = StageContext(plan=sample_plan)
        outcome = v.validate(sample_plan.stages[0], sr, ctx)
        assert outcome.passed is False

    def test_cross_stage_check(self, sample_plan):
        v = StageValidator()
        ctx = StageContext(plan=sample_plan)
        qr1 = QueryResult(columns=["a"], rows=[[1]], row_count=10)
        ctx.set_result(
            "find_renewals",
            StageResult(
                stage_id="find_renewals",
                status="success",
                query_result=qr1,
            ),
        )
        qr2 = QueryResult(columns=["b"], rows=[[1]], row_count=100)
        sr2 = StageResult(stage_id="match_users", status="success", query_result=qr2)
        outcome = v.validate(sample_plan.stages[1], sr2, ctx)
        assert any("cross-stage" in w.lower() for w in outcome.warnings)


# ------------------------------------------------------------------
# QueryPlanner
# ------------------------------------------------------------------


class TestQueryPlanner:
    @pytest.mark.asyncio
    async def test_successful_planning(self, mock_llm):
        plan_args = {
            "stages": [
                {"stage_id": "s1", "description": "Get data", "tool": "query_database"},
                {
                    "stage_id": "s2",
                    "description": "Summarize",
                    "tool": "synthesize",
                    "depends_on": ["s1"],
                },
            ],
            "complexity_reason": "Multi-step",
        }
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[ToolCall(id="tc1", name="create_execution_plan", arguments=plan_args)],
            )
        )
        planner = QueryPlanner(mock_llm)
        plan = await planner.plan("complex question", table_map="users: id, name")
        assert plan is not None
        assert len(plan.stages) == 2
        assert plan.stages[0].stage_id == "s1"

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_plan(self, mock_llm):
        bad_args = {"stages": [], "complexity_reason": "empty"}
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[ToolCall(id="tc1", name="create_execution_plan", arguments=bad_args)],
            )
        )
        planner = QueryPlanner(mock_llm)
        result = await planner.plan("query")
        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_on_llm_exception(self, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))
        planner = QueryPlanner(mock_llm)
        result = await planner.plan("query")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_tool_call_returns_none(self, mock_llm):
        mock_llm.complete = AsyncMock(return_value=LLMResponse(content="I can't plan this"))
        planner = QueryPlanner(mock_llm)
        result = await planner.plan("query")
        assert result is None


# ------------------------------------------------------------------
# StageExecutor
# ------------------------------------------------------------------


def _make_sql_agent_result(
    query: str = "SELECT 1",
    columns: list[str] | None = None,
    row_count: int = 5,
):
    """Helper to create a mock SQL agent result."""
    cols = columns or ["id", "name"]
    rows = [[i, f"item_{i}"] for i in range(row_count)]
    from app.agents.sql_agent import SQLAgentResult

    return SQLAgentResult(
        status="success",
        query=query,
        results=QueryResult(columns=cols, rows=rows, row_count=row_count),
    )


class TestStageExecutor:
    @pytest.fixture
    def mock_sql_agent(self):
        agent = MagicMock()
        agent.run = AsyncMock(
            return_value=_make_sql_agent_result(
                "SELECT * FROM renewals",
                columns=["product_id", "renewal_type"],
                row_count=10,
            )
        )
        return agent

    @pytest.fixture
    def mock_knowledge_agent(self):
        from app.agents.knowledge_agent import KnowledgeResult

        agent = MagicMock()
        agent.run = AsyncMock(
            return_value=KnowledgeResult(
                status="success",
                answer="Knowledge answer",
            )
        )
        return agent

    @pytest.fixture
    def executor(self, mock_sql_agent, mock_knowledge_agent, mock_llm, mock_tracker):
        return StageExecutor(
            sql_agent=mock_sql_agent,
            knowledge_agent=mock_knowledge_agent,
            llm_router=mock_llm,
            tracker=mock_tracker,
        )

    @pytest.mark.asyncio
    async def test_execute_stops_at_checkpoint(self, executor, mock_context, sample_plan):
        result = await executor.execute(sample_plan, mock_context)
        assert result.status == "checkpoint"
        assert result.checkpoint_stage is not None
        assert result.checkpoint_stage.stage_id == "find_renewals"
        assert result.stage_ctx.get_result("find_renewals") is not None

    @pytest.mark.asyncio
    async def test_execute_full_pipeline_no_checkpoint(self, executor, mock_context, mock_llm):
        plan = ExecutionPlan(
            plan_id="p-2",
            question="Simple multi-step",
            stages=[
                PlanStage(
                    stage_id="get_data",
                    description="Get data",
                    tool="query_database",
                    checkpoint=False,
                ),
                PlanStage(
                    stage_id="synth",
                    description="Summarize",
                    tool="synthesize",
                    depends_on=["get_data"],
                ),
            ],
        )
        mock_llm.complete = AsyncMock(return_value=LLMResponse(content="Final answer"))
        result = await executor.execute(plan, mock_context)
        assert result.status == "completed"
        assert "Final answer" in result.final_answer

    @pytest.mark.asyncio
    async def test_resume_from_stage(self, executor, mock_context, sample_plan, mock_llm):
        qr = QueryResult(columns=["product_id", "renewal_type"], rows=[[1, "sub"]], row_count=1)
        stage_ctx = StageContext(plan=sample_plan, pipeline_run_id="run-1")
        stage_ctx.set_result(
            "find_renewals",
            StageResult(
                stage_id="find_renewals",
                status="success",
                query="SELECT 1",
                query_result=qr,
            ),
        )
        mock_llm.complete = AsyncMock(return_value=LLMResponse(content="Done"))

        result = await executor.execute(
            sample_plan, mock_context, resume_from=1, stage_ctx=stage_ctx
        )
        assert result.stage_ctx.get_result("find_renewals") is not None
        assert result.stage_ctx.get_result("match_users") is not None

    @pytest.mark.asyncio
    async def test_stage_failure_returns_failed(
        self,
        mock_knowledge_agent,
        mock_llm,
        mock_tracker,
        mock_context,
    ):
        from app.agents.errors import AgentFatalError

        fail_agent = MagicMock()
        fail_agent.run = AsyncMock(side_effect=AgentFatalError("DB gone"))
        executor = StageExecutor(
            sql_agent=fail_agent,
            knowledge_agent=mock_knowledge_agent,
            llm_router=mock_llm,
            tracker=mock_tracker,
        )
        plan = ExecutionPlan(
            plan_id="p-fail",
            question="Failing query",
            stages=[PlanStage(stage_id="fail", description="Fail", tool="query_database")],
        )

        with patch("app.agents.stage_executor.settings") as mock_settings:
            mock_settings.max_stage_retries = 0
            result = await executor.execute(plan, mock_context)

        assert result.status == "stage_failed"

    @pytest.mark.asyncio
    async def test_validation_failure_triggers_retry(
        self,
        mock_sql_agent,
        mock_knowledge_agent,
        mock_llm,
        mock_tracker,
        mock_context,
    ):
        call_count = 0
        good_qr = QueryResult(columns=["expected_col"], rows=[[1]], row_count=1)
        bad_qr = QueryResult(columns=["wrong_col"], rows=[[1]], row_count=1)

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            from app.agents.sql_agent import SQLAgentResult

            if call_count <= 1:
                return SQLAgentResult(status="success", query="SELECT 1", results=bad_qr)
            return SQLAgentResult(status="success", query="SELECT 1", results=good_qr)

        mock_sql_agent.run = AsyncMock(side_effect=side_effect)
        executor = StageExecutor(
            sql_agent=mock_sql_agent,
            knowledge_agent=mock_knowledge_agent,
            llm_router=mock_llm,
            tracker=mock_tracker,
        )
        plan = ExecutionPlan(
            plan_id="p-retry",
            question="Retry test",
            stages=[
                PlanStage(
                    stage_id="retry_stage",
                    description="Retryable",
                    tool="query_database",
                    validation=StageValidation(expected_columns=["expected_col"]),
                ),
                PlanStage(
                    stage_id="done",
                    description="Done",
                    tool="synthesize",
                    depends_on=["retry_stage"],
                ),
            ],
        )
        mock_llm.complete = AsyncMock(return_value=LLMResponse(content="Done"))
        result = await executor.execute(plan, mock_context)
        assert result.status == "completed"
        assert call_count >= 2


# ------------------------------------------------------------------
# ExecutionPlan serialization
# ------------------------------------------------------------------


class TestExecutionPlanSerialization:
    def test_roundtrip(self, sample_plan):
        j = sample_plan.to_json()
        restored = ExecutionPlan.from_json(j)
        assert restored.plan_id == sample_plan.plan_id
        assert len(restored.stages) == len(sample_plan.stages)
        assert restored.stages[0].stage_id == "find_renewals"
        assert restored.stages[0].validation.expected_columns == ["product_id", "renewal_type"]
        assert restored.stages[1].depends_on == ["find_renewals"]
        assert restored.stages[0].checkpoint is True

    def test_to_dict_and_back(self, sample_plan):
        d = sample_plan.to_dict()
        assert isinstance(d, dict)
        assert d["plan_id"] == "plan-1"
        restored = ExecutionPlan.from_dict(d)
        assert restored.complexity_reason == sample_plan.complexity_reason


# ------------------------------------------------------------------
# StageResult serialization
# ------------------------------------------------------------------


class TestStageResultSerialization:
    def test_summary_dict_roundtrip(self):
        qr = QueryResult(columns=["a", "b"], rows=[[1, 2], [3, 4]], row_count=2)
        sr = StageResult(
            stage_id="test",
            status="success",
            query="SELECT a, b FROM t",
            query_result=qr,
            summary="found 2 rows",
        )
        d = sr.to_summary_dict()
        assert d["stage_id"] == "test"
        assert d["columns"] == ["a", "b"]
        assert d["row_count"] == 2

        restored = StageResult.from_summary_dict(d)
        assert restored.stage_id == "test"
        assert restored.query_result is not None
        assert restored.query_result.columns == ["a", "b"]

    def test_error_result_serialization(self):
        sr = StageResult(stage_id="fail", status="error", error="bad query")
        d = sr.to_summary_dict()
        assert d["error"] == "bad query"
        restored = StageResult.from_summary_dict(d)
        assert restored.status == "error"


# ------------------------------------------------------------------
# StageValidationOutcome
# ------------------------------------------------------------------


class TestStageValidationOutcome:
    def test_fail_sets_passed_false(self):
        o = StageValidationOutcome()
        assert o.passed is True
        o.fail("bad")
        assert o.passed is False
        assert "bad" in o.error_summary

    def test_warn_does_not_fail(self):
        o = StageValidationOutcome()
        o.warn("minor issue")
        assert o.passed is True
        assert len(o.warnings) == 1

    def test_to_dict(self):
        o = StageValidationOutcome()
        o.fail("err1")
        o.warn("warn1")
        d = o.to_dict()
        assert d["passed"] is False
        assert "err1" in d["errors"]
        assert "warn1" in d["warnings"]
