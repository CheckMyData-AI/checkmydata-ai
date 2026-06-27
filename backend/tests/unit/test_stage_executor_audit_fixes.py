"""Audit P1 fixes for StageExecutor:

- _classify_stage_error must NOT default unknown (deterministic) exceptions to
  ``transient`` — that retries un-retryable bugs, burning budget/latency and
  masking root causes. Known-transient infra errors stay retryable.
- process_data source selection must honor the declared ``depends_on`` contract
  and must NOT silently scavenge an unrelated prior stage's dataset.
"""

from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock

from app.agents.base import AgentContext
from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
from app.agents.stage_executor import StageExecutor, _classify_stage_error
from app.agents.validation import AgentResultValidator
from app.connectors.base import ConnectionConfig, QueryResult


class TestClassifyStageError:
    def test_unknown_deterministic_exception_is_not_retryable(self):
        # KeyError/TypeError/ValueError are deterministic bugs — retrying is
        # pointless. They must classify non-retryable (configuration), not
        # transient.
        for exc in (KeyError("col"), TypeError("bad"), ValueError("nope"), AttributeError("x")):
            assert _classify_stage_error(exc) == "configuration", exc

    def test_infra_errors_stay_transient(self):
        # Genuine infra blips remain retryable (all OSError subclasses).
        assert _classify_stage_error(TimeoutError("slow")) == "transient"
        assert _classify_stage_error(ConnectionError("reset")) == "transient"
        assert _classify_stage_error(ConnectionResetError("reset")) == "transient"
        assert _classify_stage_error(OSError("network unreachable")) == "transient"
        import socket

        assert _classify_stage_error(socket.gaierror("dns")) == "transient"


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


def _mcp_executor(mcp_source) -> StageExecutor:
    return StageExecutor(
        sql_agent=MagicMock(),
        knowledge_agent=MagicMock(),
        llm_router=MagicMock(),
        tracker=MagicMock(),
        mcp_source_agent=mcp_source,
    )


def _ctx() -> AgentContext:
    return AgentContext(
        project_id="p",
        connection_config=ConnectionConfig(db_type="postgres"),
        user_question="q",
        chat_history=[],
        llm_router=MagicMock(),
        tracker=MagicMock(),
        workflow_id="wf",
    )


class TestMcpStageNoResult:
    """MUST-FIX: an MCP agent that exhausts its iteration budget returns
    status="no_result"; the stage must treat that as a (data_missing) failure,
    NOT map it to success and surface the placeholder string as a real answer.
    """

    async def test_no_result_becomes_stage_error(self):
        mcp = MagicMock()
        mcp.run = AsyncMock(
            return_value=types.SimpleNamespace(
                answer="Reached maximum iterations for MCP tool calls.",
                status="no_result",
                token_usage={},
                error=None,
            )
        )
        stage = PlanStage(stage_id="m", description="mcp", tool="query_mcp_source")
        res = await _mcp_executor(mcp)._run_mcp_stage("q", stage, _ctx())
        assert res.status == "error"
        assert res.error_category == "data_missing"

    async def test_success_still_succeeds(self):
        mcp = MagicMock()
        mcp.run = AsyncMock(
            return_value=types.SimpleNamespace(
                answer="real answer", status="success", token_usage={}, error=None
            )
        )
        stage = PlanStage(stage_id="m", description="mcp", tool="query_mcp_source")
        res = await _mcp_executor(mcp)._run_mcp_stage("q", stage, _ctx())
        assert res.status == "success"
        assert res.summary == "real answer"

    def test_validate_mcp_result_fails_on_no_result(self):
        out = AgentResultValidator().validate_mcp_result(
            types.SimpleNamespace(status="no_result", answer="placeholder", error=None)
        )
        assert out.passed is False
