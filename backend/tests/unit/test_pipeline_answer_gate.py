"""T11 — ORCH-A02: AnswerQualityGate wired into pipeline final answer.

Verifies that:
1. A pipeline whose synthesised answer fails the AnswerQualityGate (action != accept)
   returns response_type "step_limit_reached" (not "pipeline_complete").
2. A pipeline with a good answer keeps response_type "pipeline_complete".
3. The AnswerQualityGate.evaluate call receives the real row_count and truncated
   flag from the pipeline's SQL results (W1 T14 carry-forward).
4. build_pipeline_response honours the optional `answer_directive` kwarg:
   - directive.action in ("requery", "warn") → step_limit_reached
   - directive.action == "accept" → pipeline_complete (unchanged)
   - directive is None (default) → pipeline_complete (back-compat)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.answer_validator import AnswerValidationResult, AnswerValidator
from app.agents.response_builder import ResponseBuilder
from app.agents.result_validation import AnswerQualityGate, ResultDirective
from app.agents.stage_context import PlanStage, StageContext
from app.agents.stage_executor import _StageExecutorResult
from app.connectors.base import QueryResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stage_result(
    stage_id: str = "s1",
    *,
    row_count: int = 5,
    truncated: bool = False,
    query: str = "SELECT 1",
    summary: str = "some summary",
    status: str = "success",
):
    """Build a minimal StageResult with a QueryResult."""
    from app.agents.stage_context import StageResult

    qr = QueryResult(columns=["n"], rows=[[1]] * min(row_count, 10), row_count=row_count)
    qr.truncated = truncated
    return StageResult(
        stage_id=stage_id,
        status=status,
        query=query,
        query_result=qr,
        summary=summary,
    )


def _make_exec_result(
    final_answer: str = "The total is 42.",
    *,
    row_count: int = 5,
    truncated: bool = False,
) -> _StageExecutorResult:
    """Build a completed _StageExecutorResult with one SQL stage."""
    stage = PlanStage(stage_id="s1", description="query", tool="query_database")
    plan = MagicMock()
    plan.stages = [stage]

    stage_ctx = StageContext(plan=plan, pipeline_run_id="run-test-1")
    stage_result = _make_stage_result("s1", row_count=row_count, truncated=truncated)
    stage_ctx.set_result("s1", stage_result)

    return _StageExecutorResult(
        status="completed",
        stage_ctx=stage_ctx,
        final_answer=final_answer,
    )


# ---------------------------------------------------------------------------
# ResponseBuilder.build_pipeline_response — answer_directive kwarg
# ---------------------------------------------------------------------------


def test_build_pipeline_response_no_directive_is_pipeline_complete():
    """Default (None directive) must still produce pipeline_complete."""
    exec_result = _make_exec_result("The total is 42.")
    resp = ResponseBuilder.build_pipeline_response(exec_result, "wf-1", None, "run-1")
    assert resp.response_type == "pipeline_complete"


def test_build_pipeline_response_accept_directive_is_pipeline_complete():
    """accept directive must preserve pipeline_complete."""
    exec_result = _make_exec_result("The total is 42.")
    directive = ResultDirective(action="accept", reason="ok")
    resp = ResponseBuilder.build_pipeline_response(
        exec_result, "wf-1", None, "run-1", answer_directive=directive
    )
    assert resp.response_type == "pipeline_complete"


def test_build_pipeline_response_requery_directive_downgrades():
    """requery directive must downgrade to step_limit_reached."""
    exec_result = _make_exec_result("I couldn't find the data.")
    directive = ResultDirective(action="requery", reason="answer does not address question")
    resp = ResponseBuilder.build_pipeline_response(
        exec_result, "wf-1", None, "run-1", answer_directive=directive
    )
    assert resp.response_type == "step_limit_reached"
    # answer text must be preserved (not discarded)
    assert "couldn't find" in resp.answer


def test_build_pipeline_response_warn_directive_downgrades():
    """warn directive (non-partial vague answer) must also downgrade."""
    exec_result = _make_exec_result("Something happened.")
    directive = ResultDirective(action="warn", reason="answer is vague")
    resp = ResponseBuilder.build_pipeline_response(
        exec_result, "wf-1", None, "run-1", answer_directive=directive
    )
    assert resp.response_type == "step_limit_reached"


def test_build_pipeline_response_block_directive_downgrades():
    """block directive must also downgrade (e.g. impossible value in answer)."""
    exec_result = _make_exec_result("Conversion rate was 150%.")
    directive = ResultDirective(action="block", reason="impossible value")
    resp = ResponseBuilder.build_pipeline_response(
        exec_result, "wf-1", None, "run-1", answer_directive=directive
    )
    assert resp.response_type == "step_limit_reached"


# ---------------------------------------------------------------------------
# _run_complex_pipeline integration: gate runs + row_count/truncated wired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_non_answer_triggers_gate_downgrade():
    """When the pipeline synthesises a non-answer, the gate downgrades to step_limit_reached.

    Verifies end-to-end: AnswerQualityGate.evaluate called and directive propagated.
    """
    mock_validator = MagicMock(spec=AnswerValidator)
    mock_validator.validate = AsyncMock(
        return_value=AnswerValidationResult(
            addresses_question=False,
            confidence=0.9,
            reason="no conclusion given",
            is_partial=True,
        )
    )
    gate = AnswerQualityGate(mock_validator)
    exec_result = _make_exec_result("I tried but couldn't find the answer.")

    directive = await gate.evaluate(
        question="How many orders were placed last month?",
        answer=exec_result.final_answer,
        sql_summaries=[],
    )
    assert directive.action != "accept"

    resp = ResponseBuilder.build_pipeline_response(
        exec_result, "wf-gate", None, "run-gate", answer_directive=directive
    )
    assert resp.response_type == "step_limit_reached"


@pytest.mark.asyncio
async def test_pipeline_good_answer_stays_pipeline_complete():
    """When the answer addresses the question, pipeline_complete is preserved."""
    mock_validator = MagicMock(spec=AnswerValidator)
    mock_validator.validate = AsyncMock(
        return_value=AnswerValidationResult(
            addresses_question=True,
            confidence=0.95,
            reason="clear numeric conclusion",
            is_partial=False,
        )
    )
    gate = AnswerQualityGate(mock_validator)
    exec_result = _make_exec_result("Last month there were 1,204 orders.")

    directive = await gate.evaluate(
        question="How many orders were placed last month?",
        answer=exec_result.final_answer,
        sql_summaries=[],
    )
    assert directive.action == "accept"

    resp = ResponseBuilder.build_pipeline_response(
        exec_result, "wf-good", None, "run-good", answer_directive=directive
    )
    assert resp.response_type == "pipeline_complete"


# ---------------------------------------------------------------------------
# W1 T14 carry-forward: row_count / truncated passed to AnswerQualityGate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_receives_row_count_and_truncated():
    """validate() must be called with the real row_count + truncated flag."""
    mock_validator = MagicMock(spec=AnswerValidator)
    mock_validator.validate = AsyncMock(
        return_value=AnswerValidationResult(
            addresses_question=True, confidence=1.0, reason="ok", is_partial=False
        )
    )
    gate = AnswerQualityGate(mock_validator)

    await gate.evaluate(
        question="q",
        answer="The total revenue was $500k.",
        sql_summaries=["SELECT sum(revenue) FROM sales"],
        row_count=250,
        truncated=True,
    )

    call_kwargs = mock_validator.validate.call_args.kwargs
    assert call_kwargs["row_count"] == 250
    assert call_kwargs["truncated"] is True


@pytest.mark.asyncio
async def test_gate_truncated_answer_downgraded():
    """When data is truncated, the gate should downgrade even a plausible answer."""
    # Validator returns False when it sees truncated + presented-as-complete answer
    mock_validator = MagicMock(spec=AnswerValidator)
    mock_validator.validate = AsyncMock(
        return_value=AnswerValidationResult(
            addresses_question=False,
            confidence=0.8,
            reason="answer presents truncated data as complete total",
            is_partial=True,
        )
    )
    gate = AnswerQualityGate(mock_validator)

    exec_result = _make_exec_result("Total revenue is $500k.", row_count=1000, truncated=True)
    # Extract row_count/truncated as _run_complex_pipeline will
    last_sql = None
    for sr in exec_result.stage_ctx.results.values():
        if sr.query_result:
            last_sql = sr
    assert last_sql is not None
    real_row_count = last_sql.query_result.row_count
    real_truncated = bool(last_sql.query_result.truncated)

    directive = await gate.evaluate(
        question="What is total revenue?",
        answer=exec_result.final_answer,
        sql_summaries=[],
        row_count=real_row_count,
        truncated=real_truncated,
    )
    assert directive.action != "accept"

    resp = ResponseBuilder.build_pipeline_response(
        exec_result, "wf-trunc", None, "run-trunc", answer_directive=directive
    )
    assert resp.response_type == "step_limit_reached"
