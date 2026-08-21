"""Tests for ORCH-P03, RP01, RP02 and stage_executor ORCH-P02 acceptance.

ORCH-P02: _parse_process_data_params accepts params_json wrapper.
ORCH-P03: trivial <=2 data-stage plans bounce to unified loop.
ORCH-RP01: degraded stages are carried on replan (seeded + allowed as dep).
ORCH-RP02: replan_history stores failed_stage_tool (tool name, not stage_id).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.stage_context import (
    ExecutionPlan,
    PlanStage,
    QueryResult,
    StageResult,
)
from app.agents.stage_executor import StageExecutor

# ---------------------------------------------------------------------------
# ORCH-P02: _parse_process_data_params accepts params_json wrapper
# ---------------------------------------------------------------------------


class TestParseProcessDataParamsAcceptsParamsJson:
    """ORCH-P02: pipeline path _parse_process_data_params must unwrap params_json."""

    def _make_stage(self, input_context: str) -> PlanStage:
        return PlanStage(
            stage_id="enrich",
            description="enrich IPs",
            tool="process_data",
            input_context=input_context,
        )

    def _make_source_qr(self) -> QueryResult:
        return QueryResult(
            columns=["ip", "country"],
            rows=[["1.2.3.4", "US"]],
            row_count=1,
        )

    def test_top_level_keys_accepted(self) -> None:
        """Existing top-level key format still works."""
        import json

        stage = self._make_stage(json.dumps({"operation": "ip_to_country", "column": "ip"}))
        params = StageExecutor._parse_process_data_params(stage, self._make_source_qr())
        assert params["operation"] == "ip_to_country"
        assert params["column"] == "ip"

    def test_params_json_wrapper_unwrapped(self) -> None:
        """params_json wrapper is unwrapped to top-level keys."""
        import json

        wrapped = {
            "operation": "cohort_window",
            "params_json": {
                "release_dates": [{"tag": "v1.0", "date": "2026-01-01"}],
                "event_date_column": "created_at",
                "value_column": "amount",
                "windows": [7, 14],
                "metric": "revenue",
            },
        }
        stage = self._make_stage(json.dumps(wrapped))
        params = StageExecutor._parse_process_data_params(stage, self._make_source_qr())
        assert params["operation"] == "cohort_window"
        assert "release_dates" in params
        assert params["event_date_column"] == "created_at"
        # params_json key should be removed
        assert "params_json" not in params

    def test_params_json_as_sole_key(self) -> None:
        """params_json with operation inside it also works."""
        import json

        wrapped = {
            "params_json": {
                "operation": "ip_to_country",
                "column": "src_ip",
            },
        }
        stage = self._make_stage(json.dumps(wrapped))
        params = StageExecutor._parse_process_data_params(stage, self._make_source_qr())
        assert params["operation"] == "ip_to_country"
        assert params["column"] == "src_ip"
        assert "params_json" not in params

    def test_top_level_keys_take_precedence_over_params_json_overlap(self) -> None:
        """Top-level keys win when both params_json and top-level provide same key."""
        import json

        wrapped = {
            "operation": "ip_to_country",
            "column": "top_level_column",
            "params_json": {
                "operation": "cohort_window",
                "column": "inner_column",
            },
        }
        stage = self._make_stage(json.dumps(wrapped))
        params = StageExecutor._parse_process_data_params(stage, self._make_source_qr())
        # top-level keys should win
        assert params["operation"] == "ip_to_country"
        assert params["column"] == "top_level_column"


# ---------------------------------------------------------------------------
# ORCH-P03: trivial <=2 data-stage plan bounces to unified loop
# ---------------------------------------------------------------------------


class TestTrivialPlanBouncesToUnified:
    """ORCH-P03: a plan with <=2 data stages should fall back to the unified loop."""

    def _make_orch(self) -> Any:
        """Build a minimal OrchestratorAgent with mocked internals."""
        from app.agents.orchestrator import OrchestratorAgent

        orch = object.__new__(OrchestratorAgent)
        # Wire up minimal mocks needed by _run_complex_pipeline
        orch._llm = MagicMock()
        orch._tracker = MagicMock()
        orch._tracker.emit = AsyncMock()
        orch._tracker.step = MagicMock()
        orch._tracker.step.return_value.__aenter__ = AsyncMock(return_value=None)
        orch._tracker.step.return_value.__aexit__ = AsyncMock(return_value=False)
        orch._sql = MagicMock()
        orch._knowledge = MagicMock()
        orch._mcp_source = MagicMock()
        orch._git = MagicMock()
        orch._llm_sink = MagicMock(return_value=None)
        orch._ctx_loader = MagicMock()
        orch._ctx_loader.load_recent_learnings = AsyncMock(return_value=None)
        orch._ctx_loader.load_relevant_insights = AsyncMock(return_value=None)
        return orch

    def _make_trivial_plan(self, n_data_stages: int) -> ExecutionPlan:
        """Build a plan with exactly n_data_stages data stages + a synthesize stage."""
        data_tools = ["query_database", "search_codebase", "query_mcp_source", "analyze_git"]
        stages = []
        for i in range(n_data_stages):
            stages.append(
                PlanStage(
                    stage_id=f"fetch_{i}",
                    description=f"fetch {i}",
                    tool=data_tools[i % len(data_tools)],
                )
            )
        stages.append(
            PlanStage(
                stage_id="synth",
                description="synthesize",
                tool="synthesize",
                depends_on=[s.stage_id for s in stages],
            )
        )
        return ExecutionPlan(
            plan_id="test-plan",
            question="test question",
            stages=stages,
            plan_type="full",
        )

    def _make_context(self) -> Any:
        from app.agents.base import AgentContext
        from app.llm.router import LLMRouter

        llm = MagicMock(spec=LLMRouter)
        ctx = AgentContext(
            project_id="proj-1",
            connection_config=MagicMock(),
            user_question="show me something",
            chat_history=[],
            llm_router=llm,
            tracker=MagicMock(),
            workflow_id="wf-0",
        )
        return ctx

    async def test_one_data_stage_plan_bounces(self) -> None:
        """A plan with 1 data stage (trivial) should bounce to unified loop."""
        orch = self._make_orch()
        trivial_plan = self._make_trivial_plan(1)
        context = self._make_context()

        # Patch AdaptivePlanner.plan to return the trivial plan
        fallback_response = MagicMock()
        fallback_response.answer = "unified loop answer"
        orch.run = AsyncMock(return_value=fallback_response)

        with patch("app.agents.orchestrator.AdaptivePlanner") as mock_planner_cls:
            mock_planner_instance = MagicMock()
            mock_planner_instance.plan = AsyncMock(return_value=trivial_plan)
            mock_planner_cls.return_value = mock_planner_instance

            await orch._run_complex_pipeline(context, "wf-1", "", "postgres", None)

        # Should have called orch.run (unified fallback) with _skip_complexity=True
        orch.run.assert_called_once()
        call_ctx = orch.run.call_args[0][0]
        assert call_ctx.extra.get("_skip_complexity") is True

    async def test_two_data_stage_plan_bounces(self) -> None:
        """A plan with 2 data stages (trivial) should bounce to unified loop."""
        orch = self._make_orch()
        trivial_plan = self._make_trivial_plan(2)
        context = self._make_context()

        fallback_response = MagicMock()
        orch.run = AsyncMock(return_value=fallback_response)

        with patch("app.agents.orchestrator.AdaptivePlanner") as mock_planner_cls:
            mock_planner_instance = MagicMock()
            mock_planner_instance.plan = AsyncMock(return_value=trivial_plan)
            mock_planner_cls.return_value = mock_planner_instance

            await orch._run_complex_pipeline(context, "wf-1", "", "postgres", None)

        orch.run.assert_called_once()
        call_ctx = orch.run.call_args[0][0]
        assert call_ctx.extra.get("_skip_complexity") is True

    async def test_three_data_stage_plan_does_not_bounce(self) -> None:
        """A plan with 3 data stages (non-trivial) should NOT bounce."""
        orch = self._make_orch()
        non_trivial_plan = self._make_trivial_plan(3)
        context = self._make_context()

        orch.run = AsyncMock()

        # Mock everything needed for normal pipeline execution
        mock_pipeline_run = MagicMock()
        mock_pipeline_run.id = "run-1"
        orch._create_pipeline_run = AsyncMock(return_value=mock_pipeline_run)

        mock_exec_result = MagicMock()
        mock_exec_result.status = "completed"
        mock_exec_result.stage_ctx = MagicMock()
        mock_exec_result.stage_ctx.results = {}
        mock_exec_result.failed_stage = None
        mock_exec_result.data_gate_outcome = None
        mock_exec_result.failed_validation = None

        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=mock_exec_result)

        with (
            patch("app.agents.orchestrator.AdaptivePlanner") as mock_planner_cls,
            patch("app.agents.orchestrator.StageExecutor", return_value=mock_executor),
            patch("app.agents.orchestrator.StageValidator"),
            patch("app.agents.orchestrator.DataGate"),
            patch.object(
                orch,
                "_run_pipeline_replans",
                new=AsyncMock(return_value=(mock_exec_result, [])),
            ),
            patch.object(orch, "_end_pipeline_workflow", new=AsyncMock()),
            patch.object(orch, "_persist_stage_results", new=AsyncMock()),
            patch.object(orch, "_extract_pipeline_learnings", new=AsyncMock()),
            patch("app.agents.orchestrator.ResponseBuilder") as mock_rb,
        ):
            mock_planner_instance = MagicMock()
            mock_planner_instance.plan = AsyncMock(return_value=non_trivial_plan)
            mock_planner_cls.return_value = mock_planner_instance

            mock_rb.build_pipeline_response.return_value = MagicMock(answer="real pipeline answer")

            await orch._run_complex_pipeline(context, "wf-1", "", "postgres", None)

        # Should NOT have called orch.run (no bounce)
        orch.run.assert_not_called()


# ---------------------------------------------------------------------------
# ORCH-RP01: degraded stages are carried on replan
# ---------------------------------------------------------------------------


class TestDegradedStageCarriedOnReplan:
    """ORCH-RP01: degraded stages should be seeded into new_stage_ctx on replan."""

    def _make_orch_for_replan(self) -> Any:
        """Build minimal OrchestratorAgent for replan tests."""
        from app.agents.orchestrator import OrchestratorAgent

        orch = object.__new__(OrchestratorAgent)
        orch._llm = MagicMock()
        orch._tracker = MagicMock()
        orch._tracker.emit = AsyncMock()
        return orch

    async def test_degraded_stage_is_seeded(self) -> None:
        """Degraded stage result should be seeded into new_stage_ctx."""
        from app.agents.orchestrator import OrchestratorAgent
        from app.agents.stage_context import StageContext

        orch = object.__new__(OrchestratorAgent)
        orch._llm = MagicMock()
        orch._tracker = MagicMock()
        orch._tracker.emit = AsyncMock()

        # Build a degraded stage result
        degraded_result = StageResult(
            stage_id="fetch_data",
            status="degraded",
            query_result=QueryResult(columns=["id", "name"], rows=[[1, "Alice"]], row_count=1),
            summary="Partial results due to timeout",
        )

        # Build a new plan that depends on the degraded stage
        new_stage = PlanStage(
            stage_id="analyze",
            description="analyze data",
            tool="analyze_results",
            depends_on=["fetch_data"],
        )
        synthesize_stage = PlanStage(
            stage_id="synth",
            description="synthesize",
            tool="synthesize",
            depends_on=["analyze"],
        )
        new_plan = ExecutionPlan(
            plan_id="replan-1",
            question="what happened?",
            stages=[new_stage, synthesize_stage],
            plan_type="full",
        )

        # Build initial exec_result with degraded stage in results
        failed_stage = PlanStage(
            stage_id="fetch_data",
            description="fetch data",
            tool="query_database",
        )

        mock_stage_ctx = MagicMock()
        mock_stage_ctx.results = {"fetch_data": degraded_result}
        mock_stage_ctx.plan = MagicMock()

        mock_exec_result = MagicMock()
        mock_exec_result.status = "stage_failed"
        mock_exec_result.replan_eligible = True
        mock_exec_result.failed_stage = failed_stage
        mock_exec_result.failed_validation = None
        mock_exec_result.data_gate_outcome = None
        mock_exec_result.stage_ctx = mock_stage_ctx

        # New exec result (after replan)
        new_exec_result = MagicMock()
        new_exec_result.status = "completed"
        new_exec_result.replan_eligible = False

        # Track what stage_ctx was passed to executor.execute
        seeded_stage_ctx_capture: list[StageContext] = []

        async def mock_execute(plan: Any, ctx: Any, stage_ctx: Any = None, **kwargs: Any) -> Any:
            seeded_stage_ctx_capture.append(stage_ctx)
            return new_exec_result

        mock_executor = MagicMock()
        mock_executor.execute = mock_execute

        mock_adaptive = MagicMock()
        mock_adaptive.replan = AsyncMock(return_value=new_plan)

        mock_pipeline_ctx = MagicMock()
        mock_context = MagicMock()
        mock_context.user_question = "what happened?"
        mock_context.preferred_provider = None
        mock_context.model = None

        with patch("app.agents.orchestrator.settings") as mock_settings:
            mock_settings.max_pipeline_replans = 2

            exec_result, replan_history = await orch._run_pipeline_replans(
                executor=mock_executor,
                exec_result=mock_exec_result,
                pipeline_ctx=mock_pipeline_ctx,
                context=mock_context,
                adaptive=mock_adaptive,
                table_map="",
                db_type="postgres",
                staleness_warning=None,
                run_id="run-1",
                wf_id="wf-1",
            )

        # Verify the new stage_ctx was seeded with the degraded result
        assert len(seeded_stage_ctx_capture) == 1
        new_ctx = seeded_stage_ctx_capture[0]
        seeded = new_ctx.get_result("fetch_data")
        assert seeded is not None, "degraded stage should be seeded into new_stage_ctx"
        assert seeded.status == "degraded"

    async def test_degraded_stage_allowed_as_dependency(self) -> None:
        """Degraded stage id should be in seedable_ids (no dangling-dep rejection)."""
        from app.agents.orchestrator import OrchestratorAgent

        orch = object.__new__(OrchestratorAgent)
        orch._llm = MagicMock()
        orch._tracker = MagicMock()
        orch._tracker.emit = AsyncMock()

        degraded_result = StageResult(
            stage_id="fetch_data",
            status="degraded",
            query_result=QueryResult(columns=["id"], rows=[[1]], row_count=1),
            summary="degraded",
        )

        # Plan with a dangling dep on the degraded stage id
        new_stage = PlanStage(
            stage_id="analyze",
            description="analyze",
            tool="analyze_results",
            depends_on=["fetch_data"],  # this was the degraded stage
        )
        new_plan = ExecutionPlan(
            plan_id="replan-2",
            question="q",
            stages=[new_stage],
            plan_type="full",
        )

        failed_stage = PlanStage(
            stage_id="fetch_data",
            description="fetch",
            tool="query_database",
        )

        mock_stage_ctx = MagicMock()
        mock_stage_ctx.results = {"fetch_data": degraded_result}
        mock_stage_ctx.plan = MagicMock()

        mock_exec_result = MagicMock()
        mock_exec_result.status = "stage_failed"
        mock_exec_result.replan_eligible = True
        mock_exec_result.failed_stage = failed_stage
        mock_exec_result.failed_validation = None
        mock_exec_result.data_gate_outcome = None
        mock_exec_result.stage_ctx = mock_stage_ctx

        completed_exec = MagicMock()
        completed_exec.status = "completed"
        completed_exec.replan_eligible = False

        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=completed_exec)

        mock_adaptive = MagicMock()
        mock_adaptive.replan = AsyncMock(return_value=new_plan)

        mock_context = MagicMock()
        mock_context.user_question = "q"
        mock_context.preferred_provider = None
        mock_context.model = None

        with patch("app.agents.orchestrator.settings") as mock_settings:
            mock_settings.max_pipeline_replans = 2

            exec_result, _ = await orch._run_pipeline_replans(
                executor=mock_executor,
                exec_result=mock_exec_result,
                pipeline_ctx=MagicMock(),
                context=mock_context,
                adaptive=mock_adaptive,
                table_map="",
                db_type=None,
                staleness_warning=None,
                run_id="run-1",
                wf_id="wf-1",
            )

        # If degraded is allowed as a dep, executor.execute should have been called
        # (plan was not rejected as dangling)
        mock_executor.execute.assert_called_once()


# ---------------------------------------------------------------------------
# ORCH-RP02: replan_history stores failed_stage_tool (tool name, not stage_id)
# ---------------------------------------------------------------------------


class TestReplanLearningGetsTool:
    """ORCH-RP02: replan history must store the tool name, not the stage_id."""

    async def test_replan_history_stores_tool_name(self) -> None:
        """replan_history entries must have failed_stage_tool = the actual tool name."""
        from app.agents.orchestrator import OrchestratorAgent

        orch = object.__new__(OrchestratorAgent)
        orch._llm = MagicMock()
        orch._tracker = MagicMock()
        orch._tracker.emit = AsyncMock()

        # The failed stage has stage_id="fetch_rev" and tool="query_database"
        failed_stage = PlanStage(
            stage_id="fetch_rev",
            description="fetch revenue",
            tool="query_database",
        )

        mock_stage_ctx = MagicMock()
        mock_stage_ctx.results = {}
        mock_stage_ctx.plan = MagicMock()

        mock_exec_result = MagicMock()
        mock_exec_result.status = "stage_failed"
        mock_exec_result.replan_eligible = True
        mock_exec_result.failed_stage = failed_stage
        mock_exec_result.failed_validation = None
        mock_exec_result.data_gate_outcome = None
        mock_exec_result.stage_ctx = mock_stage_ctx

        # Make replan return None so we stop after 1 attempt
        mock_adaptive = MagicMock()
        mock_adaptive.replan = AsyncMock(return_value=None)

        mock_context = MagicMock()
        mock_context.user_question = "q"
        mock_context.preferred_provider = None
        mock_context.model = None

        with patch("app.agents.orchestrator.settings") as mock_settings:
            mock_settings.max_pipeline_replans = 2

            _, replan_history = await orch._run_pipeline_replans(
                executor=MagicMock(),
                exec_result=mock_exec_result,
                pipeline_ctx=MagicMock(),
                context=mock_context,
                adaptive=mock_adaptive,
                table_map="",
                db_type=None,
                staleness_warning=None,
                run_id="run-1",
                wf_id="wf-1",
            )

        assert len(replan_history) == 1
        entry = replan_history[0]
        # Must have the tool name, not the stage_id
        assert entry.get("failed_stage_tool") == "query_database", (
            f"expected tool='query_database', got {entry.get('failed_stage_tool')!r}"
        )
        # stage_id should still be present for context
        assert entry.get("failed_stage") == "fetch_rev"

    async def test_extract_pipeline_learnings_passes_tool_not_stage(self) -> None:
        """_extract_pipeline_learnings must pass failed_stage_tool, not stage_id."""
        from app.agents.orchestrator import OrchestratorAgent

        orch = object.__new__(OrchestratorAgent)

        # Build replan_history with both fields
        replan_history = [
            {
                "attempt": 1,
                "failed_stage": "fetch_rev",
                "failed_stage_tool": "query_database",
                "error": "column not found",
            }
        ]

        mock_exec_result = MagicMock()
        mock_exec_result.status = "completed"
        mock_exec_result.data_gate_outcome = None
        mock_exec_result.failed_stage = None

        mock_stage_ctx = MagicMock()
        mock_exec_result.stage_ctx = mock_stage_ctx

        captured_kwargs: list[dict[str, Any]] = []

        async def mock_extract_from_replan(session: Any, conn_id: str, **kwargs: Any) -> None:
            captured_kwargs.append(kwargs)

        mock_extractor = MagicMock()
        mock_extractor.extract_from_replan = mock_extract_from_replan
        mock_extractor.extract_from_data_gate = AsyncMock()
        mock_extractor.extract_from_pipeline_completion = AsyncMock()

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.agents.orchestrator.PipelineLearningExtractor",
                return_value=mock_extractor,
            ),
            patch("app.models.base.async_session_factory", return_value=mock_session),
        ):
            await orch._extract_pipeline_learnings(
                "conn-1",
                exec_result=mock_exec_result,
                replan_history=replan_history,
            )

        assert len(captured_kwargs) == 1
        kw = captured_kwargs[0]
        # Must pass the tool name, not the stage_id
        assert kw.get("failed_stage_tool") == "query_database", (
            f"expected 'query_database', got {kw.get('failed_stage_tool')!r}"
        )
        # Must NOT pass the stage_id as the tool name
        assert kw.get("failed_stage_tool") != "fetch_rev", (
            "failed_stage_tool should be the tool name, not the stage_id"
        )


# ---------------------------------------------------------------------------
# F-SQL-03: one request, one wall clock — the replan count must not multiply it
# ---------------------------------------------------------------------------


class TestReplansShareOneDeadline:
    """ORCH-V02 bounded the retries *inside* one plan and left the plan count
    multiplying that bound.

    ``StageExecutor.execute`` computed ``deadline = monotonic() + budget`` on
    entry, and ``_run_pipeline_replans`` re-entered it once per replan — so the
    worst case was ``(1 + max_pipeline_replans) x pipeline_max_wall_seconds``,
    540 s against a documented 180 s limit, plus planner calls outside all of it.
    """

    @staticmethod
    def _orch() -> Any:
        from app.agents.orchestrator import OrchestratorAgent

        orch = object.__new__(OrchestratorAgent)
        orch._llm = MagicMock()
        orch._tracker = MagicMock()
        orch._tracker.emit = AsyncMock()
        return orch

    async def test_executor_honours_a_deadline_it_is_handed(self) -> None:
        """An already-spent deadline must stop the executor before any stage runs."""
        import time as _time

        from app.agents.stage_context import StageContext

        ex = object.__new__(StageExecutor)
        ex._tracker = MagicMock()
        ex._tracker.emit = AsyncMock()
        plan = ExecutionPlan(
            plan_id="p1",
            question="q",
            stages=[PlanStage(stage_id="s1", description="d", tool="query_database")],
        )
        stage_ctx = StageContext(plan=plan)
        dispatched: list[str] = []

        # The stub records a result the way the real collaborator does. Without that,
        # the stage loop spins forever whenever the deadline check does *not* fire —
        # and a test that hangs under a planted defect reports a CI timeout rather
        # than a failure, which is indistinguishable from an infra flake.
        async def _fake_stage(stage: Any, *a: Any, **k: Any) -> None:
            dispatched.append(stage.stage_id)
            stage_ctx.set_result(
                stage.stage_id, StageResult(stage_id=stage.stage_id, status="completed")
            )

        ex._process_one_stage = _fake_stage

        res = await ex.execute(
            plan, MagicMock(), stage_ctx=stage_ctx, deadline=_time.monotonic() - 1.0
        )

        assert dispatched == [], "a spent deadline must not dispatch a stage"
        assert res is not None

    async def test_replans_forward_the_deadline_they_were_given(self) -> None:
        """Every replan's execute() must carry the request's original deadline."""
        import time as _time

        orch = self._orch()
        request_deadline = _time.monotonic() + 42.0

        first = MagicMock()
        first.status = "stage_failed"
        first.replan_eligible = True
        first.stage_ctx = MagicMock()
        first.stage_ctx.results = {}
        first.data_gate_outcome = None

        after = MagicMock()
        after.status = "completed"
        after.replan_eligible = False

        seen: list[float | None] = []

        async def mock_execute(plan: Any, ctx: Any, **kwargs: Any) -> Any:
            seen.append(kwargs.get("deadline"))
            return after

        executor = MagicMock()
        executor.execute = mock_execute

        new_plan = ExecutionPlan(
            plan_id="p2",
            question="q",
            stages=[PlanStage(stage_id="s2", description="d", tool="query_database")],
        )
        adaptive = MagicMock()
        adaptive.replan = AsyncMock(return_value=new_plan)

        ctx = MagicMock()
        ctx.user_question = "q"
        ctx.preferred_provider = None
        ctx.model = None

        with patch("app.agents.orchestrator.settings") as st:
            st.max_pipeline_replans = 2
            await orch._run_pipeline_replans(
                executor=executor,
                exec_result=first,
                pipeline_ctx=MagicMock(),
                context=ctx,
                adaptive=adaptive,
                table_map="",
                db_type="postgres",
                staleness_warning=None,
                run_id="r",
                wf_id="w",
                deadline=request_deadline,
            )

        assert seen, "the replan must have re-entered the executor"
        assert all(d == request_deadline for d in seen), (
            f"a replan started a fresh budget instead of sharing the request's: {seen}"
        )

    async def test_replans_stop_once_the_shared_deadline_is_spent(self) -> None:
        """A spent request deadline must end the replan loop, not start a new plan."""
        import time as _time

        orch = self._orch()

        first = MagicMock()
        first.status = "stage_failed"
        first.replan_eligible = True
        first.stage_ctx = MagicMock()
        first.stage_ctx.results = {}
        first.data_gate_outcome = None

        executor = MagicMock()
        executor.execute = AsyncMock(side_effect=AssertionError("must not re-execute"))
        adaptive = MagicMock()
        adaptive.replan = AsyncMock(side_effect=AssertionError("must not replan"))

        ctx = MagicMock()
        ctx.user_question = "q"
        ctx.preferred_provider = None
        ctx.model = None

        with patch("app.agents.orchestrator.settings") as st:
            st.max_pipeline_replans = 2
            out, history = await orch._run_pipeline_replans(
                executor=executor,
                exec_result=first,
                pipeline_ctx=MagicMock(),
                context=ctx,
                adaptive=adaptive,
                table_map="",
                db_type="postgres",
                staleness_warning=None,
                run_id="r",
                wf_id="w",
                deadline=_time.monotonic() - 1.0,
            )

        assert out is first
        assert history == []


class TestOneDeadlinePerPipelineEntry:
    """The invariant is about wiring: within one method, the initial
    ``executor.execute(...)`` and the ``_run_pipeline_replans(...)`` that follows it
    must be handed the *same* deadline name.

    Driving ``_run_complex_pipeline`` end to end needs planners, contexts and a DB
    session; asking the question directly of the syntax tree is both cheaper and
    exact. A plant that changed the initial call to ``deadline=None`` walked past
    every behavioural test here, because they enter at the replan loop.
    """

    @staticmethod
    def _deadline_arg(call: Any) -> str | None:
        import ast

        for kw in call.keywords:
            if kw.arg == "deadline":
                return kw.value.id if isinstance(kw.value, ast.Name) else "<not-a-name>"
        return None

    def _pairs(self) -> list[tuple[str, str | None, str | None]]:
        """(enclosing function, execute's deadline, replans' deadline) per call site."""
        import ast
        import inspect

        from app.agents import orchestrator as mod

        tree = ast.parse(inspect.getsource(mod))
        out = []
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            execs, replans = [], []
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                    continue
                if n.func.attr == "execute" and getattr(n.func.value, "id", "") == "executor":
                    execs.append(self._deadline_arg(n))
                elif n.func.attr == "_run_pipeline_replans":
                    replans.append(self._deadline_arg(n))
            for e in execs:
                for r in replans:
                    out.append((fn.name, e, r))
        return out

    def test_every_entry_shares_one_deadline_with_its_replans(self) -> None:
        pairs = self._pairs()
        assert pairs, "found no executor.execute + _run_pipeline_replans pair to check"
        for fn, exec_dl, replan_dl in pairs:
            assert exec_dl is not None, f"{fn}: executor.execute got no deadline"
            assert replan_dl is not None, f"{fn}: _run_pipeline_replans got no deadline"
            assert exec_dl == replan_dl, (
                f"{fn}: the initial execution used `{exec_dl}` while its replans used "
                f"`{replan_dl}` — two budgets for one request is the F-SQL-03 defect"
            )

    def test_every_executor_entry_is_handed_a_deadline(self) -> None:
        """No `executor.execute` may compute its own budget by omission."""
        import ast
        import inspect

        from app.agents import orchestrator as mod

        tree = ast.parse(inspect.getsource(mod))
        missing = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "execute"
            and getattr(n.func.value, "id", "") == "executor"
            and self._deadline_arg(n) is None
        ]
        assert not missing, (
            f"executor.execute at line(s) {missing} passes no deadline, so it starts a "
            "fresh budget — which is how the replan count multiplied the request limit"
        )
