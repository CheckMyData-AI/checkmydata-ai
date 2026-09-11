"""Five ways the multi-stage pipeline described a run that did not happen.

P1 row 12, the orchestrator half; ORCH-02/04/06/08/09. Each is the pipeline path
disagreeing with the flat loop, or with itself on resume — and the pipeline is the
path a *complex* question takes, so the disagreement lands on the hardest questions.

- **ORCH-02** — a correct zero-row result failed the stage. The same directive is
  an appended warning in the flat loop, and the SQL agent only returns a clean
  0-row result *after* its own ValidationLoop has spent its empty-result retries
  and concluded that zero is the truth. So "how many refunds were there in July?"
  against a month with none burned two planner replans and returned a failed
  pipeline.
- **ORCH-04** — both production call sites overrode the executor's own default and
  built `StageValidator()` with no router, leaving one substring (`"no negative"`)
  as the entire business-rule evaluator — while `_emit_stage_validation` published
  `{"passed": true}` for every rule nobody read.
- **ORCH-06** — the resumed pipeline is a second implementation of the tail and had
  drifted: no freshness warning into any stage prompt, and no answer-quality gate
  on the answer it publishes.
- **ORCH-08** — `execute()` discarded `_synthesize`'s degraded reason and returned
  `completed`, so a failed final synthesis was sealed as `pipeline_complete` with
  `error=None` whenever the plan did not end in a `synthesize` stage — which its
  own planner prompt sanctions.
- **ORCH-09** — the truncation caveat and the answer gate read only the *last*
  stage with rows. A capped SQL stage followed by a fresh GA4 stage therefore
  published the capped total as a complete figure.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from app.agents import orchestrator as orch_mod
from app.agents import response_builder as rb_mod
from app.agents import stage_executor as se_mod


class TestZeroRowsIsAnAnswer:
    """ORCH-02."""

    def test_a_requery_directive_does_not_fail_the_stage(self) -> None:
        source = textwrap.dedent(inspect.getsource(se_mod.StageExecutor._run_sql_stage))
        tree = ast.parse(source.replace("async def", "def", 1))
        # The COMPARISON, not the word: the defect is `in ("block", "requery")`,
        # and a guard looking for the string "requery" anywhere matches the fix
        # and the defect alike.
        error_returns = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Compare)
            and "directive.action" in ast.unparse(node.left)
            and "requery" in ast.unparse(node)
            and "block" in ast.unparse(node)
        ]
        assert not error_returns, (
            "`requery` and `block` share the error return, so a clean zero-row result "
            "becomes status='error', error_category='data_missing' — non-retryable, so "
            "the orchestrator burns its two planner replans and returns a failed "
            "pipeline for a question whose answer was zero. The flat loop appends the "
            f"identical directive as a warning and keeps the answer. Found: {error_returns} "
            "(ORCH-02)"
        )

    def test_it_still_blocks_an_impossible_value(self) -> None:
        source = inspect.getsource(se_mod.StageExecutor._run_sql_stage)
        assert 'directive.action == "block"' in source, (
            "aligning the two paths must not disarm the hard block: DataGate's "
            "impossible-value verdict is the one directive that must never reach a user"
        )


class TestBusinessRulesAreActuallyEvaluated:
    """ORCH-04."""

    def test_neither_production_call_site_drops_the_router(self) -> None:
        tree = ast.parse(inspect.getsource(orch_mod))
        bare = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and ast.unparse(node.func).endswith("StageValidator")
            and not node.args
            and not node.keywords
        ]
        assert not bare, (
            "`StageExecutor.__init__` defaults to `StageValidator(llm_router=llm_router)` "
            "so planner-written business rules get the evaluator the class docstring "
            "describes. Both sites that actually run in production override it with a "
            "bare constructor, leaving one substring ('no negative') as the whole "
            "evaluator — while the stage still publishes {'passed': true, 'errors': []} "
            "on every rule nobody read (ORCH-04)"
        )


class TestAResumedRunGetsTheSameGates:
    """ORCH-06."""

    def test_the_resumed_stages_are_told_how_stale_the_knowledge_is(self) -> None:
        source = textwrap.dedent(inspect.getsource(orch_mod.OrchestratorAgent._execute_resume))
        tree = ast.parse(source.replace("async def", "def", 1))
        executes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("execute")
        ]
        assert executes, "the resumed path no longer calls execute(); this guard is blind"
        assert any(kw.arg == "staleness_warning" for call in executes for kw in call.keywords), (
            "no stage prompt and no synthesis prompt on a resumed run carries the "
            "knowledge-freshness block the fresh path injects, so the resumed stages are "
            "never told the DB index is stale or the clone is behind HEAD (ORCH-06)"
        )

    def test_the_resumed_answer_passes_the_quality_gate(self) -> None:
        source = textwrap.dedent(inspect.getsource(orch_mod.OrchestratorAgent._execute_resume))
        tree = ast.parse(source.replace("async def", "def", 1))
        builds = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and ast.unparse(node.func).endswith("build_pipeline_response")
        ]
        assert builds, "the resumed path no longer builds a pipeline response"
        assert any(kw.arg == "answer_directive" for call in builds for kw in call.keywords), (
            "`answer_directive` defaults to None and the downgrade is guarded on "
            "`is not None`, so AnswerQualityGate never runs on the resumed path: an "
            "answer the gate would have downgraded to 'step_limit_reached' with a "
            "'Continue analysis' CTA is published as pipeline_complete with error=None "
            "— a green seal on an answer the gate refused (ORCH-06)"
        )


class TestAFailedSynthesisIsNotACompletedPipeline:
    """ORCH-08."""

    def test_the_degraded_reason_is_not_discarded(self) -> None:
        """The name `_synthesize`'s second value is bound to must reach the result.

        The first draft asserted `"_degraded_reason" not in source`, which renaming
        the throwaway satisfies while still discarding it — and deleting the keyword
        while keeping the new name passed it, together with the behavioural test
        beside it, because that one constructs the result container directly.
        """
        source = textwrap.dedent(inspect.getsource(se_mod.StageExecutor.execute))
        tree = ast.parse(source.replace("async def", "def", 1))

        bound: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and "_synthesize(" in ast.unparse(node.value):
                target = node.targets[0]
                if isinstance(target, ast.Tuple) and len(target.elts) == 2:
                    bound.append(ast.unparse(target.elts[1]))
        assert bound, "execute() no longer unpacks _synthesize; this guard is blind"

        carried = {
            ast.unparse(kw.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and ast.unparse(node.func).endswith("_StageExecutorResult")
            for kw in node.keywords
            if kw.arg == "degraded_reason"
        }
        assert set(bound) & carried, (
            "`_synthesize` returns (answer, degraded_reason); execute() binds the "
            f"second element to {bound} and hands on {carried or 'nothing'}. The "
            "response is then typed from stage statuses alone, and `degraded` is a "
            "status only `_synthesize_stage` sets — so on a plan ending in "
            "`analyze_results`, which the planner's own prompt sanctions, a failed "
            "final synthesis is sealed as pipeline_complete with error=None (ORCH-08)"
        )

    def test_the_result_container_can_carry_it(self) -> None:
        sig = inspect.signature(se_mod._StageExecutorResult.__init__)
        assert "degraded_reason" in sig.parameters, (
            "`_StageExecutorResult` has no field for it, and ResponseBuilder derives "
            "'degraded' solely by scanning stage results for status == 'degraded' — a "
            "status only `_synthesize_stage` ever sets, and on this path no such stage "
            "result exists"
        )

    def test_the_response_reads_it(self) -> None:
        """The response, not the source text.

        The first draft asserted `"exec_result.degraded_reason" in source`, which a
        `getattr(exec_result, ...)` spelling fails while behaving correctly — and
        which a `getattr(other_thing, "degraded_reason")` would pass while doing
        nothing.
        """
        response = rb_mod.ResponseBuilder.build_pipeline_response(
            _completed_run(degraded_reason="the final synthesis call failed"),
            "wf-1",
            None,
            "run-1",
        )
        assert response.response_type == "pipeline_complete_degraded", (
            "the answer text is honest ('the final synthesis step failed…') and the "
            f"metadata is not: response_type={response.response_type!r}, so every "
            "dashboard built on it under-reports synthesis failures (ORCH-08)"
        )
        assert response.error == "the final synthesis call failed"


class TestTruncationIsAggregatedAcrossStages:
    """ORCH-09."""

    def test_an_earlier_truncated_stage_is_not_overwritten(self) -> None:
        """The published response, from the plan shape the audit names.

        The first draft forbade the `last_sql_result = sr` assignment. That
        assignment is not the defect — it is a correct "last stage with rows",
        and only the caveat and the gate reading it instead of aggregating were
        wrong. A guard on the assignment would have rejected the fix.
        """
        response = rb_mod.ResponseBuilder.build_pipeline_response(
            _completed_run(truncated_first=True), "wf-1", None, "run-1"
        )

        assert "PARTIAL DATA" in response.answer, (
            "plan = capped query_database -> fresh GA4 -> synthesize. "
            "`last_sql_result` ends up as the GA4 stage, so no caveat is appended and "
            "the synthesis' total derived from the capped stage is published as a "
            "complete figure (ORCH-09)"
        )
        assert response.results is not None and response.results.truncated, (
            "the table returned to the UI is the untruncated later stage, so the user "
            "cannot even see which result the caveat is about"
        )

    def test_the_answer_gate_sees_the_truncation_too(self) -> None:
        source = textwrap.dedent(
            inspect.getsource(orch_mod.OrchestratorAgent._evaluate_pipeline_answer)
        )
        tree = ast.parse(source.replace("async def", "def", 1))
        overwrites = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and ast.unparse(node.targets[0]) == "last_truncated"
            and "sr.query_result.truncated" in ast.unparse(node.value)
            and "last_truncated" not in ast.unparse(node.value)
        ]
        assert not overwrites, (
            "the same overwrite one file over: `last_truncated` is reassigned by every "
            "stage with rows before it is handed to AnswerValidator, so a truncated "
            "earlier stage is invisible to the gate as well as to the caveat (ORCH-09)"
        )


# ---------------------------------------------------------------------------
# Fixtures: the plan shape ORCH-09 names — a capped SQL stage, then a fresh one.
# ---------------------------------------------------------------------------


def _completed_run(*, truncated_first: bool = False, degraded_reason: str | None = None):
    from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
    from app.connectors.base import QueryResult

    plan = ExecutionPlan(
        plan_id="p1",
        question="how many orders, and how many sessions?",
        stages=[
            PlanStage(stage_id="s1", tool="query_database", description="capped"),
            PlanStage(stage_id="s2", tool="query_analytics_source", description="fresh"),
        ],
    )
    ctx = StageContext(plan=plan)
    ctx.set_result(
        "s1",
        StageResult(
            stage_id="s1",
            status="success",
            query="SELECT * FROM orders",
            query_result=QueryResult(
                columns=["n"], rows=[[1]], row_count=10_000, truncated=truncated_first
            ),
        ),
    )
    ctx.set_result(
        "s2",
        StageResult(
            stage_id="s2",
            status="success",
            query_result=QueryResult(columns=["sessions"], rows=[[7]], row_count=1),
        ),
    )
    return se_mod._StageExecutorResult(
        status="completed",
        stage_ctx=ctx,
        final_answer="Orders totalled 10,000.",
        degraded_reason=degraded_reason,
    )
