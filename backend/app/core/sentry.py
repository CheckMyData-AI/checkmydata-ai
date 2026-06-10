"""Sentry initialisation with PII scrubbing (T-OBS-1).

Opt-in: nothing happens unless ``SENTRY_DSN`` is set. The SDK is an optional
dependency — a missing ``sentry-sdk`` package degrades to a logged warning so
local/dev environments without the extra installed keep working.

Privacy posture:

* ``send_default_pii=False`` — no IP addresses, no cookies, no auth headers.
* ``before_send`` strips request bodies, headers, cookies and query strings,
  and redacts obviously sensitive values that leak into exception messages
  (bearer tokens, API keys, passwords in DSN-style URLs).
* Only the user *id* is kept for cross-referencing with audit logs; emails
  and usernames are dropped.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Patterns for secrets that commonly leak into exception messages / breadcrumbs.
_SECRET_PATTERNS = [
    # Authorization: Bearer xxx / token=xxx / api_key=xxx
    re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password|passwd|pwd)\s*[=:]\s*)\S+"),
    # Credentials embedded in URLs: scheme://user:pass@host
    re.compile(r"(://[^/:@\s]+:)[^@\s]+(@)"),
]

_REDACTED = "[redacted]"


def scrub_text(value: str) -> str:
    """Redact secret-looking substrings from free-form text."""
    out = value
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 2:
            out = pat.sub(rf"\1{_REDACTED}\2", out)
        else:
            out = pat.sub(rf"\1{_REDACTED}", out)
    return out


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """``before_send`` hook: drop request payloads/headers and redact secrets."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        request.pop("headers", None)
        request.pop("query_string", None)
        request.pop("env", None)

    user = event.get("user")
    if isinstance(user, dict):
        # Keep only the opaque id for audit-log correlation.
        event["user"] = {"id": user.get("id")} if user.get("id") else {}

    # Exception values and log messages can embed connection strings etc.
    for exc in (event.get("exception") or {}).get("values") or []:
        if isinstance(exc, dict) and isinstance(exc.get("value"), str):
            exc["value"] = scrub_text(exc["value"])
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        for key in ("message", "formatted"):
            if isinstance(logentry.get(key), str):
                logentry[key] = scrub_text(logentry[key])

    for crumb in (event.get("breadcrumbs") or {}).get("values") or []:
        if isinstance(crumb, dict) and isinstance(crumb.get("message"), str):
            crumb["message"] = scrub_text(crumb["message"])
        if isinstance(crumb, dict):
            crumb.pop("data", None)

    return event


def init_sentry() -> bool:
    """Initialise the Sentry SDK if a DSN is configured. Returns True on init."""
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but sentry-sdk is not installed. "
            "Install with: pip install 'sentry-sdk[fastapi]'"
        )
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment or settings.environment,
        send_default_pii=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        # scrub_event is typed against plain dicts (so it stays unit-testable
        # without the optional sentry-sdk types); Sentry's Event is a TypedDict
        # that is structurally a dict at runtime.
        before_send=scrub_event,  # type: ignore[arg-type]
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
    )
    logger.info(
        "Sentry initialised (environment=%s, traces_sample_rate=%s)",
        settings.sentry_environment or settings.environment,
        settings.sentry_traces_sample_rate,
    )
    return True
