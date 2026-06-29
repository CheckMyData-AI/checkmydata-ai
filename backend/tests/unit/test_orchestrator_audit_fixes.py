"""Audit-High remediation tests for ``app/agents/orchestrator.py``.

Four isolated findings, each with a focused regression test:

1. Budget hard-stop never emits ``pipeline_end`` — the terminal
   :class:`AgentResponse` was returned without ``tracker.end(...)``, so the
   workflow was only closed by a downstream fallback net mislabeled
   "pipeline_end never emitted". The hard-stop must end the workflow itself
   (status ``failed``, detail = the budget reason), guarded against a
   double-end.
2. ``executed_pairs[tc.id]`` ``KeyError`` discarded the whole turn — the
   tool_pairs rebuild iterated the *original* ``llm_resp.tool_calls`` (which may
   carry a duplicate or stray id) but indexed a dict keyed by the *deduplicated*
   ``active_calls``. A missing id raised ``KeyError`` that bubbled to ``run()``'s
   catch-all and threw away every gathered result. It must degrade gracefully.
3. Generic exception handler leaked raw ``str(exc)`` to the client — DB DSNs,
   hostnames, etc. ended up in ``AgentResponse.error`` and the ``tracker.end``
   detail. Only the exception *type name* may be surfaced; full detail stays
   server-side via ``logger.exception``.
4. Replan could build a plan whose ``depends_on`` points at a dropped
   (non-success) stage that is neither in the new plan nor seeded — the executor
   then reports "pipeline stuck", wasting a replan. Such a structurally-doomed
   plan must be rejected up front (log + break to honest partial results).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base import AgentContext
from app.agents.orchestrator import OrchestratorAgent
from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
from app.agents.tools.orchestrator_tools import get_orchestrator_tools
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall

# ---------------------------------------------------------------------------
# Test doubles (mirrors tests/unit/test_orchestrator_budget.py conventions)
# ---------------------------------------------------------------------------


class _StubSink:
    """Minimal UsageSink-shaped double whose ``budget_exceeded`` is scripted."""

    def __init__(self, reason: str | None = None) -> None:
        self._reason = reason

    async def observe(self, **_: object) -> None:  # pragma: no cover — protocol shape
        return None

    def budget_exceeded(self) -> str | None:
        return self._reason


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()
    # Default: NOT ended yet, so the hard-stop is expected to emit the end.
    t.has_ended = MagicMock(return_value=False)

    @asynccontextmanager
    async def fake_step(wf_id, step, detail="", **kwargs):
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


@pytest.fixture
def base_context(mock_llm, mock_tracker):
    return AgentContext(
        project_id="test-proj",
        connection_config=None,
        user_question="What is X?",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
        project_name="TestProject",
    )


# ---------------------------------------------------------------------------
# Finding 1: budget hard-stop must emit a single terminal pipeline_end
# ---------------------------------------------------------------------------


class TestBudgetHardStopEmitsPipelineEnd:
    @pytest.mark.asyncio
    async def test_hard_stop_ends_workflow_exactly_once_with_reason(
        self, orch, mock_llm, mock_tracker, base_context
    ):
        """A sticky budget breach must end the workflow itself (status
        ``failed``, detail = the budget reason) before returning — exactly once.
        """
        reason = "Daily limit exceeded — upgrade"
        sink = _StubSink(reason=reason)
        mock_llm._sink = sink
        mock_llm.complete = AsyncMock(return_value=LLMResponse(content="should not be called"))

        tools = get_orchestrator_tools(has_knowledge_base=True)
        resp = await orch._run_tool_loop(
            base_context,
            "wf-1",
            has_connection=False,
            db_type=None,
            has_kb=True,
            has_mcp=False,
            has_repo=False,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            custom_rules="",
            tools=tools,
            staleness_warning=None,
            route_result=None,
        )

        # No LLM call issued; terminal error response carries the reason.
        assert mock_llm.complete.await_count == 0
        assert resp.response_type == "error"
        assert resp.error == reason

        # The hard-stop emitted the terminal pipeline_end exactly once with a
        # "failed" status and the budget reason as the detail.
        assert mock_tracker.end.await_count == 1
        args, kwargs = mock_tracker.end.await_args
        called = list(args) + list(kwargs.values())
        assert "failed" in called
        assert reason in called

    @pytest.mark.asyncio
    async def test_hard_stop_does_not_double_end_when_already_ended(
        self, orch, mock_llm, mock_tracker, base_context
    ):
        """If the workflow was already ended, the hard-stop must not end again."""
        reason = "Monthly limit exceeded — upgrade plan"
        sink = _StubSink(reason=reason)
        mock_llm._sink = sink
        mock_llm.complete = AsyncMock(return_value=LLMResponse(content="should not be called"))
        mock_tracker.has_ended = MagicMock(return_value=True)

        tools = get_orchestrator_tools(has_knowledge_base=True)
        resp = await orch._run_tool_loop(
            base_context,
            "wf-1",
            has_connection=False,
            db_type=None,
            has_kb=True,
            has_mcp=False,
            has_repo=False,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            custom_rules="",
            tools=tools,
            staleness_warning=None,
            route_result=None,
        )

        assert resp.response_type == "error"
        assert resp.error == reason
        assert mock_tracker.end.await_count == 0


# ---------------------------------------------------------------------------
# Finding 2: duplicate/missing tool-call id must not raise / discard the turn
# ---------------------------------------------------------------------------


class TestDuplicateToolCallIdDoesNotDiscardTurn:
    @pytest.mark.asyncio
    async def test_dispatch_id_mismatch_does_not_discard_turn(
        self, orch, mock_llm, base_context, monkeypatch
    ):
        """A ``tool_calls`` batch where the executed-pairs dict (keyed by the
        deduplicated ``active_calls`` ids) does NOT cover an id present in the
        original ``llm_resp.tool_calls`` must NOT raise ``KeyError`` and discard
        the whole turn.

        The rebuild at the bottom of the loop iterates ``llm_resp.tool_calls``
        but indexes a dict built from ``active_calls``; any duplicate/missing id
        (an internal dedup↔dispatch mismatch) used to raise ``KeyError`` that
        bubbled to ``run()``'s catch-all and threw away every gathered result.
        It must degrade to a graceful fallback tool message instead.

        We force the mismatch deterministically by patching ``dedup_tool_calls``
        to return a single kept call whose id ('real') differs from one of the
        two ids in the original batch ('ghost') — exactly the "internal
        dispatch mismatch" the fallback message names.
        """
        from app.agents.tool_dispatcher import ToolDispatcher

        sink = _StubSink(reason=None)
        mock_llm._sink = sink

        ghost = ToolCall(id="ghost", name="search_codebase", arguments={"question": "a"})
        real = ToolCall(id="real", name="search_codebase", arguments={"question": "b"})

        responses = [
            LLMResponse(content="", tool_calls=[ghost, real]),
            LLMResponse(content="Final answer."),
        ]

        async def _complete(**_kwargs):
            return responses.pop(0)

        mock_llm.complete = AsyncMock(side_effect=_complete)
        orch._dispatcher.dispatch = AsyncMock(return_value=("ok result", None))

        # dedup keeps only 'real' and records NOTHING in skipped_map → the
        # rebuild over [ghost, real] hits an id ('ghost') absent from both
        # executed_pairs and skipped_map.
        def _fake_dedup(tool_calls):
            return [real], {}

        monkeypatch.setattr(ToolDispatcher, "dedup_tool_calls", staticmethod(_fake_dedup))

        tools = get_orchestrator_tools(has_knowledge_base=True)
        # Must not raise; must run to a final answer.
        resp = await orch._run_tool_loop(
            base_context,
            "wf-1",
            has_connection=False,
            db_type=None,
            has_kb=True,
            has_mcp=False,
            has_repo=False,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            custom_rules="",
            tools=tools,
            staleness_warning=None,
            route_result=None,
        )

        assert resp.response_type != "error"
        assert resp.answer == "Final answer."

        # The second LLM call received a tool message for BOTH original tool
        # calls (one real result, one graceful fallback) — none were dropped.
        second_call_kwargs = mock_llm.complete.await_args_list[1].kwargs
        messages = second_call_kwargs["messages"]
        tool_msgs = [m for m in messages if getattr(m, "role", None) == "tool"]
        assert len(tool_msgs) == 2


# ---------------------------------------------------------------------------
# Finding 3: generic exception handler must not leak raw str(exc)
# ---------------------------------------------------------------------------


class TestGenericErrorDoesNotLeakSecrets:
    @pytest.mark.asyncio
    async def test_exception_text_with_secret_not_in_response_error(
        self, orch, mock_tracker, base_context
    ):
        """A raised exception whose message looks like a DSN/host must not have
        its text surfaced in ``AgentResponse.error`` — only the type name.
        """
        secret = "postgres://admin:s3cr3t@db.internal.example:5432/prod"

        class WeirdBoomError(RuntimeError):
            pass

        # Force the very first thing run() does after entering the try block to
        # blow up with a secret-laden message.
        orch._cleanup_stale_results = MagicMock()
        orch._apply_continuation_context = MagicMock(side_effect=WeirdBoomError(secret))
        base_context.extra["pipeline_action"] = "continue_analysis"

        resp = await orch.run(base_context)

        assert resp.response_type == "error"
        # Only the exception type name is surfaced; the secret text is not.
        assert resp.error == "WeirdBoomError"
        assert secret not in (resp.error or "")
        assert secret not in (resp.answer or "")

        # The tracker.end detail must also be the type name, never str(exc).
        assert mock_tracker.end.await_count == 1
        args, kwargs = mock_tracker.end.await_args
        called = list(args) + list(kwargs.values())
        assert "WeirdBoomError" in called
        assert secret not in called


# ---------------------------------------------------------------------------
# Finding 4: replan with a dangling dependency must be rejected up front
# ---------------------------------------------------------------------------


class TestStreamTokenChurn:
    """L2: a very long answer must not flood SSE with token events."""

    @pytest.mark.asyncio
    async def test_long_answer_caps_token_events(self, orch, mock_tracker, base_context):
        from app.agents.orchestrator import _MAX_TOKEN_EVENTS

        await orch._stream_tokens("wf-1", "x" * 100_000)

        token_emits = [
            c
            for c in mock_tracker.emit.await_args_list
            if len(c.args) > 1 and c.args[1] == "token"
        ]
        assert 0 < len(token_emits) <= _MAX_TOKEN_EVENTS


class TestDirectMisrouteRecovery:
    """C1: a question mis-routed 'direct' that needs data re-routes to tools."""

    def _llm_resp(self, content: str):
        from app.llm.base import LLMResponse

        return LLMResponse(content=content, provider="p", model="m", usage={})

    @pytest.mark.asyncio
    async def test_sentinel_reroutes_returns_none(self, orch, mock_tracker, base_context):
        from unittest.mock import AsyncMock

        from app.agents.prompts.orchestrator_prompt import NEEDS_DATA_SENTINEL

        orch._llm_call_with_retry = AsyncMock(return_value=self._llm_resp(NEEDS_DATA_SENTINEL))
        resp = await orch._run_direct_response(
            base_context, "wf-1", has_connection=True, has_kb=False, has_mcp=False, has_repo=False
        )
        assert resp is None

    @pytest.mark.asyncio
    async def test_normal_answer_returns_response(self, orch, mock_tracker, base_context):
        from unittest.mock import AsyncMock

        orch._llm_call_with_retry = AsyncMock(return_value=self._llm_resp("Hello there!"))
        resp = await orch._run_direct_response(
            base_context, "wf-1", has_connection=True, has_kb=False, has_mcp=False, has_repo=False
        )
        assert resp is not None
        assert resp.answer == "Hello there!"

    @pytest.mark.asyncio
    async def test_sentinel_ignored_without_data_source(self, orch, mock_tracker, base_context):
        # No data source → no re-route target; the sentinel is treated as a
        # (degenerate) literal answer rather than looping.
        from unittest.mock import AsyncMock

        from app.agents.prompts.orchestrator_prompt import NEEDS_DATA_SENTINEL

        orch._llm_call_with_retry = AsyncMock(return_value=self._llm_resp(NEEDS_DATA_SENTINEL))
        resp = await orch._run_direct_response(
            base_context, "wf-1", has_connection=False, has_kb=False, has_mcp=False, has_repo=False
        )
        assert resp is not None


class TestResumeIdempotency:
    """B7: duplicate concurrent resume of the same pipeline_run_id is rejected."""

    @pytest.mark.asyncio
    async def test_duplicate_concurrent_resume_rejected(self, orch, mock_tracker, base_context):
        orch._resuming_run_ids.add("run-xyz")
        resp = await orch._resume_pipeline(
            {"pipeline_run_id": "run-xyz", "action": "continue"}, base_context
        )
        assert resp.response_type == "error"
        assert "already being resumed" in resp.answer.lower()
        # The guard rejects without claiming the lock a second time.
        assert orch._resuming_run_ids == {"run-xyz"}


class TestPlanFingerprint:
    """B3: _plan_fingerprint identifies semantically-equal plans."""

    def test_identical_content_same_fingerprint_despite_ids(self):
        from app.agents.orchestrator import _plan_fingerprint

        p1 = ExecutionPlan(
            plan_id="orig",
            question="q",
            stages=[
                PlanStage(stage_id="s1", description="Sum revenue", tool="query_database"),
                PlanStage(stage_id="s2", description="aggregate", tool="process_data"),
            ],
        )
        p2 = ExecutionPlan(
            plan_id="replan-9",
            question="q2",
            stages=[
                PlanStage(stage_id="x", description="sum  revenue", tool="query_database"),
                PlanStage(stage_id="y", description="aggregate", tool="process_data"),
            ],
        )
        assert _plan_fingerprint(p1) == _plan_fingerprint(p2)

    def test_changed_tool_or_description_differs(self):
        from app.agents.orchestrator import _plan_fingerprint

        base = ExecutionPlan(
            plan_id="orig",
            question="q",
            stages=[PlanStage(stage_id="s1", description="Sum revenue", tool="query_database")],
        )
        diff_desc = ExecutionPlan(
            plan_id="orig",
            question="q",
            stages=[PlanStage(stage_id="s1", description="Count users", tool="query_database")],
        )
        diff_tool = ExecutionPlan(
            plan_id="orig",
            question="q",
            stages=[PlanStage(stage_id="s1", description="Sum revenue", tool="search_codebase")],
        )
        assert _plan_fingerprint(base) != _plan_fingerprint(diff_desc)
        assert _plan_fingerprint(base) != _plan_fingerprint(diff_tool)


def _failed_exec_result(completed: dict[str, StageResult]):
    """Build a stage-failed ``_StageExecutorResult`` carrying ``completed``."""
    from app.agents.stage_executor import _StageExecutorResult

    plan = ExecutionPlan(
        plan_id="orig",
        question="q",
        stages=[
            PlanStage(stage_id="s1", description="d1", tool="query_database"),
            PlanStage(stage_id="s2", description="d2", tool="query_database"),
        ],
    )
    stage_ctx = StageContext(plan=plan, pipeline_run_id="run-1")
    stage_ctx.results = completed
    return _StageExecutorResult(
        status="stage_failed",
        stage_ctx=stage_ctx,
        failed_stage=plan.stages[1],
        replan_eligible=True,
    )


class TestReplanDanglingDependency:
    @pytest.mark.asyncio
    async def test_replan_with_dangling_dep_is_not_executed(self, orch, mock_tracker, base_context):
        """When the replanned plan has a stage whose ``depends_on`` points at an
        id that is neither in the new plan nor a carried-over success stage, the
        replan must be treated as failed: the executor must NOT be invoked and
        the loop breaks to honest partial results (no wasted execute()).
        """
        # s1 failed (status="error"), so it is NOT seeded into the new context.
        completed = {
            "s1": StageResult(stage_id="s1", status="error", error="boom"),
        }
        exec_result = _failed_exec_result(completed)

        # Replanned plan: its only stage depends on "s1", which is neither in
        # the new plan nor a carried-over success → structurally doomed.
        dangling_plan = ExecutionPlan(
            plan_id="replan-1",
            question="q",
            stages=[
                PlanStage(
                    stage_id="s3",
                    description="needs s1",
                    tool="query_database",
                    depends_on=["s1"],
                ),
            ],
        )

        adaptive = MagicMock()
        adaptive.replan = AsyncMock(return_value=dangling_plan)

        executor = MagicMock()
        executor.execute = AsyncMock()  # must NOT be called

        result, replan_history = await orch._run_pipeline_replans(
            executor=executor,
            exec_result=exec_result,
            pipeline_ctx=base_context,
            context=base_context,
            adaptive=adaptive,
            table_map="",
            db_type=None,
            staleness_warning=None,
            run_id="run-1",
            wf_id="wf-1",
        )

        # The structurally-doomed plan was never executed.
        assert executor.execute.await_count == 0
        # The original (stage_failed) result is surfaced as honest partial.
        assert result is exec_result
        assert result.status == "stage_failed"
        # One replan attempt was recorded before breaking.
        assert len(replan_history) == 1

    @pytest.mark.asyncio
    async def test_replan_repeating_failed_plan_is_not_executed(
        self, orch, mock_tracker, base_context
    ):
        """B3: a replan semantically identical to a plan already tried (same
        tool/description/input_context sequence; only ids differ) must be
        rejected as oscillation — not executed — so a doomed plan is not
        re-run until the replan budget is exhausted."""
        completed = {"s1": StageResult(stage_id="s1", status="error", error="boom")}
        exec_result = _failed_exec_result(completed)

        # Same semantic content as the original failing plan (d1/d2,
        # query_database), only the ids/plan_id differ.
        repeat_plan = ExecutionPlan(
            plan_id="replan-1",
            question="q",
            stages=[
                PlanStage(stage_id="a", description="d1", tool="query_database"),
                PlanStage(stage_id="b", description="d2", tool="query_database"),
            ],
        )
        adaptive = MagicMock()
        adaptive.replan = AsyncMock(return_value=repeat_plan)
        executor = MagicMock()
        executor.execute = AsyncMock()  # must NOT be called

        result, replan_history = await orch._run_pipeline_replans(
            executor=executor,
            exec_result=exec_result,
            pipeline_ctx=base_context,
            context=base_context,
            adaptive=adaptive,
            table_map="",
            db_type=None,
            staleness_warning=None,
            run_id="run-1",
            wf_id="wf-1",
        )

        assert executor.execute.await_count == 0
        assert result is exec_result
        assert result.status == "stage_failed"
        assert len(replan_history) == 1

    @pytest.mark.asyncio
    async def test_replan_with_satisfiable_deps_is_executed(self, orch, mock_tracker, base_context):
        """A replanned plan whose deps reference only carried-over success
        stages (or its own stages) must still be executed normally.
        """
        from app.agents.stage_executor import _StageExecutorResult

        # s1 succeeded → seeded into the new context; s2 failed.
        completed = {
            "s1": StageResult(stage_id="s1", status="success", summary="ok"),
        }
        exec_result = _failed_exec_result(completed)

        good_plan = ExecutionPlan(
            plan_id="replan-ok",
            question="q",
            stages=[
                PlanStage(
                    stage_id="s4",
                    description="depends on carried-over s1",
                    tool="query_database",
                    depends_on=["s1"],
                ),
            ],
        )

        adaptive = MagicMock()
        adaptive.replan = AsyncMock(return_value=good_plan)

        final_ctx = StageContext(plan=good_plan, pipeline_run_id="run-1")
        success_result = _StageExecutorResult(status="completed", stage_ctx=final_ctx)
        executor = MagicMock()
        executor.execute = AsyncMock(return_value=success_result)

        result, replan_history = await orch._run_pipeline_replans(
            executor=executor,
            exec_result=exec_result,
            pipeline_ctx=base_context,
            context=base_context,
            adaptive=adaptive,
            table_map="",
            db_type=None,
            staleness_warning=None,
            run_id="run-1",
            wf_id="wf-1",
        )

        assert executor.execute.await_count == 1
        assert result is success_result
        assert result.status == "completed"
        assert len(replan_history) == 1
