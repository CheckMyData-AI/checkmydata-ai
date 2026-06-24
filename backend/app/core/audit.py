"""Structured audit logging for sensitive operations.

Emits a structured logger line (always) AND, when an event loop is running,
persists the event to the durable ``audit_logs`` table via a fire-and-forget
task so the trail survives Heroku dyno restarts and is queryable (F-AUTH-15).
Persistence is best-effort: a DB failure never breaks the request path.
"""

import asyncio
import json
import logging
from typing import Any

audit_logger = logging.getLogger("audit")
logger = logging.getLogger(__name__)


async def _persist_audit(
    action: str,
    user_id: str | None,
    project_id: str | None,
    resource_type: str | None,
    resource_id: str | None,
    detail: str,
    extra: dict[str, Any] | None,
) -> None:
    """Insert one ``AuditLog`` row in a fresh session (best-effort)."""
    try:
        from app.models.audit_log import AuditLog
        from app.models.base import async_session_factory

        async with async_session_factory() as session:
            session.add(
                AuditLog(
                    action=action,
                    user_id=user_id,
                    project_id=project_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    detail=detail or "",
                    extra=json.dumps(extra, default=str) if extra else None,
                )
            )
            await session.commit()
    except Exception:
        logger.warning("audit: failed to persist audit_log row (action=%s)", action, exc_info=True)


def audit_log(
    action: str,
    user_id: str | None = None,
    project_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: str = "",
    **extra: Any,
) -> None:
    """Log a structured audit event for sensitive operations (and persist it)."""
    audit_logger.info(
        "AUDIT action=%s user=%s project=%s resource=%s/%s detail=%s %s",
        action,
        user_id or "system",
        project_id or "-",
        resource_type or "-",
        resource_id or "-",
        detail,
        " ".join(f"{k}={v}" for k, v in extra.items()) if extra else "",
    )

    # Persist to the durable table when a loop is running (request path). Outside a
    # running loop (sync scripts/tests without asyncio) we keep the logger line only.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        from app.core.background import spawn_tracked

        spawn_tracked(
            _persist_audit(
                action, user_id, project_id, resource_type, resource_id, detail, extra or None
            ),
            name=f"audit:{action}",
        )
    except Exception:
        logger.debug("audit: could not schedule persistence", exc_info=True)
