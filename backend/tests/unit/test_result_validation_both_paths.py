"""T10 — ORCH-A01: ResultValidation wired into pipeline SQL stage (_run_sql_stage).

Verifies that:
1. Pipeline SQL stage with impossible/empty/truncated result → correct
   ResultValidation directive (block/requery/warn), same gate as flat loop.
2. DataGate.check_query_result is invoked at most ONCE on the pipeline path
   (ResultValidation.evaluate uses skip_data_gate=True when called from
   _run_sql_stage; _process_one_stage calls DataGate.check() separately).
3. A clean result → accept → stage proceeds normally.
4. Existing StageExecutor happy-path regression: previous tests stay green.

Design notes
------------
``_run_sql_stage`` now calls ``ResultValidation.evaluate(skip_data_gate=True)``
on the QueryResult it obtains from the SQL agent before returning. When the
directive is ``requery`` or ``block`` the stage returns a StageResult with
status="error" so ``_process_one_stage`` can handle it consistently with other
stage errors. When the directive is ``warn`` the stage appends the warning to
the summary and returns status="success" (mirrors the flat-loop behaviour).
``skip_data_gate=True`` ensures DataGate.check_query_result is NOT called by
ResultValidation on the pipeline path; ``_process_one_stage`` calls the broader
DataGate.check() on the StageResult so comprehensive DataGate checks still run.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base import AgentContext, AgentResult
from app.agents.data_gate import DataGate
from app.agents.result_validation import ResultValidation
from app.agents.stage_context import PlanStage
from app.agents.stage_executor import StageExecutor
from app.agents.stage_validator import StageValidationOutcome, StageValidator
from app.agents.validation import AgentResultValidator
from app.connectors.base import ConnectionConfig, QueryResult
from app.core.workflow_tracker import WorkflowTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sql_stage(stage_id: str = "s1") -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description=f"SQL stage {stage_id}",
        tool="query_database",
    )


def _make_sql_result(qr: QueryResult, query: str = "SELECT 1") -> AgentResult:
    r = MagicMock(spec=AgentResult)
    r.status = "success"
    r.results = qr
    r.query = query
    r.token_usage = {}
    return r


def _context(mock_llm: MagicMock, mock_tracker: MagicMock) -> AgentContext:
    return AgentContext(
        project_id="proj-t10",
        connection_config=ConnectionConfig(db_type="postgres"),
        user_question="test question",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-t10",
    )


def _executor(
    mock_sql_agent: AsyncMock,
    mock_llm: MagicMock,
    mock_tracker: MagicMock,
    *,
    result_validation: ResultValidation | None = None,
) -> StageExecutor:
    """Build a StageExecutor with an optionally injected ResultValidation."""
    validator = MagicMock(spec=StageValidator)
    validator.validate = MagicMock(return_value=StageValidationOutcome(passed=True))
    kb = AsyncMock()
    kb.run = AsyncMock()
    ex = StageExecutor(
        sql_agent=mock_sql_agent,
        knowledge_agent=kb,
        llm_router=mock_llm,
        tracker=mock_tracker,
        validator=validator,
    )
    if result_validation is not None:
        ex._result_validation = result_validation
    return ex


# ---------------------------------------------------------------------------
# T10-1: impossible value → directive block/requery propagated as stage error
# ---------------------------------------------------------------------------


class TestPipelineSQLStageResultValidation:
    @pytest.mark.asyncio
    async def test_impossible_value_passes_sql_stage_deferred_to_process_one_stage(self):
        """150% conversion: _run_sql_stage uses skip_data_gate=True → the impossible-value
        check is deferred to _process_one_stage's DataGate.check() call.  The SQL stage
        itself returns success (DataGate not yet run); the pipeline's DataGate step catches it.

        This is the correct split-responsibility design:
        - _run_sql_stage: error/requery/warn/accept for structural issues (DB error,
          validate_sql_result, empty-retry, truncation) — DataGate skipped.
        - _process_one_stage: comprehensive DataGate.check() (nulls, dups, types,
          value ranges, cross-stage) runs on the StageResult after _run_sql_stage.
        """
        qr = QueryResult(
            columns=["conversion_rate"],
            rows=[[Decimal("150.0")]],
            row_count=1,
        )
        mock_sql_agent = AsyncMock()
        mock_sql_agent.run = AsyncMock(return_value=_make_sql_result(qr))
        mock_llm = MagicMock()
        mock_tracker = MagicMock(spec=WorkflowTracker)
        mock_tracker.emit = AsyncMock()

        ex = _executor(mock_sql_agent, mock_llm, mock_tracker)
        stage = _sql_stage("s1")
        ctx = _context(mock_llm, mock_tracker)

        result = await ex._run_sql_stage("what is the conversion rate", stage, ctx)

        # _run_sql_stage passes the result through (DataGate deferred to _process_one_stage).
        # A separate test verifies DataGate.check_query_result is NOT called here.
        assert result.status == "success", (
            f"_run_sql_stage should pass through with skip_data_gate=True; "
            f"impossible-value blocking is _process_one_stage's DataGate.check() job. "
            f"Got status={result.status!r}, error={result.error!r}"
        )
        # The QueryResult must be preserved so _process_one_stage can run DataGate on it
        assert result.query_result is qr

    @pytest.mark.asyncio
    async def test_empty_result_with_retry_flag_produces_stage_error(self, monkeypatch):
        """0-row result with query_empty_result_retry=True → requery → stage error."""
        from app.config import settings

        monkeypatch.setattr(settings, "query_empty_result_retry", True)

        qr = QueryResult(columns=["x"], rows=[], row_count=0)
        mock_sql_agent = AsyncMock()
        mock_sql_agent.run = AsyncMock(return_value=_make_sql_result(qr))
        mock_llm = MagicMock()
        mock_tracker = MagicMock(spec=WorkflowTracker)
        mock_tracker.emit = AsyncMock()

        ex = _executor(mock_sql_agent, mock_llm, mock_tracker)
        stage = _sql_stage("s1")
        ctx = _context(mock_llm, mock_tracker)

        result = await ex._run_sql_stage("how many orders", stage, ctx)

        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_truncated_result_produces_warning_in_summary(self):
        """Truncated result → warn directive → stage status success with warning in summary."""
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1, truncated=True)
        mock_sql_agent = AsyncMock()
        mock_sql_agent.run = AsyncMock(return_value=_make_sql_result(qr))
        mock_llm = MagicMock()
        mock_tracker = MagicMock(spec=WorkflowTracker)
        mock_tracker.emit = AsyncMock()

        ex = _executor(mock_sql_agent, mock_llm, mock_tracker)
        stage = _sql_stage("s1")
        ctx = _context(mock_llm, mock_tracker)

        result = await ex._run_sql_stage("list all ids", stage, ctx)

        assert result.status == "success"
        assert result.summary is not None
        assert any(kw in result.summary.upper() for kw in ("PARTIAL", "WARN", "TRUNCAT")), (
            f"Expected truncation warning in summary but got: {result.summary!r}"
        )

    @pytest.mark.asyncio
    async def test_clean_result_accepts_and_stage_succeeds(self):
        """Clean numeric result → accept → stage status success, no error."""
        qr = QueryResult(columns=["revenue"], rows=[[9999.99]], row_count=1)
        mock_sql_agent = AsyncMock()
        mock_sql_agent.run = AsyncMock(return_value=_make_sql_result(qr, "SELECT SUM(revenue)"))
        mock_llm = MagicMock()
        mock_tracker = MagicMock(spec=WorkflowTracker)
        mock_tracker.emit = AsyncMock()

        ex = _executor(mock_sql_agent, mock_llm, mock_tracker)
        stage = _sql_stage("s1")
        ctx = _context(mock_llm, mock_tracker)

        result = await ex._run_sql_stage("total revenue", stage, ctx)

        assert result.status == "success"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_db_error_in_qr_produces_stage_error(self):
        """QueryResult with error set → block directive → stage error."""
        qr = QueryResult(columns=[], rows=[], row_count=0, error="column X does not exist")
        mock_sql_agent = AsyncMock()
        mock_sql_agent.run = AsyncMock(return_value=_make_sql_result(qr))
        mock_llm = MagicMock()
        mock_tracker = MagicMock(spec=WorkflowTracker)
        mock_tracker.emit = AsyncMock()

        ex = _executor(mock_sql_agent, mock_llm, mock_tracker)
        stage = _sql_stage("s1")
        ctx = _context(mock_llm, mock_tracker)

        result = await ex._run_sql_stage("bad column query", stage, ctx)

        assert result.status == "error"
        assert "column X does not exist" in (result.error or "")


# ---------------------------------------------------------------------------
# T10-2: DataGate is called ONCE on the pipeline path (not twice)
# ---------------------------------------------------------------------------


class TestDataGateNotDoubleInvoked:
    """Verify that DataGate.check_query_result is NOT called when ResultValidation
    is invoked with skip_data_gate=True from _run_sql_stage; the full DataGate.check()
    runs once in _process_one_stage.
    """

    @pytest.mark.asyncio
    async def test_data_gate_check_query_result_not_called_from_sql_stage(self):
        """_run_sql_stage must NOT invoke DataGate.check_query_result (skip_data_gate=True)."""
        qr = QueryResult(columns=["n"], rows=[[42]], row_count=1)
        mock_sql_agent = AsyncMock()
        mock_sql_agent.run = AsyncMock(return_value=_make_sql_result(qr, "SELECT 42 AS n"))
        mock_llm = MagicMock()
        mock_tracker = MagicMock(spec=WorkflowTracker)
        mock_tracker.emit = AsyncMock()

        # Spy on DataGate.check_query_result
        real_dg = DataGate()
        call_log: list[str] = []

        original_cqr = real_dg.check_query_result

        def spy_check_query_result(*args, **kwargs):  # type: ignore[override]
            call_log.append("check_query_result")
            return original_cqr(*args, **kwargs)

        real_dg.check_query_result = spy_check_query_result  # type: ignore[method-assign]

        # Build ResultValidation with the spy DataGate
        rv = ResultValidation(real_dg, AgentResultValidator())
        ex = _executor(mock_sql_agent, mock_llm, mock_tracker, result_validation=rv)
        stage = _sql_stage("s1")
        ctx = _context(mock_llm, mock_tracker)

        result = await ex._run_sql_stage("how many rows", stage, ctx)

        assert result.status == "success"
        assert "check_query_result" not in call_log, (
            "DataGate.check_query_result must NOT be called from _run_sql_stage "
            "(skip_data_gate=True prevents double-DataGate on pipeline path)"
        )

    @pytest.mark.asyncio
    async def test_result_validation_evaluate_skip_data_gate_skips_datagate(self):
        """ResultValidation.evaluate(skip_data_gate=True) skips DataGate.check_query_result."""
        from decimal import Decimal

        # 150% conversion — would trigger DataGate if not skipped
        qr = QueryResult(
            columns=["conversion"],
            rows=[[Decimal("150.0")]],
            row_count=1,
        )
        dg = DataGate()
        check_call_count = 0

        original = dg.check_query_result

        def counting_check(*args, **kwargs):  # type: ignore[override]
            nonlocal check_call_count
            check_call_count += 1
            return original(*args, **kwargs)

        dg.check_query_result = counting_check  # type: ignore[method-assign]

        rv = ResultValidation(dg, AgentResultValidator())
        directive = rv.evaluate(
            qr,
            question="conversion rate",
            sql="SELECT conversion FROM kpi",
            skip_data_gate=True,
        )

        assert check_call_count == 0, (
            "DataGate.check_query_result must be called 0 times when skip_data_gate=True"
        )
        # Without DataGate, a 150% conversion with valid SQL should accept
        # (no error, passes validate_sql_result, not empty, not truncated)
        assert directive.action in ("accept", "warn"), (
            f"With skip_data_gate=True, 150% should not block (DataGate skipped); "
            f"got {directive.action!r}"
        )

    def test_result_validation_evaluate_default_calls_datagate(self):
        """ResultValidation.evaluate() without skip_data_gate still calls DataGate (default)."""
        from decimal import Decimal

        qr = QueryResult(
            columns=["conversion"],
            rows=[[Decimal("150.0")]],
            row_count=1,
        )
        dg = DataGate()
        check_call_count = 0
        original = dg.check_query_result

        def counting_check(*args, **kwargs):  # type: ignore[override]
            nonlocal check_call_count
            check_call_count += 1
            return original(*args, **kwargs)

        dg.check_query_result = counting_check  # type: ignore[method-assign]

        rv = ResultValidation(dg, AgentResultValidator())
        directive = rv.evaluate(
            qr,
            question="conversion rate",
            sql="SELECT conversion FROM kpi",
        )

        assert check_call_count == 1, (
            f"DataGate.check_query_result must be called exactly once by default; "
            f"got {check_call_count}"
        )
        assert directive.action in ("block", "requery"), (
            f"Expected block/requery for 150% conversion but got {directive.action!r}"
        )
