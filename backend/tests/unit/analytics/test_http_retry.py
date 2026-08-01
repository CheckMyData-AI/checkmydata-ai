"""Unit tests for the injectable retrying transport (spec §2.1 + §2.2).

Nothing here touches the network or the wall clock: both the transport (``http``)
and the delay (``sleep``) are injected fakes, so every assertion is about
behaviour — which errors are raised, how many times the transport was called, and
exactly what delays were requested.

The rule under test: **retry only ``AnalyticsTransientError`` and
``QuotaExhaustedError``.** 401/403/404 are configuration errors — retrying them
burns vendor quota and can never succeed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

import pytest

from app.analytics.errors import (
    RETRYABLE_ERRORS,
    AnalyticsAuthError,
    AnalyticsEmpty,
    AnalyticsError,
    AnalyticsPermissionError,
    AnalyticsTransientError,
    QuotaExhaustedError,
)
from app.analytics.http import Resp, request_with_retry

URL = "https://analyticsdata.googleapis.com/v1beta/properties/294380179:runReport"


class FakeHttp:
    """Transport fake: replays a scripted list of responses/exceptions."""

    def __init__(self, script: Sequence[Resp | Exception]) -> None:
        self._script = list(script)
        self.calls: list[tuple[str, str, Mapping[str, str], bytes | None]] = []

    async def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> Resp:
        self.calls.append((method, url, dict(headers), body))
        if not self._script:
            raise AssertionError("transport called more times than the script allows")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def call_count(self) -> int:
        return len(self.calls)


class FakeSleep:
    """Records the delays asked for instead of actually waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def _resp(status: int, headers: dict[str, str] | None = None, body: bytes = b"") -> Resp:
    return Resp(status=status, headers=headers or {}, body=body)


async def _call(http: FakeHttp, sleep: FakeSleep, **kwargs: object) -> Resp:
    return await request_with_retry(
        http,
        "POST",
        URL,
        headers={"Authorization": "Bearer token"},
        body=b"{}",
        sleep=sleep,
        **kwargs,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# Taxonomy                                                                     #
# --------------------------------------------------------------------------- #


def test_retryable_errors_are_exactly_transient_and_quota() -> None:
    assert set(RETRYABLE_ERRORS) == {AnalyticsTransientError, QuotaExhaustedError}
    assert all(issubclass(cls, AnalyticsError) for cls in RETRYABLE_ERRORS)
    for configuration_error in (AnalyticsAuthError, AnalyticsPermissionError, AnalyticsEmpty):
        assert not issubclass(configuration_error, RETRYABLE_ERRORS)


# --------------------------------------------------------------------------- #
# Success paths                                                                #
# --------------------------------------------------------------------------- #


async def test_success_returns_the_response_without_sleeping() -> None:
    http = FakeHttp([_resp(200, body=b'{"rows": []}')])
    sleep = FakeSleep()

    resp = await _call(http, sleep)

    assert resp.status == 200
    assert resp.body == b'{"rows": []}'
    assert http.call_count == 1
    assert sleep.delays == []


async def test_transport_receives_method_url_headers_and_body() -> None:
    http = FakeHttp([_resp(200)])

    await _call(http, FakeSleep())

    method, url, headers, body = http.calls[0]
    assert method == "POST"
    assert url == URL
    assert headers == {"Authorization": "Bearer token"}
    assert body == b"{}"


async def test_success_on_the_second_attempt_returns_the_body_and_sleeps_once() -> None:
    http = FakeHttp([_resp(500, body=b"boom"), _resp(200, body=b'{"rows": [1]}')])
    sleep = FakeSleep()

    resp = await _call(http, sleep, attempts=3, base_delay=1.0)

    assert resp.status == 200
    assert resp.body == b'{"rows": [1]}'
    assert http.call_count == 2
    assert sleep.delays == [1.0]


# --------------------------------------------------------------------------- #
# Non-retryable statuses — the transport must be called exactly once           #
# --------------------------------------------------------------------------- #


async def test_401_raises_auth_error_and_is_not_retried() -> None:
    http = FakeHttp([_resp(401, body=b"invalid credential")])
    sleep = FakeSleep()

    with pytest.raises(AnalyticsAuthError):
        await _call(http, sleep, attempts=3)

    assert http.call_count == 1
    assert sleep.delays == []


async def test_403_raises_permission_error_and_is_not_retried() -> None:
    http = FakeHttp([_resp(403, body=b"caller lacks permission on property")])
    sleep = FakeSleep()

    with pytest.raises(AnalyticsPermissionError):
        await _call(http, sleep, attempts=3)

    assert http.call_count == 1
    assert sleep.delays == []


async def test_404_raises_analytics_empty_and_is_not_retried() -> None:
    http = FakeHttp([_resp(404)])
    sleep = FakeSleep()

    with pytest.raises(AnalyticsEmpty):
        await _call(http, sleep, attempts=3)

    assert http.call_count == 1
    assert sleep.delays == []


async def test_400_raises_the_base_error_and_is_not_retried() -> None:
    """A malformed request is a bug, not weather — never worth retrying."""
    http = FakeHttp([_resp(400, body=b"invalid dimension")])
    sleep = FakeSleep()

    with pytest.raises(AnalyticsError) as excinfo:
        await _call(http, sleep, attempts=3)

    assert not isinstance(excinfo.value, RETRYABLE_ERRORS)
    assert http.call_count == 1
    assert sleep.delays == []


async def test_error_message_carries_the_status_and_a_body_snippet() -> None:
    http = FakeHttp([_resp(403, body=b"User does not have sufficient permissions")])

    with pytest.raises(AnalyticsPermissionError) as excinfo:
        await _call(http, FakeSleep(), attempts=3)

    message = str(excinfo.value)
    assert "403" in message
    assert "sufficient permissions" in message


# --------------------------------------------------------------------------- #
# Retryable statuses                                                           #
# --------------------------------------------------------------------------- #


async def test_429_with_retry_after_header_sleeps_exactly_that_long() -> None:
    http = FakeHttp([_resp(429, {"Retry-After": "7"}), _resp(200, body=b"ok")])
    sleep = FakeSleep()

    resp = await _call(http, sleep, attempts=3, base_delay=1.0)

    assert resp.status == 200
    assert sleep.delays == [7.0]
    assert http.call_count == 2


async def test_retry_after_header_lookup_is_case_insensitive() -> None:
    http = FakeHttp([_resp(429, {"retry-after": "3"}), _resp(200)])
    sleep = FakeSleep()

    await _call(http, sleep, attempts=3, base_delay=1.0)

    assert sleep.delays == [3.0]


async def test_unparsable_retry_after_falls_back_to_exponential_backoff() -> None:
    """RFC 9110 also allows an HTTP-date; we degrade instead of guessing."""
    http = FakeHttp([_resp(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), _resp(200)])
    sleep = FakeSleep()

    await _call(http, sleep, attempts=3, base_delay=1.0)

    assert sleep.delays == [1.0]


async def test_negative_retry_after_is_clamped_to_zero() -> None:
    http = FakeHttp([_resp(429, {"Retry-After": "-5"}), _resp(200)])
    sleep = FakeSleep()

    await _call(http, sleep, attempts=3, base_delay=1.0)

    assert sleep.delays == [0.0]


async def test_429_without_retry_after_backs_off_exponentially() -> None:
    http = FakeHttp([_resp(429), _resp(429), _resp(429)])
    sleep = FakeSleep()

    with pytest.raises(AnalyticsTransientError):
        await _call(http, sleep, attempts=3, base_delay=1.0)

    assert http.call_count == 3
    assert sleep.delays == [1.0, 2.0]  # base_delay * 2**attempt, no sleep after the last try


async def test_backoff_scales_with_base_delay() -> None:
    http = FakeHttp([_resp(503), _resp(503), _resp(503)])
    sleep = FakeSleep()

    with pytest.raises(AnalyticsTransientError):
        await _call(http, sleep, attempts=3, base_delay=0.5)

    assert sleep.delays == [0.5, 1.0]


async def test_500_is_retried_up_to_attempts_then_raises_transient() -> None:
    http = FakeHttp([_resp(500, body=b"backend error"), _resp(500, body=b"backend error")])
    sleep = FakeSleep()

    with pytest.raises(AnalyticsTransientError):
        await _call(http, sleep, attempts=2, base_delay=1.0)

    assert http.call_count == 2
    assert sleep.delays == [1.0]


async def test_single_attempt_never_sleeps() -> None:
    http = FakeHttp([_resp(500)])
    sleep = FakeSleep()

    with pytest.raises(AnalyticsTransientError):
        await _call(http, sleep, attempts=1)

    assert http.call_count == 1
    assert sleep.delays == []


# --------------------------------------------------------------------------- #
# Errors raised by the transport itself                                        #
# --------------------------------------------------------------------------- #


async def test_quota_exhausted_raised_by_the_transport_is_retried() -> None:
    http = FakeHttp([QuotaExhaustedError("tokens per hour exhausted"), _resp(200, body=b"ok")])
    sleep = FakeSleep()

    resp = await _call(http, sleep, attempts=3, base_delay=1.0)

    assert resp.body == b"ok"
    assert http.call_count == 2
    assert sleep.delays == [1.0]


async def test_transient_raised_by_the_transport_is_retried() -> None:
    http = FakeHttp([AnalyticsTransientError("connection reset"), _resp(200)])
    sleep = FakeSleep()

    await _call(http, sleep, attempts=3, base_delay=1.0)

    assert http.call_count == 2


async def test_auth_error_raised_by_the_transport_is_not_retried() -> None:
    http = FakeHttp([AnalyticsAuthError("token expired"), _resp(200)])
    sleep = FakeSleep()

    with pytest.raises(AnalyticsAuthError):
        await _call(http, sleep, attempts=3)

    assert http.call_count == 1
    assert sleep.delays == []


async def test_unexpected_transport_exception_propagates_unretried() -> None:
    """A programming error must surface, not be swallowed by the retry loop."""
    http = FakeHttp([RuntimeError("socket exploded")])
    sleep = FakeSleep()

    with pytest.raises(RuntimeError, match="socket exploded"):
        await _call(http, sleep, attempts=3)

    assert http.call_count == 1
    assert sleep.delays == []


async def test_invalid_attempts_is_rejected_before_any_call() -> None:
    http = FakeHttp([])

    with pytest.raises(ValueError):
        await _call(http, FakeSleep(), attempts=0)

    assert http.call_count == 0


# --------------------------------------------------------------------------- #
# Log hygiene                                                                  #
# --------------------------------------------------------------------------- #


async def test_retry_log_never_leaks_credentials(caplog: pytest.LogCaptureFixture) -> None:
    http = FakeHttp([_resp(500), _resp(200)])
    sleep = FakeSleep()

    with caplog.at_level(logging.WARNING, logger="app.analytics.http"):
        await request_with_retry(
            http,
            "GET",
            "https://analyticsdata.googleapis.com/v1beta/data?api_key=SUPERSECRET",
            headers={"Authorization": "Bearer TOPSECRET"},
            attempts=2,
            base_delay=1.0,
            sleep=sleep,
        )

    assert "SUPERSECRET" not in caplog.text
    assert "TOPSECRET" not in caplog.text
    assert "/v1beta/data" in caplog.text  # still diagnosable
