"""Persist failed/recovered query executions to ``query_failures``.

The ValidationLoop already produces the FULL diagnostic story of a query —
every repair attempt, the classified error type, and the raw DB error — but
historically discarded it after answering the user. This service captures that
story (final failing SQL, full raw error, repair-attempt history) into the
append-only ``QueryFailure`` table so a failure is diagnosable after the fact.

It is **best-effort and off the request path**: every call is wrapped so a
diagnostics-layer fault never propagates into the answer pipeline. The layer is
self-observing — when persistence itself fails it bumps the
``diagnostics_persist_failures`` counter and logs at ERROR rather than swallowing
the fault silently (a recorder that fails invisibly is worse than no recorder).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.core.metrics import record_diagnostics_persist_failure
from app.models.query_failure import QueryFailure

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.query_validation import QueryAttempt

logger = logging.getLogger(__name__)

# Per-attempt query/raw_error cap inside the serialized history. Independent of
# the final ``raw_error`` cap (``diagnostics_raw_error_max_chars``) so a 20-row
# history can't bloat the Text column with 20 full multi-KB error dumps.
_PER_ATTEMPT_FIELD_CAP = 2000


def _cap(text: str | None, limit: int) -> str:
    """Return *text* truncated to *limit* chars (never None, never raises)."""
    if not text:
        return ""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit]


class QueryFailureService:
    """Build and insert a single ``QueryFailure`` row from a repair-attempt list."""

    async def record(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        connection_id: str | None,
        workflow_id: str | None,
        trace_id: str | None,
        session_id: str | None,
        message_id: str | None,
        db_type: str,
        question: str,
        attempts: list[QueryAttempt],
        final_status: str,
    ) -> None:
        """Insert one diagnostic row built from *attempts*.

        ``failed_sql``/``error_type``/``raw_error`` are taken from the last
        attempt that carried an error; if no attempt errored, the last
        attempt's query is used with ``error_type="unknown"``. Up to
        ``diagnostics_attempt_history_max`` attempts are serialized into
        ``attempts_json``; ``attempt_count`` always reflects the full count.
        Commits the session. Callers are expected to wrap this for best-effort
        behaviour (see :func:`maybe_record_query_failure`).
        """
        raw_error_cap = max(0, int(settings.diagnostics_raw_error_max_chars))
        history_max = max(0, int(settings.diagnostics_attempt_history_max))

        # Resolve the representative failing query/error: prefer the last
        # attempt that actually carried an error; otherwise the final attempt.
        errored = [a for a in attempts if a.error is not None]
        if errored:
            primary = errored[-1]
            error_type = primary.error.error_type.value if primary.error else "unknown"
            raw_error = _cap(primary.error.raw_error if primary.error else "", raw_error_cap)
            failed_sql = primary.query or ""
        elif attempts:
            primary = attempts[-1]
            error_type = "unknown"
            raw_error = ""
            failed_sql = primary.query or ""
        else:
            error_type = "unknown"
            raw_error = ""
            failed_sql = ""

        serialized: list[dict[str, Any]] = []
        for attempt in attempts[:history_max]:
            err = attempt.error
            serialized.append(
                {
                    "attempt": attempt.attempt_number,
                    "query": _cap(attempt.query, _PER_ATTEMPT_FIELD_CAP),
                    "error_type": err.error_type.value if err else None,
                    "raw_error": _cap(err.raw_error if err else "", _PER_ATTEMPT_FIELD_CAP),
                    "elapsed_ms": round(float(attempt.elapsed_ms), 1),
                }
            )

        row = QueryFailure(
            project_id=project_id,
            connection_id=connection_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            session_id=session_id,
            message_id=message_id,
            db_type=db_type or "",
            question=question or "",
            failed_sql=failed_sql,
            error_type=error_type,
            raw_error=raw_error,
            attempts_json=json.dumps(serialized),
            attempt_count=len(attempts),
            final_status=final_status,
        )
        session.add(row)
        await session.commit()


def _extract(context: Any, *names: str) -> Any:
    """Return the first present attribute / ``extra`` key from *names*.

    ``session_id``/``message_id`` may live either directly on the context or
    inside its ``extra`` dict; this tolerates both without raising.
    """
    extra = getattr(context, "extra", None)
    extra = extra if isinstance(extra, dict) else {}
    for name in names:
        val = getattr(context, name, None)
        if val:
            return val
        val = extra.get(name)
        if val:
            return val
    return None


async def maybe_record_query_failure(
    *,
    context: Any,
    attempts: list[QueryAttempt],
    loop_success: bool,
    question: str = "",
    trace_id: str | None = None,
) -> None:
    """Best-effort recorder for the SQL-agent execute seam.

    No-ops when diagnostics capture is disabled or when no attempt carried an
    error (we only record genuinely-errored executions — a clean first-shot
    success is not a failure). Opens its own DB session so it never borrows the
    request's transaction, and swallows every error: on any fault it bumps
    ``diagnostics_persist_failures`` and logs at ERROR. MUST NOT raise.
    """
    try:
        if not settings.diagnostics_capture_enabled:
            return
        if not any(a.error is not None for a in attempts):
            return

        connection_config = getattr(context, "connection_config", None)
        connection_id = getattr(connection_config, "connection_id", None)
        db_type = getattr(connection_config, "db_type", "") or ""

        project_id = getattr(context, "project_id", None)
        if not project_id:
            # Without a project there is no FK target — nothing safe to persist.
            return
        workflow_id = getattr(context, "workflow_id", None)
        session_id = _extract(context, "session_id")
        message_id = _extract(context, "message_id")
        resolved_question = question or getattr(context, "user_question", "") or ""
        final_status = "recovered" if loop_success else "failed"

        from app.models.base import async_session_factory

        async with async_session_factory() as session:
            await QueryFailureService().record(
                session,
                project_id=project_id,
                connection_id=connection_id,
                workflow_id=workflow_id,
                trace_id=trace_id,
                session_id=session_id,
                message_id=message_id,
                db_type=db_type,
                question=resolved_question,
                attempts=attempts,
                final_status=final_status,
            )
    except Exception:
        record_diagnostics_persist_failure()
        logger.error("Failed to persist query failure diagnostics", exc_info=True)
