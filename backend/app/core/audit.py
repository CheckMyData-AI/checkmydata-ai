"""Structured audit logging for sensitive operations."""

import logging
from typing import Any

audit_logger = logging.getLogger("audit")


def audit_log(
    action: str,
    user_id: str | None = None,
    project_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: str = "",
    **extra: Any,
) -> None:
    """Log a structured audit event for sensitive operations."""
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
