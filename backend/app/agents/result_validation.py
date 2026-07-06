"""Unified post-result validation façade (contracts C-B / C-C).

Composes the existing quality nets so BOTH execution paths (flat loop and
multi-stage pipeline) can share one gate. W0 builds + tests the module; the
A01/A02 call-site wiring is Wave 3. See the intelligence-remediation spec §2.

Decision table for :meth:`ResultValidation.evaluate`:

1. ``qr.error`` is set        → **block**   (DB-level error, non-retryable)
2. ``validate_sql_result`` fails → **requery** (hints = gate error messages)
3. zero rows + ``query_empty_result_retry`` flag → **requery**
4. ``qr.truncated`` or ``truncated`` kwarg  → **warn**  (partial data)
5. :class:`DataGate` hard-checks (impossible values) → **block**
6. otherwise                  → **accept**

:class:`DataGate` is invoked in branch 5 (not held for W3); the
:attr:`reconcile` callable is available for multi-result cross-checking at
the call-site level.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.agents.answer_validator import AnswerValidator
from app.agents.data_gate import DataGate
from app.agents.sql_result_reconciliation import sql_results_reconcile
from app.agents.validation import AgentResultValidator
from app.config import settings
from app.connectors.base import QueryResult
from app.core.metrics import get_metrics_collector


@dataclass
class ResultDirective:
    """Structured verdict from a result-validation gate.

    Attributes:
        action:  One of ``"accept"``, ``"warn"``, ``"requery"``, ``"block"``.
        reason:  Human-readable explanation surfaced to the orchestrator.
        hints:   Optional list of repair hints for the retry planner.
    """

    action: Literal["accept", "warn", "requery", "block"]
    reason: str
    hints: list[str] = field(default_factory=list)


@dataclass
class _ResultShim:
    """Adapts a bare ``QueryResult`` to the ``results``/``query`` shape that
    :meth:`AgentResultValidator.validate_sql_result` expects.

    The validator reads ``getattr(result, "status", "")`` (defaults to ``""``),
    ``getattr(result, "query", None)`` (must be truthy to pass),
    ``getattr(result, "results", None)`` (the ``QueryResult``), plus
    ``qr.error`` / ``qr.row_count`` / ``qr.execution_time_ms`` from the nested
    ``QueryResult``.  This shim supplies ``results`` and ``query``; the rest
    resolve via ``getattr`` defaults.
    """

    results: QueryResult
    query: str


class ResultValidation:
    """Synchronous per-result validation façade (contract C-B).

    Holds references to :class:`~app.agents.data_gate.DataGate` (for W3
    stage-level checks) and the :attr:`reconcile` callable (for multi-result
    cross-checking at the call-site).  The core ``evaluate`` method is
    intentionally synchronous — both ``DataGate`` and
    :class:`~app.agents.validation.AgentResultValidator` are sync.
    """

    def __init__(
        self,
        data_gate: DataGate,
        result_gate: AgentResultValidator,
        *,
        reconcile: Callable[[Sequence[Any]], bool] = sql_results_reconcile,
    ) -> None:
        self._data_gate = data_gate
        self._result_gate = result_gate
        self._reconcile = reconcile

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        qr: QueryResult,
        *,
        question: str,
        sql: str,
        truncated: bool | None = None,
        skip_data_gate: bool = False,
    ) -> ResultDirective:
        """Evaluate a single ``QueryResult`` and return a :class:`ResultDirective`.

        Parameters:
            qr:             The ``QueryResult`` returned by a connector.
            question:       The original user question (for future context).
            sql:            The SQL that produced *qr* (passed to the result gate).
            truncated:      Caller-supplied truncation flag; OR-ed with
                            ``qr.truncated`` so either source suffices.
            skip_data_gate: When ``True``, branch 5 (:class:`DataGate`
                            hard-checks) is skipped.  Set by the pipeline SQL
                            stage (``StageExecutor._run_sql_stage``) to avoid
                            double-invocation: ``_process_one_stage`` already
                            calls ``DataGate.check()`` on the full
                            ``StageResult`` after this gate returns.

        Returns:
            A :class:`ResultDirective` with ``action`` in
            ``{"accept", "warn", "requery", "block"}``.
        """
        # 1. DB-level error — always block; retrying the same SQL won't help
        #    without a replan.
        if qr.error:
            return ResultDirective(
                action="block",
                reason=qr.error,
                hints=["Check the SQL syntax and the connection's schema."],
            )

        # 2. Result-quality gate — a failed shim check means the result is
        #    structurally invalid and a fresh query with corrections should
        #    be attempted.
        shim = _ResultShim(results=qr, query=sql)
        outcome = self._result_gate.validate_sql_result(shim)
        if not outcome.passed:
            return ResultDirective(
                action="requery",
                reason="; ".join(outcome.errors) or "the result failed validation",
                hints=list(outcome.errors),
            )

        # 3. Empty result — if the retry flag is on, ask for a replan.
        if settings.query_empty_result_retry and qr.row_count == 0:
            return ResultDirective(
                action="requery",
                reason="query returned 0 rows",
                hints=["Verify table/column names and filter values against the schema."],
            )

        # 4. Truncated data — not an error, but callers should note the
        #    incompleteness in their answer.
        if qr.truncated or bool(truncated):
            return ResultDirective(
                action="warn",
                reason=(
                    f"PARTIAL DATA: query capped at {qr.row_count} rows — totals are incomplete."
                ),
                hints=["Push aggregation into SQL (GROUP BY / aggregate functions)."],
            )

        # 5. DataGate value-range hard-checks — catch impossible values
        #    (150% conversion, negative counts) that the structural gate above
        #    doesn't cover.  Runs only when hard checks are enabled (config
        #    data_gate_hard_checks_enabled=True, the default).
        #    Skipped when ``skip_data_gate=True`` (pipeline path) because
        #    ``_process_one_stage`` already runs ``DataGate.check()`` on the
        #    full ``StageResult`` — invoking it here too would double-fire.
        if skip_data_gate:
            return ResultDirective(action="accept", reason="ok", hints=[])

        dg_outcome = self._data_gate.check_query_result(qr, question=question)
        if not dg_outcome.passed:
            try:
                get_metrics_collector().inc("datagate_block_total", check="value_range")
            except Exception:
                pass
            return ResultDirective(
                action="block",
                reason=dg_outcome.error_summary or "impossible data value detected",
                hints=list(dg_outcome.suggestions),
            )

        # 6. All checks passed.
        return ResultDirective(action="accept", reason="ok", hints=[])


class AnswerQualityGate:
    """Async façade mapping :class:`~app.agents.answer_validator.AnswerValidator`
    verdicts onto :class:`ResultDirective` actions (contract C-C).

    Decision table:

    * ``addresses_question=True``                       → ``accept``
    * ``addresses_question=False`` and ``is_partial``   → ``requery``
    * ``addresses_question=False`` and not ``is_partial`` → ``warn``
    """

    def __init__(self, validator: AnswerValidator) -> None:
        self._validator = validator

    async def evaluate(
        self,
        *,
        question: str,
        answer: str,
        sql_summaries: list[str] | None = None,
        row_count: int | None = None,
        truncated: bool = False,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> ResultDirective:
        """Validate *answer* against *question* and return a :class:`ResultDirective`.

        All keyword arguments are forwarded verbatim to
        :meth:`~app.agents.answer_validator.AnswerValidator.validate`.

        Parameters:
            row_count:   Row count from the pipeline's last SQL result.  Forwarded
                         to ``AnswerValidator.validate`` so the LLM prompt can flag
                         answers that present truncated data as a complete total.
            truncated:   Truncation flag from the pipeline's last SQL result.
                         OR-ed with ``qr.truncated`` inside the validator prompt.
        """
        verdict = await self._validator.validate(
            question=question,
            answer=answer,
            sql_summaries=sql_summaries,
            row_count=row_count,
            truncated=truncated,
            preferred_provider=preferred_provider,
            model=model,
        )

        if verdict.addresses_question:
            return ResultDirective(
                action="accept",
                reason=verdict.reason or "ok",
                hints=[],
            )

        action: Literal["requery", "warn"] = "requery" if verdict.is_partial else "warn"
        return ResultDirective(
            action=action,
            reason=verdict.reason or "answer does not address the question",
            hints=[],
        )
