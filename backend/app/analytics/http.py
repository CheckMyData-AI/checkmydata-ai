"""Injectable, retrying HTTP transport for analytics vendor calls (spec §2.2).

Both the transport (``http``) and the delay (``sleep``) are injected: production
passes an aiohttp/urllib adapter and :func:`asyncio.sleep`, tests pass fakes. No
unit test in :mod:`app.analytics` touches the network or the wall clock.

Retry policy (spec §2.1): **only** :class:`~app.analytics.errors.AnalyticsTransientError`
and :class:`~app.analytics.errors.QuotaExhaustedError` are retried. 401/403/404 are
configuration errors — retrying them burns vendor quota and can never succeed.

The transport contract:

* it is called as ``await http(method, url, headers, body)`` (positional, so any
  compatible callable works);
* it returns a :class:`Resp` for *every* HTTP status, including error statuses —
  status classification happens here, in one place;
* it translates network-level failures (DNS, connection reset, timeout) into
  ``AnalyticsTransientError``. Any other exception it raises is treated as a bug
  and propagates unretried rather than being silently swallowed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit

from app.analytics.errors import (
    RETRYABLE_ERRORS,
    AnalyticsAuthError,
    AnalyticsEmpty,
    AnalyticsError,
    AnalyticsPermissionError,
    AnalyticsTransientError,
)

logger = logging.getLogger(__name__)

#: How much of an error body is quoted into the exception message. Enough to
#: diagnose a vendor error, short enough not to dump a payload into the logs.
_BODY_SNIPPET_CHARS = 200


class Resp(NamedTuple):
    """One HTTP response: ``(status, headers, body)``."""

    status: int
    headers: Mapping[str, str]
    body: bytes


#: ``await http(method, url, headers, body)`` -> :class:`Resp`.
HttpFn = Callable[..., Awaitable[Resp]]
#: ``await sleep(delay_seconds)``.
SleepFn = Callable[[float], Awaitable[None]]


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup (vendors are inconsistent about casing)."""
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    """Parse ``Retry-After`` as delta-seconds, or ``None`` when unusable.

    RFC 9110 also allows an HTTP-date. We do not parse that form: rather than
    guess a delay from a clock we do not trust, we fall back to exponential
    backoff. Negative values are clamped to zero.
    """
    raw = _header(headers, "Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    return max(seconds, 0.0)


def _body_snippet(body: bytes) -> str:
    if not body:
        return ""
    text = body[: _BODY_SNIPPET_CHARS * 4].decode("utf-8", errors="replace")
    return " ".join(text.split())[:_BODY_SNIPPET_CHARS]


def _redact_url(url: str) -> str:
    """Drop the query string — some vendors accept API keys as query params."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def classify_response(resp: Resp) -> AnalyticsError | None:
    """Map an HTTP status onto the error taxonomy. ``None`` means success."""
    if 200 <= resp.status < 300:
        return None

    detail = f"HTTP {resp.status}"
    snippet = _body_snippet(resp.body)
    if snippet:
        detail = f"{detail}: {snippet}"

    if resp.status == 401:
        return AnalyticsAuthError(detail)
    if resp.status == 403:
        return AnalyticsPermissionError(detail)
    if resp.status == 404:
        return AnalyticsEmpty(detail)
    if resp.status == 429 or resp.status >= 500:
        return AnalyticsTransientError(detail)
    return AnalyticsError(detail)


async def request_with_retry(
    http: HttpFn,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    body: bytes | None = None,
    attempts: int = 3,
    base_delay: float = 1.0,
    sleep: SleepFn = asyncio.sleep,
) -> Resp:
    """Perform one vendor request, retrying only what is worth retrying.

    Args:
        http: Injected transport, see the module docstring for its contract.
        method: HTTP method, e.g. ``"POST"``.
        url: Absolute request URL.
        headers: Request headers. **Never logged** — they carry the bearer token.
        body: Optional request body.
        attempts: Maximum number of transport calls (``1`` disables retrying).
        base_delay: First backoff delay; delay for attempt *n* is
            ``base_delay * 2**n`` unless the vendor sent ``Retry-After``.
        sleep: Injected delay function.

    Returns:
        The first 2xx :class:`Resp`.

    Raises:
        ValueError: ``attempts`` is below 1.
        AnalyticsAuthError, AnalyticsPermissionError, AnalyticsEmpty,
        AnalyticsError: non-retryable failures, raised on the first occurrence.
        AnalyticsTransientError, QuotaExhaustedError: the last failure after the
            retry budget is spent.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1, got {attempts}")

    last_error: AnalyticsError | None = None
    for attempt in range(attempts):
        retry_after: float | None = None
        try:
            resp = await http(method, url, headers, body)
        except AnalyticsError as exc:
            # The transport already classified this failure (typically a network
            # error mapped to AnalyticsTransientError).
            last_error = exc
        else:
            error = classify_response(resp)
            if error is None:
                return resp
            last_error = error
            retry_after = _retry_after_seconds(resp.headers)

        if not isinstance(last_error, RETRYABLE_ERRORS):
            raise last_error
        if attempt >= attempts - 1:
            break

        delay = retry_after if retry_after is not None else base_delay * 2**attempt
        logger.warning(
            "analytics request failed (attempt %d/%d): %s %s -> %s; retrying in %.2fs",
            attempt + 1,
            attempts,
            method,
            _redact_url(url),
            last_error,
            delay,
        )
        await sleep(delay)

    if last_error is None:  # pragma: no cover - the loop always records an error
        raise AnalyticsTransientError(f"{method} {_redact_url(url)} failed without a result")
    logger.warning(
        "analytics request gave up after %d attempt(s): %s %s -> %s",
        attempts,
        method,
        _redact_url(url),
        last_error,
    )
    raise last_error
