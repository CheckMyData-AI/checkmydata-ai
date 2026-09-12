"""Six ways the orchestrator's bookkeeping disagreed with the run it describes.

P2 row 19; ORCH-01, ORCH-03, ORCH-05, ORCH-07, ORCH-10, ORCH-11.

- **ORCH-01** — `query_analytics_source` is in the planner's prompt, in its
  "CROSS-SOURCE RECIPE", and in the executor's dispatch, and it is not in the plan
  validator's tool set. `_CREATE_PLAN_TOOL`'s enum is literally `list(_VALID_TOOLS)`,
  so the schema does not even offer the name to the model, and a plan that follows
  the prose is rejected twice — once for the tool, once for "at least one
  data-retrieval stage". A shipped, documented capability is unreachable on the
  pipeline path, and the failure mode is a *wrong-scope answer* rather than an error.
  Both halves were already tested; nothing tested the seam.
- **ORCH-03** — the LayerChecker rejects a parallel layer and the replan seeds the
  rejected results straight into the next plan. `layer_checker.py` states the
  requirement it violates verbatim: *"The convergence must depend on this verdict
  rather than on the branches, or the gate has a bypass and the shape is
  decoration."*
- **ORCH-05** — the sweep enumerates stale ids from `_wf_enriched`, which only
  `process_data` ever writes. A workflow that ran `query_database` and nothing else
  never enters it, so its `_wf_sql_results` — full `QueryResult`s, all rows — is
  pinned for the life of the dyno.
- **ORCH-07** — the flat-loop fallback synthesises `route="explore",
  complexity="moderate"` and overwrites the router's real verdict, in the exact field
  a prior fix existed to make honest. Its own docstring claims the opposite.
- **ORCH-10** — a resumed stage's prompt prints `Rows: 5000` beside five restored
  sample rows and never says the set is a sample.
- **ORCH-11** — a connection error re-runs the identical statement with no
  idempotency check. That reasoning holds for SELECT and is stated as such; it does
  not hold for a statement that may have committed before the socket dropped, and
  the repository already has the primitive the SSH path uses for exactly this.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest


class TestThePlannerCanPlanWhatTheExecutorRuns:
    """ORCH-01."""

    def test_every_dispatched_tool_is_a_valid_tool(self) -> None:
        """The seam, not either side of it.

        One existing test asserts the name is in the prompt and another asserts the
        executor dispatches it. Both passed while no plan naming it could survive
        validation.
        """
        from app.agents.query_planner import _VALID_TOOLS
        from app.agents.stage_executor import StageExecutor

        source = textwrap.dedent(inspect.getsource(StageExecutor._execute_stage))
        tree = ast.parse(source.replace("async def", "def", 1))
        dispatched = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith(("query_", "search_", "analyze_", "process_", "synthesize"))
        }
        missing = sorted(dispatched - set(_VALID_TOOLS))
        assert not missing, (
            f"the executor dispatches {missing} and the plan validator refuses it, so "
            "no plan can ever contain it — and `_CREATE_PLAN_TOOL`'s enum is "
            "`list(_VALID_TOOLS)`, so the schema does not even offer the name to the "
            "model (ORCH-01)"
        )

    def test_analytics_counts_as_data_retrieval(self) -> None:
        from app.agents.query_planner import _validate_plan_structure

        stages = [
            {
                "stage_id": "an1",
                "description": "read GA4 sessions",
                "tool": "query_analytics_source",
                "depends_on": [],
            },
            {
                "stage_id": "sy1",
                "description": "answer",
                "tool": "synthesize",
                "depends_on": ["an1"],
            },
        ]
        errors = _validate_plan_structure(stages)
        assert not errors, (
            "an analytics-only plan fails a second check — 'Plan must include at least "
            f"one data-retrieval stage' — because the tool is absent from "
            f"`data_retrieval_tools` too: {errors} (ORCH-01)"
        )


class TestARejectedLayerIsNotSeeded:
    """ORCH-03."""

    def test_the_executor_names_what_its_gate_refused(self) -> None:
        from app.agents.stage_executor import _StageExecutorResult

        sig = inspect.signature(_StageExecutorResult.__init__)
        assert "rejected_stage_ids" in sig.parameters, (
            "the layer gate's failure carries the same `stage_ctx` whose results it "
            "just refused, and the checker never changes their status — so nothing "
            "downstream can tell a rejected sibling from an accepted one (ORCH-03)"
        )

    def test_the_replan_seed_excludes_the_rejected_batch(self) -> None:
        """The decision inside the seeding loop, not one particular spelling of it.

        The first draft demanded that the `if` guarding `set_result` mention the
        rejection — which a `continue` guard at the top of the same loop satisfies
        without matching, so it failed against the correct code.
        """
        from app.agents.orchestrator import OrchestratorAgent

        source = textwrap.dedent(inspect.getsource(OrchestratorAgent._run_pipeline_replans))
        tree = ast.parse(source.replace("async def", "def", 1))
        seeding_loops = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.For) and "set_result" in ast.unparse(node.body)
        ]
        assert seeding_loops, "the replan no longer seeds results; this guard is blind"
        assert any("rejected" in ast.unparse(loop) for loop in seeding_loops), (
            "`_process_one_stage` writes each result into `stage_ctx` BEFORE the "
            "cross-item gate runs on the finished batch, and the failure hands that "
            "same context back — so the replan copies in exactly the siblings the "
            "checker refused, the new plan may depend on them, and they are never "
            "re-run. `layer_checker` states the requirement it violates verbatim "
            "(ORCH-03)"
        )


class TestTheWorkflowCachesAreSwept:
    """ORCH-05."""

    def test_a_workflow_that_never_enriched_is_still_swept(self) -> None:
        from app.agents.orchestrator import OrchestratorAgent

        agent = OrchestratorAgent.__new__(OrchestratorAgent)
        for name in (
            "_wf_enriched",
            "_wf_sql_results",
            "_wf_correction_counts",
            "_wf_suspicious",
            "_wf_routing",
            "_wf_plan",
            "_wf_seen",
        ):
            setattr(agent, name, {})

        # A chat turn that queried the database and never called `process_data` —
        # which is most of them.
        agent._wf_sql_results["wf-1"] = ["a full QueryResult, all rows"]
        agent._wf_correction_counts["wf-1"] = 1
        agent._note_workflow_seen("wf-1")
        # Age the stamp the call just wrote, rather than sweeping at zero seconds —
        # `now - ts` on two `time.time()` reads microseconds apart is a race, not a
        # test.
        agent._wf_seen["wf-1"] -= 10.0

        agent._cleanup_stale_results(stale_seconds=1.0)

        assert not agent._wf_sql_results, (
            "the sweep enumerates stale ids from `_wf_enriched`, and only "
            "`_handle_process_data` ever writes that — so a workflow that queried the "
            "database and nothing else is unreachable by the sweep, and its full row "
            "set is pinned for the life of the dyno, on the memory-constrained "
            "process (ORCH-05)"
        )
        assert not agent._wf_correction_counts

    def test_every_workflow_is_stamped_on_the_way_through(self) -> None:
        """The sweep reading `_wf_seen` proves nothing if nothing writes it.

        The first draft called `_note_workflow_seen` itself, so deleting the call
        from `run()` left the method, the map and this test all intact — and every
        workflow unreachable by the sweep exactly as before.
        """
        from app.agents.orchestrator import OrchestratorAgent

        tree = ast.parse(
            textwrap.dedent(inspect.getsource(OrchestratorAgent.run)).replace("async def", "def", 1)
        )
        stamps = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and "_note_workflow_seen" in ast.unparse(node.func)
        ]
        assert stamps, (
            "nothing records when a workflow was seen, so the sweep has no clock to "
            "read and every per-workflow cache is pinned for the life of the dyno "
            "(ORCH-05)"
        )


class TestTheTraceRecordsTheRealVerdict:
    """ORCH-07."""

    def test_the_continuation_does_not_overwrite_the_routing(self) -> None:
        from app.agents.orchestrator import OrchestratorAgent

        source = textwrap.dedent(inspect.getsource(OrchestratorAgent.run))
        tree = ast.parse(source.replace("async def", "def", 1))
        writes = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and "_wf_routing[" in ast.unparse(node.targets[0])
        ]
        assert writes, "nothing records the routing; this guard is blind"
        guarded = [
            ast.unparse(node.test)
            for node in ast.walk(tree)
            if isinstance(node, ast.If) and "_wf_routing[" in ast.unparse(node.body)
        ]
        # The CONDITION, not merely that one exists: `if True:` is the planted defect
        # and it satisfies "there is an if" perfectly.
        assert any(
            "is_continuation" in condition or "skip_complexity" in condition
            for condition in guarded
        ), (
            "`_fallback_to_unified` re-enters `run()` with `_skip_complexity`, which "
            "synthesises route='explore', complexity='moderate' and overwrites both "
            "`context.extra` and `_wf_routing` — the field a prior fix existed to make "
            "honest, after 222 production traces of 222 read 'unknown'. The docstring "
            "two hundred lines below claims the original complexity is preserved; "
            f"nothing preserves it. Conditions: {guarded} (ORCH-07)"
        )


class TestAResumedSampleSaysItIsASample:
    """ORCH-10."""

    def test_the_prompt_labels_a_restored_sample(self) -> None:
        """The rendered string, not the word "truncated" in the source.

        The first draft matched the source text, which an `if False:` in front of
        the branch satisfies while rendering exactly the misleading line again.
        """
        from app.agents.stage_context import (
            ExecutionPlan,
            PlanStage,
            StageContext,
            StageResult,
        )
        from app.connectors.base import QueryResult

        plan = ExecutionPlan(
            plan_id="p1",
            question="how many orders?",
            stages=[
                PlanStage(stage_id="s1", tool="query_database", description="fetch"),
                PlanStage(
                    stage_id="s2",
                    tool="analyze_results",
                    description="analyse",
                    depends_on=["s1"],
                ),
            ],
        )
        ctx = StageContext(plan=plan)
        ctx.set_result(
            "s1",
            StageResult(
                stage_id="s1",
                status="success",
                query_result=QueryResult(
                    columns=["n"],
                    rows=[[i] for i in range(10)],
                    row_count=5000,
                    truncated=True,
                ),
            ),
        )

        rendered = ctx.build_context_for_stage(plan.stages[1])

        assert "Rows: 5000" not in rendered, (
            "the prompt asserts a row count that no longer exists in memory — ten "
            "rows are held and five thousand are claimed — so the model reasonably "
            f"reasons about a population it cannot see. Rendered:\n{rendered}"
        )
        assert "PARTIAL" in rendered, (
            "`from_summary_dict` restores at most ten rows while keeping the original "
            "`row_count` and marks the result truncated — and the prompt builder never "
            "reads that flag. The string handed to the model asserts a row count that "
            "no longer exists in memory, so it reasons about a population it cannot "
            "see (ORCH-10)"
        )


class TestAReconnectDoesNotRepeatAWrite:
    """ORCH-11."""

    def test_a_transient_retry_checks_idempotency(self) -> None:
        from app.core.validation_loop import ValidationLoop

        source = textwrap.dedent(inspect.getsource(ValidationLoop._try_repair))
        assert "is_read_only_statement" in source or "_is_repeatable" in source, (
            "a CONNECTION_ERROR re-issues the failed query verbatim. That reasoning "
            "holds for SELECT and `error_types.py` states it as such — it does not "
            "hold for a statement that may have committed before the socket dropped. "
            "`UPDATE … SET n = n + 1` runs twice and nobody is told. The repository "
            "already has the primitive: `core.safety.is_read_only_statement`, which "
            "the SSH reconnect path uses for exactly this (ORCH-11)"
        )

    @pytest.mark.asyncio
    async def test_a_write_is_not_re_run_on_a_dropped_connection(self) -> None:
        from app.connectors.base import ConnectionConfig
        from app.core.validation_loop import _is_repeatable_after_connection_loss

        writable = ConnectionConfig(db_type="postgres", is_read_only=False)
        read_only = ConnectionConfig(db_type="postgres", is_read_only=True)

        assert _is_repeatable_after_connection_loss("SELECT 1", writable) is True
        assert (
            _is_repeatable_after_connection_loss("UPDATE orders SET n = n + 1", read_only) is True
        )
        assert (
            _is_repeatable_after_connection_loss("UPDATE orders SET n = n + 1", writable) is False
        ), (
            "the write may have committed before the socket dropped; re-sending it "
            "doubles a non-idempotent statement with nothing said to anybody"
        )
