"""Unit tests for StageExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext, AgentResult
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

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.emit = AsyncMock()
    return t


@pytest.fixture
def mock_sql_agent():
    agent = AsyncMock()
    agent.run = AsyncMock()
    return agent


@pytest.fixture
def mock_knowledge_agent():
    agent = AsyncMock()
    agent.run = AsyncMock()
    return agent


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
def executor(mock_sql_agent, mock_knowledge_agent, mock_llm, mock_tracker, mock_validator):
    return StageExecutor(
        sql_agent=mock_sql_agent,
        knowledge_agent=mock_knowledge_agent,
        llm_router=mock_llm,
        tracker=mock_tracker,
        validator=mock_validator,
    )


@pytest.fixture
def context(mock_llm, mock_tracker) -> AgentContext:
    return AgentContext(
        project_id="proj-1",
        connection_config=ConnectionConfig(db_type="postgres"),
        user_question="test question",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-test",
    )


def _make_plan(*stages: PlanStage) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-test",
        question="Test question",
        stages=list(stages),
    )


def _sql_stage(stage_id: str = "s1", checkpoint: bool = False) -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description=f"SQL stage {stage_id}",
        tool="query_database",
        checkpoint=checkpoint,
    )


def _kb_stage(stage_id: str = "kb1") -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description=f"KB stage {stage_id}",
        tool="search_codebase",
    )


def _analysis_stage(stage_id: str = "a1") -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description=f"Analysis stage {stage_id}",
        tool="analyze_results",
    )


def _synth_stage(stage_id: str = "syn") -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description="Final synthesis",
        tool="synthesize",
    )


# ------------------------------------------------------------------
# execute() — full pipeline
# ------------------------------------------------------------------


class TestExecute:
    @pytest.mark.asyncio
    async def test_completes_all_stages(self, executor, context, mock_sql_agent, mock_llm):
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        sql_result = MagicMock(spec=AgentResult)
        sql_result.status = "success"
        sql_result.results = qr
        sql_result.query = "SELECT 1"
        sql_result.token_usage = {}
        mock_sql_agent.run.return_value = sql_result

        mock_llm.complete.return_value = LLMResponse(content="Final answer")

        plan = _make_plan(_sql_stage("s1"), _sql_stage("s2"))
        result = await executor.execute(plan, context)

        assert result.status == "completed"
        assert result.final_answer == "Final answer"
        assert mock_sql_agent.run.call_count == 2

    @pytest.mark.asyncio
    async def test_stops_on_stage_error(self, executor, context, mock_sql_agent):
        sql_result = MagicMock(spec=AgentResult)
        sql_result.status = "error"
        sql_result.error = "DB connection failed"
        sql_result.token_usage = {}
        mock_sql_agent.run.return_value = sql_result

        plan = _make_plan(_sql_stage("s1"), _sql_stage("s2"))

        with patch("app.agents.stage_executor.settings") as mock_settings:
            mock_settings.max_stage_retries = 0
            result = await executor.execute(plan, context)

        assert result.status == "stage_failed"
        assert result.failed_stage is not None
        assert result.failed_stage.stage_id == "s1"

    @pytest.mark.asyncio
    async def test_stops_at_checkpoint(self, executor, context, mock_sql_agent, mock_llm):
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        sql_result = MagicMock(spec=AgentResult)
        sql_result.status = "success"
        sql_result.results = qr
        sql_result.query = "SELECT 1"
        sql_result.token_usage = {}
        mock_sql_agent.run.return_value = sql_result

        plan = _make_plan(_sql_stage("s1", checkpoint=True), _sql_stage("s2"))
        result = await executor.execute(plan, context)

        assert result.status == "checkpoint"
        assert result.checkpoint_stage.stage_id == "s1"
        assert mock_sql_agent.run.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_error_then_succeeds(
        self, executor, context, mock_sql_agent, mock_llm
    ):
        error_result = MagicMock(spec=AgentResult)
        error_result.status = "error"
        error_result.error = "transient failure"
        error_result.token_usage = {}

        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        success_result = MagicMock(spec=AgentResult)
        success_result.status = "success"
        success_result.results = qr
        success_result.query = "SELECT 1"
        success_result.token_usage = {}

        mock_sql_agent.run.side_effect = [error_result, success_result]
        mock_llm.complete.return_value = LLMResponse(content="done")

        plan = _make_plan(_sql_stage("s1"))

        with patch("app.agents.stage_executor.settings") as mock_settings:
            mock_settings.max_stage_retries = 1
            result = await executor.execute(plan, context)

        assert result.status == "completed"
        assert mock_sql_agent.run.call_count == 2


# ------------------------------------------------------------------
# _execute_stage() — dispatch
# ------------------------------------------------------------------


class TestExecuteStage:
    @pytest.mark.asyncio
    async def test_dispatches_query_database(self, executor, context, mock_sql_agent):
        qr = QueryResult(columns=["x"], rows=[[42]], row_count=1)
        sql_result = MagicMock(spec=AgentResult)
        sql_result.status = "success"
        sql_result.results = qr
        sql_result.query = "SELECT 42"
        sql_result.token_usage = {}
        mock_sql_agent.run.return_value = sql_result

        stage = _sql_stage("s1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        result = await executor._execute_stage(stage, stage_ctx, context)

        assert result.status == "success"
        assert result.query == "SELECT 42"
        mock_sql_agent.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatches_search_codebase(self, executor, context, mock_knowledge_agent):
        kb_result = MagicMock()
        kb_result.answer = "Found relevant docs"
        kb_result.token_usage = {}
        mock_knowledge_agent.run.return_value = kb_result

        stage = _kb_stage("kb1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        result = await executor._execute_stage(stage, stage_ctx, context)

        assert result.status == "success"
        assert "Found relevant docs" in result.summary
        mock_knowledge_agent.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_tool(self, executor, context):
        stage = PlanStage(
            stage_id="bad",
            description="bad stage",
            tool="nonexistent_tool",
        )
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        result = await executor._execute_stage(stage, stage_ctx, context)

        assert result.status == "error"
        assert "Unknown tool" in result.error

    @pytest.mark.asyncio
    async def test_catches_exceptions(self, executor, context, mock_sql_agent):
        mock_sql_agent.run.side_effect = RuntimeError("unexpected boom")

        stage = _sql_stage("s1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        result = await executor._execute_stage(stage, stage_ctx, context)

        assert result.status == "error"
        assert "unexpected boom" in result.error

    @pytest.mark.asyncio
    async def test_dispatches_analyze_results(self, executor, context, mock_llm):
        mock_llm.complete.return_value = LLMResponse(content="Analysis complete", usage={})

        stage = _analysis_stage("a1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        result = await executor._execute_stage(stage, stage_ctx, context)

        assert result.status == "success"
        assert result.summary == "Analysis complete"

    @pytest.mark.asyncio
    async def test_dispatches_synthesize(self, executor, context, mock_llm):
        mock_llm.complete.return_value = LLMResponse(content="Synthesized answer")

        stage = _synth_stage("syn")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        result = await executor._execute_stage(stage, stage_ctx, context)

        assert result.status == "success"
        assert "Synthesized answer" in result.summary


# ------------------------------------------------------------------
# _build_stage_question()
# ------------------------------------------------------------------


class TestBuildStageQuestion:
    def test_includes_description(self, executor):
        stage = _sql_stage("s1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        question = executor._build_stage_question(stage, stage_ctx)

        assert "SQL stage s1" in question

    def test_includes_previous_context(self, executor):
        s1 = _sql_stage("s1")
        s2 = PlanStage(
            stage_id="s2",
            description="Second stage",
            tool="query_database",
            depends_on=["s1"],
        )
        plan = _make_plan(s1, s2)
        stage_ctx = StageContext(plan=plan)
        stage_ctx.set_result(
            "s1",
            StageResult(stage_id="s1", status="success", summary="Found 10 rows"),
        )

        question = executor._build_stage_question(s2, stage_ctx)

        assert "Found 10 rows" in question
        assert "Second stage" in question

    def test_includes_error_context(self, executor):
        stage = _sql_stage("s1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        question = executor._build_stage_question(
            stage, stage_ctx, error_context="Missing columns: revenue"
        )

        assert "Missing columns: revenue" in question
        assert "previous attempt failed validation" in question

    def test_includes_input_context(self, executor):
        stage = PlanStage(
            stage_id="s1",
            description="Test",
            tool="query_database",
            input_context="Use the orders table",
        )
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        question = executor._build_stage_question(stage, stage_ctx)

        assert "Use the orders table" in question


# ------------------------------------------------------------------
# _summarize_query_result()
# ------------------------------------------------------------------


class TestSummarizeQueryResult:
    def test_no_results(self):
        summary = StageExecutor._summarize_query_result("SELECT 1", None)
        assert summary == "No results."

    def test_with_data(self):
        qr = QueryResult(
            columns=["name", "total"],
            rows=[["Alice", 100], ["Bob", 200]],
            row_count=2,
        )
        summary = StageExecutor._summarize_query_result("SELECT name, total FROM users", qr)

        assert "SELECT name, total FROM users" in summary
        assert "name" in summary
        assert "total" in summary
        assert "2" in summary

    def test_with_no_query(self):
        qr = QueryResult(columns=["a"], rows=[[1]], row_count=1)
        summary = StageExecutor._summarize_query_result(None, qr)

        assert "Query:" not in summary
        assert "Columns:" in summary

    def test_sample_capped_at_five(self):
        rows = [[i] for i in range(20)]
        qr = QueryResult(columns=["num"], rows=rows, row_count=20)
        summary = StageExecutor._summarize_query_result("SELECT num", qr)

        assert "first 5" in summary


# ------------------------------------------------------------------
# _execute_with_retries()
# ------------------------------------------------------------------


class TestExecuteWithRetries:
    @pytest.mark.asyncio
    async def test_no_retry_on_success(self, executor, context, mock_sql_agent):
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        sql_result = MagicMock(spec=AgentResult)
        sql_result.status = "success"
        sql_result.results = qr
        sql_result.query = "SELECT 1"
        sql_result.token_usage = {}
        mock_sql_agent.run.return_value = sql_result

        stage = _sql_stage("s1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        with patch("app.agents.stage_executor.settings") as mock_settings:
            mock_settings.max_stage_retries = 2
            result = await executor._execute_with_retries(stage, stage_ctx, context)

        assert result.status == "success"
        assert mock_sql_agent.run.call_count == 1

    @pytest.mark.asyncio
    async def test_exhausts_retries(self, executor, context, mock_sql_agent, mock_tracker):
        error_result = MagicMock(spec=AgentResult)
        error_result.status = "error"
        error_result.error = "persistent failure"
        error_result.token_usage = {}
        mock_sql_agent.run.return_value = error_result

        stage = _sql_stage("s1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        with patch("app.agents.stage_executor.settings") as mock_settings:
            mock_settings.max_stage_retries = 1
            result = await executor._execute_with_retries(stage, stage_ctx, context)

        assert result.status == "error"
        assert mock_sql_agent.run.call_count == 2  # initial + 1 retry


# ------------------------------------------------------------------
# History scoping (GAP 1)
# ------------------------------------------------------------------


class TestHistoryScoping:
    """Verify that _run_sql_stage and _run_knowledge_stage pass scoped history."""

    @pytest.fixture
    def context_with_history(self, mock_llm, mock_tracker) -> AgentContext:
        from app.llm.base import Message

        history = [Message(role="user", content=f"old question {i}") for i in range(10)]
        return AgentContext(
            project_id="proj-1",
            connection_config=ConnectionConfig(db_type="postgres"),
            user_question="test question",
            chat_history=history,
            llm_router=mock_llm,
            tracker=mock_tracker,
            workflow_id="wf-test",
        )

    @pytest.mark.asyncio
    async def test_sql_stage_receives_scoped_history(
        self, executor, context_with_history, mock_sql_agent
    ):
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        sql_result = MagicMock(spec=AgentResult)
        sql_result.status = "success"
        sql_result.results = qr
        sql_result.query = "SELECT 1"
        sql_result.token_usage = {}
        mock_sql_agent.run.return_value = sql_result

        stage = _sql_stage("s1")
        await executor._run_sql_stage("test q", stage, context_with_history)

        call_ctx = mock_sql_agent.run.call_args[0][0]
        assert len(call_ctx.chat_history) == StageExecutor._SUB_AGENT_HISTORY_TAIL
        assert len(context_with_history.chat_history) == 10

    @pytest.mark.asyncio
    async def test_knowledge_stage_receives_scoped_history(
        self, executor, context_with_history, mock_knowledge_agent
    ):
        kb_result = MagicMock()
        kb_result.answer = "Found info"
        kb_result.token_usage = {}
        mock_knowledge_agent.run.return_value = kb_result

        stage = _kb_stage("kb1")
        await executor._run_knowledge_stage("test q", stage, context_with_history)

        call_ctx = mock_knowledge_agent.run.call_args[0][0]
        assert len(call_ctx.chat_history) == StageExecutor._SUB_AGENT_HISTORY_TAIL

    @pytest.mark.asyncio
    async def test_sql_stage_handles_empty_history(self, executor, context, mock_sql_agent):
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        sql_result = MagicMock(spec=AgentResult)
        sql_result.status = "success"
        sql_result.results = qr
        sql_result.query = "SELECT 1"
        sql_result.token_usage = {}
        mock_sql_agent.run.return_value = sql_result

        stage = _sql_stage("s1")
        await executor._run_sql_stage("test q", stage, context)

        call_ctx = mock_sql_agent.run.call_args[0][0]
        assert call_ctx.chat_history == []
