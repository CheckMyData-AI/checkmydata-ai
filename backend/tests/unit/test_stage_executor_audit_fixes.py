"""Audit P1 fixes for StageExecutor:

- _classify_stage_error must NOT default unknown (deterministic) exceptions to
  ``transient`` — that retries un-retryable bugs, burning budget/latency and
  masking root causes. Known-transient infra errors stay retryable.
- process_data source selection must honor the declared ``depends_on`` contract
  and must NOT silently scavenge an unrelated prior stage's dataset.
"""

from __future__ import annotations

from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
from app.agents.stage_executor import StageExecutor, _classify_stage_error
from app.connectors.base import QueryResult


class TestClassifyStageError:
    def test_unknown_deterministic_exception_is_not_retryable(self):
        # KeyError/TypeError/ValueError are deterministic bugs — retrying is
        # pointless. They must classify non-retryable (configuration), not
        # transient.
        for exc in (KeyError("col"), TypeError("bad"), ValueError("nope"), AttributeError("x")):
            assert _classify_stage_error(exc) == "configuration", exc

    def test_timeout_and_connection_errors_stay_transient(self):
        # Genuine infra blips remain retryable.
        assert _classify_stage_error(TimeoutError("slow")) == "transient"
        assert _classify_stage_error(ConnectionError("reset")) == "transient"
        assert _classify_stage_error(ConnectionResetError("reset")) == "transient"


def _qr(rows: list[list]) -> QueryResult:
    return QueryResult(columns=["x"], rows=rows, row_count=len(rows))


def _process_stage(stage_id: str, depends_on: list[str]) -> PlanStage:
    return PlanStage(
        stage_id=stage_id, description="proc", tool="process_data", depends_on=depends_on
    )


def _ctx_with(stages: list[PlanStage], results: dict[str, StageResult]) -> StageContext:
    plan = ExecutionPlan(plan_id="p", question="q", stages=stages)
    ctx = StageContext(plan=plan)
    for sid, res in results.items():
        ctx.set_result(sid, res)
    return ctx


class TestProcessDataSourceSelection:
    def test_declared_dep_empty_does_not_scavenge_unrelated_stage(self):
        # s0 (unrelated) has rows; s1 (the declared dep) is empty. The
        # process_data stage p depends ONLY on s1. It must NOT pick up s0's
        # data — it must signal "no source" so the orchestrator can replan.
        s0 = PlanStage(stage_id="s0", description="other", tool="query_database")
        s1 = PlanStage(stage_id="s1", description="dep", tool="query_database")
        p = _process_stage("p", depends_on=["s1"])
        ctx = _ctx_with(
            [s0, s1, p],
            {
                "s0": StageResult(stage_id="s0", status="success", query_result=_qr([[1], [2]])),
                "s1": StageResult(stage_id="s1", status="success", query_result=_qr([])),
            },
        )
        assert StageExecutor._select_process_data_source(p, ctx) is None

    def test_declared_dep_with_rows_is_used(self):
        s1 = PlanStage(stage_id="s1", description="dep", tool="query_database")
        p = _process_stage("p", depends_on=["s1"])
        src_qr = _qr([[7]])
        ctx = _ctx_with(
            [s1, p],
            {"s1": StageResult(stage_id="s1", status="success", query_result=src_qr)},
        )
        assert StageExecutor._select_process_data_source(p, ctx) is src_qr

    def test_no_declared_deps_falls_back_to_recent_prior(self):
        # Regression guard: a process_data stage with empty depends_on may
        # still fall back to the most recent prior stage with rows.
        s0 = PlanStage(stage_id="s0", description="other", tool="query_database")
        p = _process_stage("p", depends_on=[])
        prior_qr = _qr([[9]])
        ctx = _ctx_with(
            [s0, p],
            {"s0": StageResult(stage_id="s0", status="success", query_result=prior_qr)},
        )
        assert StageExecutor._select_process_data_source(p, ctx) is prior_qr
