"""Retry policy for analytics vendor calls, and the injectable HTTP transport (spec §2.2).

:func:`retry_async` is the policy; :func:`request_with_retry` is that policy
wrapped around a raw-HTTP call. Both vendor transports in the codebase run on the
single loop in :func:`retry_async` — the raw-HTTP path here and the GA4 client
path in :mod:`app.analytics.ga4.adapter`, which cannot use ``request_with_retry``
because google's own client owns the socket. One policy, one place to change it;
a second hand-rolled loop next to the vendor client is how "429 → retry" ends up
implemented and tested but never actually reached (M3).

Both the transport (``http``) and the delay (``sleep``) are injected: production
passes an aiohttp/urllib adapter and :func:`asyncio.sleep`, tests pass fakes. No
unit test in :mod:`app.analytics` touches the network or the wall clock.

Retry policy (spec §2.1): **only** :class:`~app.analytics.errors.AnalyticsTransientError`
and :class:`~app.analytics.errors.QuotaExhaustedError` are retried. 401/403/404 are
configuration errors — retrying them burns vendor quota and can never succeed.

Every delay is bounded by :data:`MAX_RETRY_DELAY`. ``Retry-After`` is a value a
third party chooses for us, and an unbounded one (``86400``) would hold a
collection job — and its worker slot — for a day.

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

#: Ceiling on any single retry delay, in seconds. ``Retry-After`` is chosen by
#: the vendor, not by us: a hostile or simply generous ``86400`` would otherwise
#: be slept in full, holding a collection job and its worker slot for a day for
#: one period. Exponential backoff is bounded by the same value so a large
#: ``base_delay`` cannot outflank it. One minute is longer than any blip worth
#: waiting out inside a single run — the next scheduled run retries anyway,
#: because a ``failed`` period stays pending in the journal.
MAX_RETRY_DELAY = 60.0


class Resp(NamedTuple):
    """One HTTP response: ``(status, headers, body)``."""

    status: int
    headers: Mapping[str, str]
    body: bytes


#: ``await http(method, url, headers, body)`` -> :class:`Resp`.
HttpFn = Callable[..., Awaitable[Resp]]
#: ``await sleep(delay_seconds)``.
SleepFn = Callable[[float], Awaitable[None]]
#: Reads the vendor's ``Retry-After`` hint for the attempt that just failed, in
#: seconds, or ``None``. Zero-argument because the hint lives wherever the
#: caller's attempt found it (a response header, a vendor exception) — the
#: caller closes over it rather than the policy having to understand transports.
RetryAfterFn = Callable[[], float | None]


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup (vendors are inconsistent about casing)."""
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    """Parse ``Retry-After`` as delta-seconds, or ``None`` when unusable.

    RFC 9110 also allows an HTTP-date. We do not parse that form: rather than
    guess a delay from a clock we do not trust, we fall back to exponential
    backoff. Negative values are clamped to zero; the upper bound is applied by
    the retry loop (:data:`MAX_RETRY_DELAY`), not here, so a caller reading the
    header for its own reasons still sees what the vendor actually said.

    Public because the GA4 adapter reads the same header off a vendor exception.
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


def _bounded_delay(
    hint: float | None, *, base_delay: float, attempt: int, max_delay: float
) -> float:
    """The delay before the next attempt: the vendor's hint, else backoff — bounded."""
    delay = hint if hint is not None else base_delay * 2**attempt
    return max(0.0, min(delay, max_delay))


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = MAX_RETRY_DELAY,
    sleep: SleepFn = asyncio.sleep,
    retry_after: RetryAfterFn | None = None,
    label: str = "analytics request",
) -> T:
    """Run *operation*, retrying only the failures worth retrying (spec §2.1).

    The whole retry policy of the analytics stack lives here: which errors are
    retryable (:data:`~app.analytics.errors.RETRYABLE_ERRORS` — transient and
    quota, nothing else), how long to wait (the vendor's ``Retry-After`` when it
    offered one, otherwise ``base_delay * 2**n``), and the ceiling on that wait
    (:data:`MAX_RETRY_DELAY`). Anything that is not an
    :class:`~app.analytics.errors.AnalyticsError` is a bug rather than weather
    and propagates on the first occurrence, unretried and unwrapped.

    Args:
        operation: A zero-argument coroutine function performing **one** attempt.
            It is called up to *attempts* times, so it must be safe to repeat.
        attempts: Maximum number of attempts (``1`` disables retrying).
        base_delay: First backoff delay; attempt *n* waits ``base_delay * 2**n``.
        max_delay: Ceiling applied to every delay, hint or backoff alike.
        sleep: Injected delay function, so tests never touch the wall clock.
        retry_after: Reads the vendor's hint for the attempt that just failed.
        label: What is being retried, for the log line. Must not contain secrets.

    Returns:
        Whatever the first successful attempt returned.

    Raises:
        ValueError: ``attempts`` is below 1, or ``max_delay`` is negative.
        AnalyticsError: the first non-retryable failure, or the last retryable
            one once the budget is spent — subclass preserved either way.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1, got {attempts}")
    if max_delay < 0:
        raise ValueError(f"max_delay must be >= 0, got {max_delay}")

    last_error: AnalyticsError | None = None
    for attempt in range(attempts):
        try:
            return await operation()
        except AnalyticsError as exc:
            last_error = exc

        if not isinstance(last_error, RETRYABLE_ERRORS):
            raise last_error
        if attempt >= attempts - 1:
            break

        delay = _bounded_delay(
            retry_after() if retry_after is not None else None,
            base_delay=base_delay,
            attempt=attempt,
            max_delay=max_delay,
        )
        logger.warning(
            "analytics request failed (attempt %d/%d): %s -> %s; retrying in %.2fs",
            attempt + 1,
            attempts,
            label,
            last_error,
            delay,
        )
        await sleep(delay)

    if last_error is None:  # pragma: no cover - the loop always records an error
        raise AnalyticsTransientError(f"{label} failed without a result")
    logger.warning(
        "analytics request gave up after %d attempt(s): %s -> %s", attempts, label, last_error
    )
    raise last_error


async def request_with_retry(
    http: HttpFn,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    body: bytes | None = None,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = MAX_RETRY_DELAY,
    sleep: SleepFn = asyncio.sleep,
) -> Resp:
    """Perform one vendor request over the injected transport, with retries.

    A thin shell over :func:`retry_async`: it turns a non-2xx response into the
    typed error the policy understands and hands over the ``Retry-After`` the
    same response carried.

    Args:
        http: Injected transport, see the module docstring for its contract.
        method: HTTP method, e.g. ``"POST"``.
        url: Absolute request URL. Only its scheme/host/path is ever logged.
        headers: Request headers. **Never logged** — they carry the bearer token.
        body: Optional request body.
        attempts: Maximum number of transport calls (``1`` disables retrying).
        base_delay: First backoff delay; delay for attempt *n* is
            ``base_delay * 2**n`` unless the vendor sent ``Retry-After``.
        max_delay: Ceiling on any single delay.
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
    hint: float | None = None

    async def attempt() -> Resp:
        # The hint belongs to the attempt that just failed, so it is cleared
        # first: a transport that raises (a network error it classified itself)
        # must not inherit the previous response's Retry-After.
        nonlocal hint
        hint = None
        resp = await http(method, url, headers, body)
        error = classify_response(resp)
        if error is None:
            return resp
        hint = retry_after_seconds(resp.headers)
        raise error

    return await retry_async(
        attempt,
        attempts=attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        sleep=sleep,
        retry_after=lambda: hint,
        label=f"{method} {_redact_url(url)}",
    )
