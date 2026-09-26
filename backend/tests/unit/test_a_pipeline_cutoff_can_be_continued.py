"""B-27 D2 (SCN-055): "Continue analysis" after a pipeline-path cutoff.

Only the flat tool loop built `continuation_context`. A multi-stage answer downgraded
to `step_limit_reached` carried none, and the continuation prompt still said "Do NOT
re-execute these queries — use the results below" with nothing below — so the agent
was told to reuse results it was never given, and started over.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from app.agents.orchestrator import OrchestratorAgent
from app.agents.response_builder import ResponseBuilder
from app.agents.result_validation import ResultDirective
from app.agents.stage_context import PlanStage, StageContext, StageResult
from app.agents.stage_executor import _StageExecutorResult
from app.connectors.base import QueryResult
from app.core.agent import AgentContext


def _exec_result() -> _StageExecutorResult:
    stages = [
        PlanStage(stage_id="s1", description="Monthly revenue", tool="query_database"),
        PlanStage(stage_id="s2", description="Refunds by month", tool="query_database"),
    ]
    plan = MagicMock()
    plan.stages = stages
    ctx = StageContext(plan=plan, pipeline_run_id="run-1")
    ctx.set_result(
        "s1",
        StageResult(
            stage_id="s1",
            query="SELECT month, SUM(amount) FROM orders GROUP BY 1",
            query_result=QueryResult(
                columns=["month", "revenue"], rows=[["2026-08", 10], ["2026-09", 12]], row_count=2
            ),
            summary="Revenue by month",
        ),
    )
    return _StageExecutorResult(status="completed", stage_ctx=ctx, final_answer="Revenue grew.")


def test_a_downgraded_pipeline_answer_carries_what_it_computed() -> None:
    resp = ResponseBuilder.build_pipeline_response(
        _exec_result(),
        "wf-1",
        None,
        "run-1",
        answer_directive=ResultDirective(action="warn", reason="vague"),
    )
    assert resp.response_type == "step_limit_reached"
    assert resp.continuation_context, "a continuable answer with no context to continue from"
    payload = json.loads(resp.continuation_context)
    (q,) = payload["sql_queries"]
    assert "SUM(amount)" in q["query"]
    assert q["row_count"] == 2 and q["columns"] == ["month", "revenue"]
    assert payload["partial_answer"].startswith("Revenue grew.")
    assert payload["steps_used"] == 1 and payload["steps_total"] == 2


def test_a_clean_pipeline_answer_carries_none() -> None:
    resp = ResponseBuilder.build_pipeline_response(_exec_result(), "wf-1", None, "run-1")
    assert resp.response_type == "pipeline_complete"
    assert resp.continuation_context is None


def _continued(raw: str) -> str:
    ctx = MagicMock(spec=AgentContext)
    ctx.extra = {"continuation_context": raw, "pipeline_action": "continue_analysis"}
    OrchestratorAgent._apply_continuation_context(ctx)
    return ctx.extra["_continuation_summary"]


def test_the_prompt_does_not_promise_results_it_does_not_have() -> None:
    summary = _continued("")
    assert "use the results below" not in summary
    assert "no intermediate results" in summary


def test_the_prompt_still_reuses_results_when_it_has_them() -> None:
    resp = ResponseBuilder.build_pipeline_response(
        _exec_result(),
        "wf-1",
        None,
        "run-1",
        answer_directive=ResultDirective(action="warn", reason="vague"),
    )
    summary = _continued(resp.continuation_context)
    assert "Do NOT re-execute these queries" in summary
    assert "SUM(amount)" in summary
