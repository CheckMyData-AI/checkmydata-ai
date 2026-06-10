"""Unit tests for StageExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

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
    # ``create_autospec`` enforces the real ``emit`` call signature (plain
    # ``AsyncMock(spec=...)`` does NOT), so an invalid emit() call - e.g. passing
    # ``status`` both positionally and via ``**extra`` - fails the test instead of
    # slipping through to production.
    return create_autospec(WorkflowTracker, instance=True)


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
    async def test_stuck_dependency_returns_stage_failed(self, executor, context):
        """R5-6: a plan whose only stage depends on a missing stage can never
        become ready; the executor must surface ``stage_failed`` (replan-
        eligible) instead of silently synthesizing partial results as
        ``completed``."""
        stuck = PlanStage(
            stage_id="s1",
            description="depends on a stage that does not exist",
            tool="query_database",
            depends_on=["does-not-exist"],
        )
        plan = _make_plan(stuck)
        result = await executor.execute(plan, context)

        assert result.status == "stage_failed"
        assert result.replan_eligible is True
        assert result.failed_stage is not None
        assert result.failed_stage.stage_id == "s1"

    @pytest.mark.asyncio
    async def test_stuck_dependency_emits_stage_failed_event(self, executor, context, mock_tracker):
        """R5-6: the stuck pipeline must also tell SSE consumers via a
        ``stage_failed`` tracker event, not just the return status."""
        stuck = PlanStage(
            stage_id="s1",
            description="depends on a stage that does not exist",
            tool="query_database",
            depends_on=["does-not-exist"],
        )
        await executor.execute(_make_plan(stuck), context)

        failed_emits = [c for c in mock_tracker.emit.await_args_list if c.args[1] == "stage_failed"]
        assert len(failed_emits) == 1
        call = failed_emits[0]
        assert call.args[0] == "wf-test"
        assert call.args[2] == "failed"
        assert call.kwargs["stage_id"] == "s1"
        assert call.kwargs["remaining_stage_ids"] == ["s1"]

    def test_missing_operation_defaults_to_passthrough(self):
        """R5-8: a process_data stage without an explicit operation must default
        to ``passthrough`` (forward rows unchanged) rather than guessing
        ``filter_data``, which silently drops rows or errors on a missing
        column."""
        qr = QueryResult(columns=["x"], rows=[[1]], row_count=1)
        stage = PlanStage(
            stage_id="p1",
            description="process",
            tool="process_data",
            input_context=None,
        )
        params = StageExecutor._parse_process_data_params(stage, qr)
        assert params["operation"] == "passthrough"

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
            mock_settings.pipeline_max_parallel_stages = 1
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
            mock_settings.pipeline_max_parallel_stages = 1
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
        stage.max_retries = 1
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

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

        from app.config import settings as _s

        call_ctx = mock_sql_agent.run.call_args[0][0]
        assert len(call_ctx.chat_history) == _s.history_tail_messages
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

        from app.config import settings as _s

        call_ctx = mock_knowledge_agent.run.call_args[0][0]
        assert len(call_ctx.chat_history) == _s.history_tail_messages

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


def _git_stage(stage_id: str = "g1") -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description=f"Git stage {stage_id}",
        tool="analyze_git",
    )


class TestGitStage:
    """analyze_git stage dispatch via the injected GitAgent."""

    @pytest.fixture
    def mock_git_agent(self):
        agent = AsyncMock()
        agent.run = AsyncMock()
        return agent

    @pytest.fixture
    def git_executor(
        self,
        mock_sql_agent,
        mock_knowledge_agent,
        mock_llm,
        mock_tracker,
        mock_validator,
        mock_git_agent,
    ):
        return StageExecutor(
            sql_agent=mock_sql_agent,
            knowledge_agent=mock_knowledge_agent,
            llm_router=mock_llm,
            tracker=mock_tracker,
            validator=mock_validator,
            git_agent=mock_git_agent,
        )

    @pytest.mark.asyncio
    async def test_dispatches_analyze_git(self, git_executor, context, mock_git_agent):
        git_result = MagicMock()
        git_result.answer = "v1.2.0 released 2026-01-15"
        git_result.token_usage = {}
        mock_git_agent.run.return_value = git_result

        stage = _git_stage("g1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        result = await git_executor._execute_stage(stage, stage_ctx, context)

        assert result.status == "success"
        assert "v1.2.0" in result.summary
        mock_git_agent.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_answer_is_error(self, git_executor, context, mock_git_agent):
        git_result = MagicMock()
        git_result.answer = ""
        git_result.token_usage = {}
        mock_git_agent.run.return_value = git_result

        stage = _git_stage("g1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        result = await git_executor._execute_stage(stage, stage_ctx, context)

        assert result.status == "error"
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_git_agent_returns_error(self, executor, context):
        """The default executor (no git_agent) reports git is unavailable."""
        stage = _git_stage("g1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        result = await executor._execute_stage(stage, stage_ctx, context)

        assert result.status == "error"
        assert "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_git_stage_receives_scoped_history(
        self, git_executor, mock_git_agent, mock_llm, mock_tracker
    ):
        from app.llm.base import Message

        git_result = MagicMock()
        git_result.answer = "ok"
        git_result.token_usage = {}
        mock_git_agent.run.return_value = git_result

        history = [Message(role="user", content=f"q{i}") for i in range(10)]
        ctx = AgentContext(
            project_id="proj-1",
            connection_config=ConnectionConfig(db_type="postgres"),
            user_question="test",
            chat_history=history,
            llm_router=mock_llm,
            tracker=mock_tracker,
            workflow_id="wf-test",
        )

        await git_executor._run_git_stage("test q", _git_stage("g1"), ctx)

        from app.config import settings as _s

        call_ctx = mock_git_agent.run.call_args[0][0]
        assert len(call_ctx.chat_history) == _s.history_tail_messages


class TestStalenessInjection:
    """V3 — vision §7 #7: complex pipeline must inject freshness warning into
    every LLM-touching surface (planner, stage prompts, synthesis)."""

    @pytest.mark.asyncio
    async def test_stage_question_includes_staleness_when_set(self, executor):
        executor._staleness_warning = "Connection schema not refreshed in 14 days."

        stage = _sql_stage("s1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        q = executor._build_stage_question(stage, stage_ctx)

        assert "KNOWLEDGE FRESHNESS WARNINGS:" in q
        assert "14 days" in q
        assert "Task: SQL stage s1" in q

    @pytest.mark.asyncio
    async def test_stage_question_omits_staleness_when_none(self, executor):
        executor._staleness_warning = None

        stage = _sql_stage("s1")
        plan = _make_plan(stage)
        stage_ctx = StageContext(plan=plan)

        q = executor._build_stage_question(stage, stage_ctx)

        assert "KNOWLEDGE FRESHNESS WARNINGS" not in q

    @pytest.mark.asyncio
    async def test_synthesis_system_prompt_includes_staleness(self, executor, context, mock_llm):
        executor._staleness_warning = "Codebase last indexed 30 days ago."

        plan = _make_plan(_sql_stage("s1"))
        stage_ctx = StageContext(plan=plan)
        stage_ctx.set_result(
            "s1",
            StageResult(
                stage_id="s1",
                status="success",
                summary="42 rows fetched",
            ),
        )

        mock_llm.complete.return_value = LLMResponse(content="Final answer")

        with patch(
            "app.agents.stage_executor.llm_call_with_retry",
            new_callable=AsyncMock,
        ) as mock_call:
            mock_call.return_value = LLMResponse(content="Final answer")
            answer, degraded = await executor._synthesize(stage_ctx, context)

        assert answer == "Final answer"
        assert degraded is None
        msgs = mock_call.call_args.kwargs["messages"]
        system_msg = next(m for m in msgs if m.role == "system")
        assert "KNOWLEDGE FRESHNESS WARNINGS:" in system_msg.content
        assert "30 days" in system_msg.content

    @pytest.mark.asyncio
    async def test_execute_threads_staleness_into_executor(
        self, executor, context, mock_sql_agent, mock_llm
    ):
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        sql_result = MagicMock(spec=AgentResult)
        sql_result.status = "success"
        sql_result.results = qr
        sql_result.query = "SELECT 1"
        sql_result.token_usage = {}
        mock_sql_agent.run.return_value = sql_result

        plan = _make_plan(_sql_stage("s1"))

        with patch(
            "app.agents.stage_executor.llm_call_with_retry",
            new_callable=AsyncMock,
        ) as mock_call:
            mock_call.return_value = LLMResponse(content="Final answer")
            await executor.execute(
                plan,
                context,
                staleness_warning="KB stale (7 days).",
            )

        assert executor._staleness_warning == "KB stale (7 days)."


class TestEmitStageResult:
    """Regression: _emit_stage_result must not pass ``status`` both positionally
    and via ``**extra`` (would raise ``emit() got multiple values for argument
    'status'`` and crash every multi-stage plan)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["success", "error"])
    async def test_emit_stage_result_no_status_collision(self, executor, mock_tracker, status):
        stage = _sql_stage("s1")
        result = StageResult(
            stage_id="s1",
            status=status,
            summary="done",
            query_result=QueryResult(columns=["a"], rows=[[1]], row_count=1),
        )

        # With the autospec'd tracker this raises TypeError if status is passed twice.
        await executor._emit_stage_result("wf-test", stage, result)

        mock_tracker.emit.assert_awaited_once()
        call = mock_tracker.emit.await_args
        # status delivered as the positional arg (top-level WorkflowEvent.status)
        assert call.args[0] == "wf-test"
        assert call.args[1] == "stage_result"
        assert call.args[2] == status
        # and NOT duplicated inside extra kwargs
        assert "status" not in call.kwargs
        assert call.kwargs["stage_id"] == "s1"
        assert call.kwargs["row_count"] == 1
