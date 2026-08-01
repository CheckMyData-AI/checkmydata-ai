"""Inter-agent result validation.

The orchestrator calls these validators *before* returning a sub-agent's
output to the user.  Validators never raise — they return a
``ValidationOutcome`` so the orchestrator can decide how to proceed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.viz.chart_rules import VALID_VIZ_TYPES, apply_chart_rules

if TYPE_CHECKING:
    from app.connectors.base import QueryResult

#: "Does this answer state a figure?" — one digit is enough. Deliberately blunt:
#: the cost of a false positive is one extra caveat, the cost of a false negative
#: is a number presented over data that was never collected.
_MENTIONS_A_NUMBER = re.compile(r"\d")


@dataclass
class ValidationOutcome:
    passed: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fallback_viz_type: str | None = None


class AgentResultValidator:
    """Validates results produced by sub-agents."""

    # ------------------------------------------------------------------
    # SQL result
    # ------------------------------------------------------------------

    def validate_sql_result(self, result: Any) -> ValidationOutcome:
        """Check that an SQL agent result looks reasonable."""
        outcome = ValidationOutcome()

        if getattr(result, "status", "") == "error":
            outcome.passed = False
            outcome.errors.append(result.error or "SQL agent returned an error")
            return outcome

        query = getattr(result, "query", None)
        if not query:
            outcome.passed = False
            outcome.errors.append("SQL agent did not produce a query")
            return outcome

        qr: QueryResult | None = getattr(result, "results", None)
        if qr is None:
            outcome.passed = False
            outcome.errors.append("SQL agent returned no query results object")
            return outcome

        if qr.error:
            outcome.passed = False
            outcome.errors.append(f"Query execution error: {qr.error}")
            return outcome

        if qr.row_count == 0:
            outcome.warnings.append("Query returned zero rows")

        if qr.execution_time_ms > 30_000:
            outcome.warnings.append(
                f"Query took {qr.execution_time_ms:.0f}ms — consider adding filters"
            )

        return outcome

    # ------------------------------------------------------------------
    # Visualization result
    # ------------------------------------------------------------------

    VALID_VIZ_TYPES = VALID_VIZ_TYPES

    def validate_viz_result(
        self,
        result: Any,
        row_count: int = 0,
        column_count: int = 0,
    ) -> ValidationOutcome:
        """Check that a visualisation result is valid for the data shape.

        Delegates to :mod:`app.viz.chart_rules` (T15) so the viz agent and
        the orchestrator validator stay in lockstep.
        """
        outcome = ValidationOutcome()

        viz_type = getattr(result, "viz_type", "table")
        chart_outcome = apply_chart_rules(viz_type, row_count=row_count, column_count=column_count)

        if chart_outcome.invalid_type:
            outcome.passed = False
            outcome.errors.extend(chart_outcome.warnings)
            return outcome

        if chart_outcome.adjusted_viz_type != viz_type:
            outcome.fallback_viz_type = chart_outcome.adjusted_viz_type
        outcome.warnings.extend(chart_outcome.warnings)

        return outcome

    # ------------------------------------------------------------------
    # MCP source result
    # ------------------------------------------------------------------

    def validate_mcp_result(self, result: Any) -> ValidationOutcome:
        outcome = ValidationOutcome()

        if getattr(result, "status", "") in ("error", "no_result"):
            # "no_result" = the MCP agent exhausted its iteration budget without
            # composing an answer. Treat it as a failure, not a usable result —
            # otherwise the iteration-exhausted placeholder is surfaced as data.
            outcome.passed = False
            outcome.errors.append(
                getattr(result, "error", None) or "MCP source agent returned no result"
            )
            return outcome

        answer = getattr(result, "answer", "")
        if not answer:
            outcome.warnings.append("MCP source returned an empty answer")

        return outcome

    # ------------------------------------------------------------------
    # Analytics source result
    # ------------------------------------------------------------------

    def validate_analytics_result(self, result: Any) -> ValidationOutcome:
        """Validate an :class:`~app.agents.analytics_agent.AnalyticsResult`.

        Strictly stronger than :meth:`validate_mcp_result`. It shares the
        error/``no_result`` rejection, and adds the check that only an analytics
        source can make: an answer may not present **numbers** for a window whose
        coverage is incomplete without saying so. A missing period is not a zero,
        and a figure quoted over one is a measurement the system never took.

        The number check reads ``raw_answer`` (the model's own text) rather than
        ``answer`` (model text + the agent's caveats), so the caveat's own dates
        cannot satisfy the check it is being judged by.
        """
        outcome = ValidationOutcome()

        if getattr(result, "status", "") in ("error", "no_result"):
            # "no_result" = the analytics agent exhausted its iteration budget
            # without composing an answer. Never surface the placeholder as data.
            outcome.passed = False
            outcome.errors.append(
                getattr(result, "error", None) or "Analytics agent returned no result"
            )
            return outcome

        answer = getattr(result, "answer", "")
        if not answer:
            outcome.warnings.append("Analytics source returned an empty answer")

        pending = list(getattr(result, "pending_periods", None) or [])
        judged = getattr(result, "raw_answer", "") or answer
        if pending and _MENTIONS_A_NUMBER.search(judged):
            outcome.warnings.append(
                "The answer reports figures for a window that is not fully collected — "
                f"{', '.join(pending[:8])} "
                + ("are" if len(pending) > 1 else "is")
                + " missing or failed, so the totals exclude "
                + ("them" if len(pending) > 1 else "it")
                + "."
            )

        return outcome

    # ------------------------------------------------------------------
    # Knowledge result
    # ------------------------------------------------------------------

    def validate_knowledge_result(self, result: Any) -> ValidationOutcome:
        outcome = ValidationOutcome()

        if getattr(result, "status", "") == "error":
            outcome.passed = False
            outcome.errors.append(result.error or "Knowledge agent returned an error")
            return outcome

        answer = getattr(result, "answer", "")
        if not answer:
            outcome.warnings.append("Knowledge agent returned an empty answer")

        sources = getattr(result, "sources", [])
        if not sources:
            outcome.warnings.append("No source citations in knowledge answer")

        return outcome
