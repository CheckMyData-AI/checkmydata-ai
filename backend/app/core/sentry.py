"""Sentry initialisation with PII scrubbing (T-OBS-1).

Opt-in: nothing happens unless ``SENTRY_DSN`` is set. The SDK is an optional
dependency — a missing ``sentry-sdk`` package degrades to a logged warning so
local/dev environments without the extra installed keep working.

Privacy posture:

* ``send_default_pii=False`` — no IP addresses, no cookies, no auth headers.
* ``include_local_variables=False`` — frame locals are never captured. They are
  the one channel ``before_send`` cannot clean (it does not walk
  ``stacktrace.frames[].vars``), and this codebase's error paths hold decrypted
  credentials in locals. :class:`app.connectors.base.ConnectionConfig` redacts
  its own ``repr`` as the second half of that defence.
* ``before_send`` strips request bodies, headers, cookies and query strings,
  and redacts obviously sensitive values that leak into exception messages
  (bearer tokens, API keys, passwords in DSN-style URLs).
* Only the user *id* is kept for cross-referencing with audit logs; emails
  and usernames are dropped.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sentry_sdk.scrubber import DEFAULT_DENYLIST

from app.config import settings

logger = logging.getLogger(__name__)

# The patterns and ``scrub_text`` moved to ``app.core.redaction`` so the API-response
# and log paths can use the same set (F-CONN-08). Re-exported here because this module's
# name is what call sites already import.
from app.core.redaction import scrub_text  # noqa: E402

#: Sentry's own scrubber matches KEY NAMES, and its 33-key default list carries
#: ``password``, ``token``, ``api_key``, ``authorization`` and the like — but **not**
#: ``dsn`` or ``database_url`` (measured on ``sentry-sdk`` 2.64.0, 2026-08-26). Those
#: two are precisely the names a connection string ends up under in this codebase.
#:
#: Extended rather than replaced: naming only the additions would drop the 33 keys
#: Sentry already covers, which is a strictly worse position than the default.
EXTRA_DENYLIST: list[str] = [
    *DEFAULT_DENYLIST,
    "dsn",
    "database_url",
    "auth_key",
    "connection_string",
    "ssh_key_content",
    "private_key",
]

__all__ = ["scrub_event", "scrub_text", "init_sentry", "EXTRA_DENYLIST"]


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

    # ``extra`` and ``contexts`` were reached by NEITHER layer: this function did not
    # walk them, and the key-based scrubber's default denylist carries neither ``dsn``
    # nor ``database_url``. ``extra`` is where a developer attaches context by hand,
    # which is exactly where a connection string ends up.
    #
    # Scrub the value rather than drop the key: a redaction that eats the host tells an
    # operator nothing about what failed, and ``scrub_text`` keeps it.
    for container in ("extra", "contexts"):
        value = event.get(container)
        if isinstance(value, dict):
            event[container] = _scrub_nested(value)

    return event


def _scrub_nested(value: Any, _depth: int = 0) -> Any:
    """Recursively scrub strings inside a dict/list, leaving structure intact.

    Depth-bounded because ``contexts`` is attacker-adjacent only in the sense that it
    holds whatever the application put there — and ``before_send`` runs on the error
    path, where a recursion error would lose the event it was called to clean along
    with the crash that produced it.
    """
    if _depth > 6:
        return value
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: _scrub_nested(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_nested(v, _depth + 1) for v in value]
    return value


def init_sentry() -> bool:
    """Initialise the Sentry SDK if a DSN is configured. Returns True on init."""
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.scrubber import EventScrubber
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but sentry-sdk is not installed. "
            "Install with: pip install 'sentry-sdk[fastapi]'"
        )
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment or settings.environment,
        # A Sentry release is only useful when this string is IDENTICAL to the release
        # the commits were attached to. When they drift, issues land on a release with
        # no commits and suspect-commit attribution silently does nothing — which reads
        # as "Sentry is not very good" rather than as a wiring bug. Heroku's slug commit
        # is the one value both sides can agree on without anybody maintaining it.
        #
        # ``None`` when the platform does not supply it. Inventing a release — a version
        # string, a timestamp — produces one that nothing ever attached commits to,
        # which is worse than none because it looks configured.
        release=os.getenv("HEROKU_SLUG_COMMIT") or os.getenv("RELEASE") or None,
        send_default_pii=False,
        # H5: the SDK defaults this to True, which attaches repr()-ed frame
        # locals under exception.values[].stacktrace.frames[].vars — a payload
        # `scrub_event` below never walks. Locals on this codebase's error paths
        # hold decrypted credentials (ConnectionConfig.db_password,
        # .ssh_key_content, and the plaintext service-account JSON in .extra), so
        # capturing them ships secrets to a third party on any crash.
        include_local_variables=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        # scrub_event is typed against plain dicts (so it stays unit-testable
        # without the optional sentry-sdk types); Sentry's Event is a TypedDict
        # that is structurally a dict at runtime.
        # Layer 1 — KEY names. Sentry's own scrubber, with the two names that carry a
        # connection string here added to its 33 defaults. ``recursive`` so a secret
        # nested inside ``extra`` or ``contexts`` is reached by this layer too.
        event_scrubber=EventScrubber(denylist=EXTRA_DENYLIST, recursive=True),
        # Layer 2 — VALUES. The scrubber above never looks inside a string, so a
        # credential embedded in a URL passes it untouched. Both layers, always:
        # `tests/unit/test_sentry_two_layer_scrubbing.py` asserts layer 1 alone still
        # leaks, so if that ever goes red the redundancy question can be re-opened
        # from evidence rather than from memory.
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
