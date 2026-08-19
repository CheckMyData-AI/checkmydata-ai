"""Redaction of secret-looking text, for anywhere a message leaves the process.

Extracted from :mod:`app.core.sentry`, where these patterns lived and were wired to
exactly one egress path. F-CONN-08 / F-LLM-03: Sentry is the path a secret does the
least damage on, because it is already a trusted sink. The two that matter are the
API response a member reads and the application log a platform retains — and both
carried `str(e)` verbatim.

The patterns stay in one place on purpose. A second copy is a copy that drifts, and
the drift is silent: nobody notices a redaction that stopped matching.
"""

from __future__ import annotations

import re

# Secrets that commonly end up inside exception messages, command lines and breadcrumbs.
_SECRET_PATTERNS = [
    # Authorization: Bearer xxx
    re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]{8,}"),
    # token=xxx / api_key: xxx / password=xxx, with either separator
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password|passwd|pwd)\s*[=:]\s*)\S+"),
    # Credentials embedded in a URL: scheme://user:pass@host — the host is kept,
    # because a redaction that eats it tells an operator nothing about what failed.
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


def safe_error(exc: BaseException, *, limit: int = 500) -> str:
    """The text of *exc*, scrubbed and length-capped, fit to hand to a caller.

    Use at every site that puts an exception's own words into an API response, a
    `QueryResult.error`, or a log line. `str(exc)` is not safe to forward: the
    driver's message is usually harmless, but anything that wrapped it with a DSN
    or a command line is not, and the call site cannot tell which it got.
    """
    text = scrub_text(str(exc))
    return text if len(text) <= limit else text[:limit] + "..."
