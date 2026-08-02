"""Unit tests for the GA4 analytics adapter (spec §2.3 + docs-study Δ1/Δ2/Δ3).

**Nothing here touches the network or needs a credential.** The GA4 client is
injected, so every test drives a fake that records the ``RunReportRequest`` it was
given and replays canned responses. The requests the adapter builds are *real*
``google.analytics.data_v1beta`` protos, so a renamed or mistyped request field
fails at construction time rather than in production.

The four contracts under test:

* **Δ1 — pagination.** GA4 caps a single ``runReport`` at 250 000 rows and defaults
  to 10 000. A report bigger than one page must be paged on ``offset``, and a report
  that is still capped after paging must come back ``truncated=True``. Silent
  truncation reading as a complete answer is exactly what the honesty program exists
  to prevent.
* **Δ2 — ``keep_empty_rows``.** Off by default, which turns a zero-activity day into
  a *missing* row and lets a chart interpolate over a genuinely dead day.
* **Δ3 — ``return_property_quota``.** Ask for the quota and raise the typed
  :class:`QuotaExhaustedError` when it is spent, instead of inferring quota state
  from a 429.
* **Column contract.** ``AnalyticsReport.columns`` is what T7 upserts into the
  ``ga4_*`` fact tables, so each report's columns are asserted literally against
  spec §1.4 rather than derived from the same constant the adapter uses.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from google.analytics.data_v1beta.types import (
    DimensionHeader,
    DimensionValue,
    MetricHeader,
    MetricValue,
    PropertyQuota,
    QuotaStatus,
    Row,
    RunReportRequest,
    RunReportResponse,
)
from google.api_core import exceptions as gexc

from app.analytics.base import AnalyticsReport, ReportSpec
from app.analytics.errors import (
    AnalyticsAuthError,
    AnalyticsEmpty,
    AnalyticsError,
    AnalyticsPermissionError,
    AnalyticsTransientError,
    QuotaExhaustedError,
)
from app.analytics.ga4.adapter import GA4Adapter
from app.analytics.ga4.config import GA4Config, GA4Credentials
from app.analytics.ga4.reports import GA4_REPORTS, REPORT_NAMES
from app.analytics.http import MAX_RETRY_DELAY
from app.config import settings
from app.connectors.base import ConnectionConfig

PROPERTY = "294380179"
PERIOD = "2026-07-31"

#: The shipped attempt budget every un-overridden adapter uses.
ATTEMPTS = settings.analytics_http_attempts

#: The payload columns each report must produce, spelled out from spec §1.4 (the
#: five ``ga4_*`` fact tables). This is T7's upsert contract: if these drift, the
#: collect service writes into the wrong columns.
EXPECTED_COLUMNS: dict[str, list[str]] = {
    "overview": [
        "property_id",
        "date",
        "sessions",
        "active_users",
        "new_users",
        "screen_page_views",
        "event_count",
        "total_revenue",
    ],
    "geo": ["property_id", "date", "country", "sessions", "active_users"],
    "platform": [
        "property_id",
        "date",
        "platform",
        "device_category",
        "sessions",
        "active_users",
    ],
    "trend": [
        "property_id",
        "date",
        "channel_group",
        "sessions",
        "active_users",
        "key_events",
    ],
    "events": ["property_id", "date", "event_name", "event_count", "active_users"],
}


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class _FakeRow:
    """Duck-typed stand-in for ``types.Row``.

    A real proto ``Row`` is used in :func:`test_parses_a_real_run_report_response`
    to prove the field names; the paging tests replay one shared instance a quarter
    of a million times, where allocating real protos would dominate the runtime.
    """

    __slots__ = ("dimension_values", "metric_values")

    def __init__(self, dimensions: list[str], metrics: list[str]) -> None:
        self.dimension_values = [DimensionValue(value=v) for v in dimensions]
        self.metric_values = [MetricValue(value=v) for v in metrics]


class _FakeResponse:
    """Duck-typed stand-in for ``types.RunReportResponse``."""

    def __init__(
        self,
        rows: list[Any],
        row_count: int,
        *,
        dimension_headers: list[str] | None = None,
        metric_headers: list[str] | None = None,
        property_quota: PropertyQuota | None = None,
    ) -> None:
        self.rows = rows
        self.row_count = row_count
        self.dimension_headers = [DimensionHeader(name=n) for n in (dimension_headers or [])]
        self.metric_headers = [MetricHeader(name=n) for n in (metric_headers or [])]
        self.property_quota = property_quota


class FakeGA4Client:
    """Records every request and replays a scripted list of responses/exceptions."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.requests: list[RunReportRequest] = []

    async def run_report(self, request: RunReportRequest) -> Any:
        self.requests.append(request)
        if not self._script:
            raise AssertionError("run_report called more times than the script allows")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RepeatingGA4Client:
    """Replays one item — a response or an exception — for *every* call.

    A scripted fake cannot express "the vendor is down": the second call falls
    off the end of the script. Retry behaviour needs a source that keeps
    failing, plus a call count saying how many attempts the adapter spent.
    """

    def __init__(self, item: Any) -> None:
        self._item = item
        self.requests: list[RunReportRequest] = []

    async def run_report(self, request: RunReportRequest) -> Any:
        self.requests.append(request)
        if isinstance(self._item, Exception):
            raise self._item
        return self._item

    @property
    def calls(self) -> int:
        return len(self.requests)


class FakeSleep:
    """Records the delays asked for instead of waiting — no test touches the clock."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class _VendorRetryAfterError(Exception):
    """A vendor error shaped like ``google.api_core.exceptions.GoogleAPICallError``.

    ``.code`` carries the HTTP status the taxonomy maps on, and ``.response``
    is the HTTP response google-api-core attaches — which is where a
    ``Retry-After`` header actually arrives.
    """

    def __init__(self, code: int, headers: dict[str, str]) -> None:
        super().__init__(f"HTTP {code}")
        self.code = code
        self.response = SimpleNamespace(headers=headers)


class PagingGA4Client:
    """A property with ``total`` rows, served in pages of at most ``page_cap``.

    Rows are shaped from the request itself, so the fake answers whichever report
    it is asked for. ``claimed`` overrides the ``row_count`` the vendor reports,
    which is how the truncation case is expressed: a source that keeps claiming
    more rows than it ever yields.
    """

    def __init__(self, *, total: int, claimed: int | None = None, page_cap: int = 10_000) -> None:
        self.total = total
        self.claimed = total if claimed is None else claimed
        self.page_cap = page_cap
        self.requests: list[RunReportRequest] = []

    async def run_report(self, request: RunReportRequest) -> Any:
        self.requests.append(request)
        dimensions = [d.name for d in request.dimensions]
        metrics = [m.name for m in request.metrics]
        # One shared row object per page: the adapter parses each reference
        # independently, and allocating 250 000 distinct fakes would dominate
        # the runtime of the paging test without testing anything more.
        row = _FakeRow(
            ["20260731" if name == "date" else f"{name}-value" for name in dimensions],
            ["1"] * len(metrics),
        )
        limit = min(int(request.limit or 10_000), self.page_cap)
        remaining = max(self.total - int(request.offset), 0)
        served = min(limit, remaining)
        return _FakeResponse(
            [row] * served,
            self.claimed,
            dimension_headers=dimensions,
            metric_headers=metrics,
        )


def _config(**overrides: Any) -> ConnectionConfig:
    source_config: dict[str, Any] = {"property_ids": [PROPERTY]}
    source_config.update(overrides)
    return ConnectionConfig(db_type="ga4", extra={"source_config": source_config})


async def _connected(client: Any, **kwargs: Any) -> GA4Adapter:
    """A connected adapter whose retry delays are recorded, never slept.

    The ``sleep`` default matters: the adapter now retries transient vendor
    failures, so without an injected delay a single 503 fixture would put the
    test suite to sleep for real.
    """
    kwargs.setdefault("sleep", FakeSleep())
    adapter = GA4Adapter(client=client, **kwargs)
    await adapter.connect(_config())
    return adapter


# --------------------------------------------------------------------------
# The adapter contract (spec §2.3)
# --------------------------------------------------------------------------


async def test_list_entities_returns_the_five_report_names() -> None:
    adapter = GA4Adapter(client=FakeGA4Client([]))
    assert await adapter.list_entities() == ["overview", "geo", "platform", "trend", "events"]
    assert set(REPORT_NAMES) == {"overview", "geo", "platform", "trend", "events"}


async def test_available_reports_are_report_specs_with_a_daily_grain() -> None:
    reports = GA4Adapter(client=FakeGA4Client([])).available_reports()
    assert len(reports) == 5
    assert all(isinstance(r, ReportSpec) for r in reports)
    assert {r.grain for r in reports} == {"daily"}
    assert all(r.description for r in reports), "every report needs a description for the agent"


async def test_query_raises_not_implemented() -> None:
    adapter = GA4Adapter(client=FakeGA4Client([]))
    with pytest.raises(NotImplementedError):
        await adapter.query("SELECT 1")


async def test_source_type_matches_the_connection_source_type() -> None:
    assert GA4Adapter(client=FakeGA4Client([])).source_type == "ga4"


# --------------------------------------------------------------------------
# The column contract T7 upserts against (spec §1.4)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("report_name", ["overview", "geo", "platform", "trend", "events"])
def test_report_columns_match_the_fact_table_payload(report_name: str) -> None:
    spec = next(r for r in GA4_REPORTS if r.name == report_name)
    assert list(spec.columns) == EXPECTED_COLUMNS[report_name]


async def test_fetch_returns_the_declared_columns() -> None:
    client = FakeGA4Client(
        [
            _FakeResponse(
                [_FakeRow(["20260731", "Germany"], ["12", "9"])],
                1,
                dimension_headers=["date", "country"],
                metric_headers=["sessions", "activeUsers"],
            )
        ]
    )
    adapter = await _connected(client)
    report = await adapter.fetch("geo", PERIOD)
    assert report.columns == EXPECTED_COLUMNS["geo"]
    assert report.rows == [[PROPERTY, dt.date(2026, 7, 31), "Germany", 12, 9]]


async def test_values_are_typed_for_the_fact_tables() -> None:
    """Counts are ``int`` and revenue is ``Decimal`` — never float (spec §1.4)."""
    client = FakeGA4Client(
        [
            _FakeResponse(
                [_FakeRow(["20260731"], ["10", "9", "3", "40", "88", "1234.5600"])],
                1,
                dimension_headers=["date"],
                metric_headers=[
                    "sessions",
                    "activeUsers",
                    "newUsers",
                    "screenPageViews",
                    "eventCount",
                    "totalRevenue",
                ],
            )
        ]
    )
    adapter = await _connected(client)
    row = (await adapter.fetch("overview", PERIOD)).rows[0]
    assert row[1] == dt.date(2026, 7, 31)
    assert [type(v) for v in row[2:7]] == [int] * 5
    assert row[7] == Decimal("1234.5600")
    assert isinstance(row[7], Decimal)


# --------------------------------------------------------------------------
# Δ1 — pagination
# --------------------------------------------------------------------------


async def test_fetch_paginates_until_row_count_is_reached() -> None:
    client = PagingGA4Client(total=250_100, page_cap=100_000)
    adapter = await _connected(client, page_size=100_000)

    report = await adapter.fetch("overview", PERIOD)

    assert [int(r.offset) for r in client.requests] == [0, 100_000, 200_000]
    assert [int(r.limit) for r in client.requests] == [100_000, 100_000, 100_000]
    assert len(report.rows) == 250_100
    assert report.truncated is False
    assert report.degraded is None


async def test_fetch_stops_on_a_short_page_without_claiming_truncation() -> None:
    client = PagingGA4Client(total=150, page_cap=100)
    adapter = await _connected(client, page_size=100)

    report = await adapter.fetch("overview", PERIOD)

    assert [int(r.offset) for r in client.requests] == [0, 100]
    assert len(report.rows) == 150
    assert report.truncated is False


async def test_fetch_marks_truncated_when_the_row_cap_is_still_hit() -> None:
    """A source that keeps claiming more rows than it yields must not loop forever."""
    client = PagingGA4Client(total=10_000, claimed=10_000, page_cap=100)
    adapter = await _connected(client, page_size=100, max_rows=250)

    report = await adapter.fetch("overview", PERIOD)

    assert len(report.rows) == 250
    assert report.truncated is True
    assert report.degraded is not None
    assert "250" in report.degraded


async def test_page_size_is_capped_at_the_vendor_maximum() -> None:
    client = PagingGA4Client(total=10, page_cap=250_000)
    adapter = await _connected(client, page_size=10_000_000)
    await adapter.fetch("overview", PERIOD)
    assert int(client.requests[0].limit) == 250_000


async def test_default_page_size_is_ten_thousand() -> None:
    client = PagingGA4Client(total=5)
    adapter = await _connected(client)
    await adapter.fetch("overview", PERIOD)
    assert int(client.requests[0].limit) == 10_000


# --------------------------------------------------------------------------
# Δ2 — keep_empty_rows
# --------------------------------------------------------------------------


@pytest.mark.parametrize("report_name", ["overview", "geo", "platform", "trend", "events"])
async def test_time_series_requests_keep_empty_rows(report_name: str) -> None:
    client = PagingGA4Client(total=1)
    adapter = await _connected(client)
    await adapter.fetch(report_name, PERIOD)
    assert client.requests[0].keep_empty_rows is True


# --------------------------------------------------------------------------
# Δ3 — return_property_quota
# --------------------------------------------------------------------------


async def test_return_property_quota_is_requested() -> None:
    client = PagingGA4Client(total=1)
    adapter = await _connected(client)
    await adapter.fetch("overview", PERIOD)
    assert client.requests[0].return_property_quota is True


async def test_exhausted_quota_raises_quota_exhausted_error() -> None:
    client = FakeGA4Client(
        [
            _FakeResponse(
                [_FakeRow(["20260731"], ["1", "1", "1", "1", "1", "1"])],
                1,
                dimension_headers=["date"],
                metric_headers=[
                    "sessions",
                    "activeUsers",
                    "newUsers",
                    "screenPageViews",
                    "eventCount",
                    "totalRevenue",
                ],
                property_quota=PropertyQuota(
                    tokens_per_day=QuotaStatus(consumed=25_000, remaining=0),
                    tokens_per_hour=QuotaStatus(consumed=10, remaining=4_990),
                ),
            )
        ]
    )
    # attempts=1: this test is about the quota *mapping*. Exhaustion is
    # retryable, and the retry path has its own test below.
    adapter = await _connected(client, attempts=1)
    with pytest.raises(QuotaExhaustedError, match="tokens_per_day"):
        await adapter.fetch("overview", PERIOD)


async def test_healthy_quota_does_not_raise() -> None:
    client = FakeGA4Client(
        [
            _FakeResponse(
                [_FakeRow(["20260731", "Germany"], ["1", "1"])],
                1,
                dimension_headers=["date", "country"],
                metric_headers=["sessions", "activeUsers"],
                property_quota=PropertyQuota(
                    tokens_per_day=QuotaStatus(consumed=10, remaining=24_990)
                ),
            )
        ]
    )
    adapter = await _connected(client)
    assert len((await adapter.fetch("geo", PERIOD)).rows) == 1


async def test_absent_quota_block_is_not_read_as_exhaustion() -> None:
    """An unset proto ``PropertyQuota`` is all-zeros — that must not look spent."""
    client = FakeGA4Client(
        [
            _FakeResponse(
                [_FakeRow(["20260731", "Germany"], ["1", "1"])],
                1,
                dimension_headers=["date", "country"],
                metric_headers=["sessions", "activeUsers"],
                property_quota=PropertyQuota(),
            )
        ]
    )
    adapter = await _connected(client)
    assert len((await adapter.fetch("geo", PERIOD)).rows) == 1


# --------------------------------------------------------------------------
# Error taxonomy (spec §2.1)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raised", "expected", "expected_calls"),
    [
        (gexc.Unauthenticated("bad key"), AnalyticsAuthError, 1),
        (gexc.PermissionDenied("property not shared"), AnalyticsPermissionError, 1),
        (gexc.NotFound("no such property"), AnalyticsEmpty, 1),
        (gexc.ResourceExhausted("slow down"), AnalyticsTransientError, ATTEMPTS),
        (gexc.ServiceUnavailable("backend down"), AnalyticsTransientError, ATTEMPTS),
        (gexc.InternalServerError("boom"), AnalyticsTransientError, ATTEMPTS),
        (gexc.InvalidArgument("bad dimension"), AnalyticsError, 1),
    ],
)
async def test_client_errors_map_onto_the_taxonomy_and_only_transient_ones_retry(
    raised: Exception, expected: type[AnalyticsError], expected_calls: int
) -> None:
    """The mapping *and* the retry decision it drives, on the real fetch path."""
    client = RepeatingGA4Client(raised)
    adapter = await _connected(client)

    with pytest.raises(expected):
        await adapter.fetch("overview", PERIOD)

    assert client.calls == expected_calls


async def test_permission_denied_is_not_swallowed_as_empty() -> None:
    """403 must stay a permission error — the collect loop stops the report on it."""
    adapter = await _connected(FakeGA4Client([gexc.PermissionDenied("no access")]))
    with pytest.raises(AnalyticsPermissionError):
        await adapter.fetch("geo", PERIOD)


async def test_no_rows_raises_analytics_empty() -> None:
    client = FakeGA4Client([_FakeResponse([], 0, dimension_headers=["date"])])
    adapter = await _connected(client)
    with pytest.raises(AnalyticsEmpty):
        await adapter.fetch("overview", PERIOD)


async def test_unknown_report_name_is_a_programming_error() -> None:
    adapter = await _connected(FakeGA4Client([]))
    with pytest.raises(ValueError, match="unknown GA4 report"):
        await adapter.fetch("nope", PERIOD)


async def test_malformed_period_is_rejected_before_any_vendor_call() -> None:
    client = FakeGA4Client([])
    adapter = await _connected(client)
    with pytest.raises(AnalyticsError):
        await adapter.fetch("overview", "31/07/2026")
    assert client.requests == []


async def test_fetch_before_connect_raises() -> None:
    adapter = GA4Adapter(client=FakeGA4Client([]))
    with pytest.raises(AnalyticsError, match="not connected"):
        await adapter.fetch("overview", PERIOD)


# --------------------------------------------------------------------------
# Retrying transient vendor failures — on the production path (M3, REQ-003)
# --------------------------------------------------------------------------
#
# REQ-003's retry policy was implemented and unit-tested in ``app.analytics.http``
# and then reached by nothing: ``GA4Adapter`` talks to google's own client, so
# ``request_with_retry`` had exactly one caller — its own test. A single 429 or
# 503 marked a period ``failed`` that one retry would have collected. Every test
# below therefore drives ``GA4Adapter.fetch``/``test_connection`` — the paths
# production actually runs — and not the retry helper in isolation.


def _geo_response() -> _FakeResponse:
    return _FakeResponse(
        [_FakeRow(["20260731", "Germany"], ["12", "9"])],
        1,
        dimension_headers=["date", "country"],
        metric_headers=["sessions", "activeUsers"],
    )


async def test_a_transient_failure_is_retried_and_the_next_attempt_is_returned() -> None:
    client = FakeGA4Client([gexc.ServiceUnavailable("backend down"), _geo_response()])
    sleep = FakeSleep()
    adapter = await _connected(client, sleep=sleep, retry_base_delay=1.0)

    report = await adapter.fetch("geo", PERIOD)

    assert report.rows == [[PROPERTY, dt.date(2026, 7, 31), "Germany", 12, 9]]
    assert len(client.requests) == 2, "the vendor must actually be called twice"
    assert sleep.delays == [1.0]


async def test_a_429_is_retried() -> None:
    client = FakeGA4Client([gexc.TooManyRequests("rate limited"), _geo_response()])
    sleep = FakeSleep()
    adapter = await _connected(client, sleep=sleep, retry_base_delay=1.0)

    assert len((await adapter.fetch("geo", PERIOD)).rows) == 1
    assert len(client.requests) == 2


async def test_an_auth_failure_is_never_retried() -> None:
    client = RepeatingGA4Client(gexc.Unauthenticated("invalid_grant"))
    sleep = FakeSleep()
    adapter = await _connected(client, sleep=sleep)

    with pytest.raises(AnalyticsAuthError):
        await adapter.fetch("overview", PERIOD)

    assert client.calls == 1
    assert sleep.delays == [], "a wrong credential can never become right by waiting"


async def test_a_permission_failure_is_never_retried() -> None:
    client = RepeatingGA4Client(gexc.PermissionDenied("property not shared"))
    sleep = FakeSleep()
    adapter = await _connected(client, sleep=sleep)

    with pytest.raises(AnalyticsPermissionError):
        await adapter.fetch("geo", PERIOD)

    assert client.calls == 1
    assert sleep.delays == []


async def test_the_attempt_budget_comes_from_the_configured_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``analytics_http_attempts`` was declared, validated, documented — and unread."""
    monkeypatch.setattr(settings, "analytics_http_attempts", 4)
    client = RepeatingGA4Client(gexc.ServiceUnavailable("backend down"))
    sleep = FakeSleep()
    adapter = await _connected(client, sleep=sleep, retry_base_delay=1.0)

    with pytest.raises(AnalyticsTransientError):
        await adapter.fetch("overview", PERIOD)

    assert client.calls == 4
    assert sleep.delays == [1.0, 2.0, 4.0], "exponential backoff, no sleep after the last try"


async def test_a_vendor_retry_after_header_is_honoured() -> None:
    client = FakeGA4Client([_VendorRetryAfterError(503, {"Retry-After": "7"}), _geo_response()])
    sleep = FakeSleep()
    adapter = await _connected(client, sleep=sleep, retry_base_delay=1.0)

    assert len((await adapter.fetch("geo", PERIOD)).rows) == 1
    assert sleep.delays == [7.0], "the vendor's own hint wins over our backoff"


async def test_an_absurd_vendor_retry_after_is_clamped() -> None:
    """A day-long ``Retry-After`` must not hold the collection job for a day."""
    client = FakeGA4Client([_VendorRetryAfterError(429, {"retry-after": "86400"}), _geo_response()])
    sleep = FakeSleep()
    adapter = await _connected(client, sleep=sleep, retry_base_delay=1.0)

    await adapter.fetch("geo", PERIOD)

    assert sleep.delays == [MAX_RETRY_DELAY]


async def test_quota_exhaustion_is_retried_and_can_recover() -> None:
    """Δ3's quota check runs *inside* the retried attempt, so a rollover heals it."""
    exhausted = _FakeResponse(
        [_FakeRow(["20260731", "Germany"], ["1", "1"])],
        1,
        dimension_headers=["date", "country"],
        metric_headers=["sessions", "activeUsers"],
        property_quota=PropertyQuota(tokens_per_hour=QuotaStatus(consumed=5_000, remaining=0)),
    )
    client = FakeGA4Client([exhausted, _geo_response()])
    sleep = FakeSleep()
    adapter = await _connected(client, sleep=sleep, retry_base_delay=1.0)

    assert len((await adapter.fetch("geo", PERIOD)).rows) == 1
    assert len(client.requests) == 2


async def test_an_unmapped_client_exception_still_propagates_unretried() -> None:
    """A bug is not weather: it must surface as itself, on the first attempt."""
    client = RepeatingGA4Client(RuntimeError("client is broken"))
    sleep = FakeSleep()
    adapter = await _connected(client, sleep=sleep)

    with pytest.raises(RuntimeError, match="client is broken"):
        await adapter.fetch("overview", PERIOD)

    assert client.calls == 1
    assert sleep.delays == []


async def test_test_connection_retries_a_transient_probe_failure() -> None:
    """The connect-test button must not fail a good property on one 503."""
    client = FakeGA4Client(
        [
            gexc.ServiceUnavailable("backend down"),
            _FakeResponse(
                [_FakeRow(["20260731"], ["1", "1", "1", "1", "1", "1"])],
                1,
                dimension_headers=["date"],
                metric_headers=[
                    "sessions",
                    "activeUsers",
                    "newUsers",
                    "screenPageViews",
                    "eventCount",
                    "totalRevenue",
                ],
            ),
        ]
    )
    adapter = await _connected(client, retry_base_delay=1.0)

    assert await adapter.test_connection() is True
    assert len(client.requests) == 2


async def test_paging_retries_only_the_failed_page() -> None:
    """A blip on page two must not restart the report from page one."""

    class _FlakyPagingClient:
        def __init__(self) -> None:
            self.requests: list[RunReportRequest] = []
            self._failed_once = False

        async def run_report(self, request: RunReportRequest) -> Any:
            self.requests.append(request)
            if int(request.offset) == 1 and not self._failed_once:
                self._failed_once = True
                raise gexc.ServiceUnavailable("backend down")
            row = _FakeRow(["20260731", "Germany"], ["1", "1"])
            served = 1 if int(request.offset) < 2 else 0
            return _FakeResponse(
                [row] * served,
                2,
                dimension_headers=["date", "country"],
                metric_headers=["sessions", "activeUsers"],
            )

    client = _FlakyPagingClient()
    sleep = FakeSleep()
    adapter = GA4Adapter(client=client, page_size=1, sleep=sleep, retry_base_delay=1.0)
    await adapter.connect(_config())

    report = await adapter.fetch("geo", PERIOD)

    assert len(report.rows) == 2
    assert report.truncated is False
    assert [int(r.offset) for r in client.requests] == [0, 1, 1]


# --------------------------------------------------------------------------
# Multiple properties, filters, connection lifecycle
# --------------------------------------------------------------------------


async def test_multiple_properties_are_unioned_and_tagged() -> None:
    client = FakeGA4Client(
        [
            _FakeResponse(
                [_FakeRow(["20260731", "Germany"], ["1", "1"])],
                1,
                dimension_headers=["date", "country"],
                metric_headers=["sessions", "activeUsers"],
            ),
            _FakeResponse(
                [_FakeRow(["20260731", "France"], ["2", "2"])],
                1,
                dimension_headers=["date", "country"],
                metric_headers=["sessions", "activeUsers"],
            ),
        ]
    )
    adapter = GA4Adapter(client=client)
    await adapter.connect(
        ConnectionConfig(db_type="ga4", extra={"source_config": {"property_ids": ["111", "222"]}})
    )

    report = await adapter.fetch("geo", PERIOD)

    assert [r.property for r in client.requests] == ["properties/111", "properties/222"]
    assert [row[0] for row in report.rows] == ["111", "222"]


async def test_one_empty_property_does_not_hide_the_other() -> None:
    client = FakeGA4Client(
        [
            _FakeResponse([], 0, dimension_headers=["date", "country"]),
            _FakeResponse(
                [_FakeRow(["20260731", "France"], ["2", "2"])],
                1,
                dimension_headers=["date", "country"],
                metric_headers=["sessions", "activeUsers"],
            ),
        ]
    )
    adapter = GA4Adapter(client=client)
    await adapter.connect(
        ConnectionConfig(db_type="ga4", extra={"source_config": {"property_ids": ["111", "222"]}})
    )
    report = await adapter.fetch("geo", PERIOD)
    assert [row[0] for row in report.rows] == ["222"]


async def test_event_report_filters_the_configured_event_names() -> None:
    client = PagingGA4Client(total=1)
    adapter = GA4Adapter(client=client)
    await adapter.connect(
        ConnectionConfig(
            db_type="ga4",
            extra={
                "source_config": {
                    "property_ids": [PROPERTY],
                    "event_names": ["pin_show_promo", "purchase"],
                }
            },
        )
    )
    await adapter.fetch("events", PERIOD)

    filt = client.requests[0].dimension_filter.filter
    assert filt.field_name == "eventName"
    assert list(filt.in_list_filter.values) == ["pin_show_promo", "purchase"]


async def test_event_report_without_configured_names_is_unfiltered() -> None:
    client = PagingGA4Client(total=1)
    adapter = await _connected(client)
    await adapter.fetch("events", PERIOD)
    assert "dimension_filter" not in client.requests[0]


async def test_currency_code_is_forwarded_when_configured() -> None:
    client = PagingGA4Client(total=1)
    adapter = GA4Adapter(client=client)
    await adapter.connect(
        ConnectionConfig(
            db_type="ga4",
            extra={"source_config": {"property_ids": [PROPERTY], "currency_code": "USD"}},
        )
    )
    await adapter.fetch("overview", PERIOD)
    assert client.requests[0].currency_code == "USD"


async def test_connect_without_property_ids_fails_loudly() -> None:
    adapter = GA4Adapter(client=FakeGA4Client([]))
    with pytest.raises(AnalyticsError, match="property_ids"):
        await adapter.connect(ConnectionConfig(db_type="ga4", extra={"source_config": {}}))


async def test_test_connection_is_true_on_a_successful_probe() -> None:
    client = PagingGA4Client(total=1)
    adapter = await _connected(client)
    assert await adapter.test_connection() is True
    assert int(client.requests[0].limit) == 1


async def test_test_connection_is_false_when_the_property_is_not_shared() -> None:
    adapter = await _connected(FakeGA4Client([gexc.PermissionDenied("not shared")]))
    assert await adapter.test_connection() is False


async def test_disconnect_drops_the_client_and_is_idempotent() -> None:
    adapter = await _connected(FakeGA4Client([]))
    await adapter.disconnect()
    await adapter.disconnect()
    with pytest.raises(AnalyticsError, match="not connected"):
        await adapter.fetch("overview", PERIOD)


# --------------------------------------------------------------------------
# Config: knobs are separate from the secret
# --------------------------------------------------------------------------


def test_config_reads_knobs_from_a_nested_source_config() -> None:
    cfg = GA4Config.from_connection_config(
        ConnectionConfig(
            db_type="ga4",
            extra={
                "source_config": {
                    "property_ids": ["1", "2"],
                    "backfill_days": 7,
                    "event_names": ["purchase"],
                    "currency_code": "EUR",
                }
            },
        )
    )
    assert cfg.property_ids == ("1", "2")
    assert cfg.backfill_days == 7
    assert cfg.event_names == ("purchase",)
    assert cfg.currency_code == "EUR"


def test_config_also_accepts_flat_extra_keys() -> None:
    cfg = GA4Config.from_connection_config(
        ConnectionConfig(db_type="ga4", extra={"property_ids": ["9"], "backfill_days": 90})
    )
    assert cfg.property_ids == ("9",)
    assert cfg.backfill_days == 90


def test_config_defaults_and_coercion() -> None:
    cfg = GA4Config.from_mapping({"property_ids": ["properties/42", 43]})
    assert cfg.property_ids == ("42", "43"), "a pasted properties/NNN prefix is normalised"
    assert cfg.backfill_days == 30
    assert cfg.event_names == ()
    assert cfg.currency_code is None


def test_config_rejects_a_non_positive_backfill() -> None:
    with pytest.raises(AnalyticsError):
        GA4Config.from_mapping({"property_ids": ["1"], "backfill_days": 0})


def test_config_carries_no_secret_material() -> None:
    cfg = GA4Config.from_mapping({"property_ids": ["1"]})
    assert not hasattr(cfg, "service_account_info")
    assert "private_key" not in repr(cfg)


def test_credentials_reject_malformed_service_account_json() -> None:
    with pytest.raises(AnalyticsAuthError):
        GA4Credentials.from_json("{not json")


def test_credentials_reject_a_service_account_missing_required_fields() -> None:
    with pytest.raises(AnalyticsAuthError):
        GA4Credentials.from_json('{"type": "service_account"}')


def test_credentials_never_repr_the_private_key() -> None:
    creds = GA4Credentials.from_json(
        '{"type": "service_account", "client_email": "sa@x.iam.gserviceaccount.com",'
        ' "private_key": "-----BEGIN PRIVATE KEY-----super-secret-----END PRIVATE KEY-----",'
        ' "token_uri": "https://oauth2.googleapis.com/token"}'
    )
    assert creds.client_email == "sa@x.iam.gserviceaccount.com"
    assert "super-secret" not in repr(creds)
    assert "super-secret" not in str(creds)


async def test_connect_without_a_client_or_credentials_raises_auth_error() -> None:
    adapter = GA4Adapter()
    with pytest.raises(AnalyticsAuthError):
        await adapter.connect(_config())


# --------------------------------------------------------------------------
# Grounding: the parser against a real proto response
# --------------------------------------------------------------------------


async def test_parses_a_real_run_report_response() -> None:
    """Guards the SDK field names the duck-typed fakes above only imitate."""
    response = RunReportResponse(
        dimension_headers=[DimensionHeader(name="date"), DimensionHeader(name="country")],
        metric_headers=[
            MetricHeader(name="sessions"),
            MetricHeader(name="activeUsers"),
        ],
        rows=[
            Row(
                dimension_values=[
                    DimensionValue(value="20260731"),
                    DimensionValue(value="Germany"),
                ],
                metric_values=[MetricValue(value="7"), MetricValue(value="5")],
            )
        ],
        row_count=1,
    )
    adapter = await _connected(FakeGA4Client([response]))
    report = await adapter.fetch("geo", PERIOD)
    assert isinstance(report, AnalyticsReport)
    assert report.rows == [[PROPERTY, dt.date(2026, 7, 31), "Germany", 7, 5]]
    assert report.truncated is False


async def test_headers_out_of_order_are_realigned_by_name() -> None:
    client = FakeGA4Client(
        [
            _FakeResponse(
                [_FakeRow(["Germany", "20260731"], ["5", "7"])],
                1,
                dimension_headers=["country", "date"],
                metric_headers=["activeUsers", "sessions"],
            )
        ]
    )
    adapter = await _connected(client)
    report = await adapter.fetch("geo", PERIOD)
    assert report.rows == [[PROPERTY, dt.date(2026, 7, 31), "Germany", 7, 5]]


async def test_a_missing_header_is_reported_not_guessed() -> None:
    client = FakeGA4Client(
        [
            _FakeResponse(
                [_FakeRow(["20260731", "Germany"], ["5"])],
                1,
                dimension_headers=["date", "country"],
                metric_headers=["activeUsers"],
            )
        ]
    )
    adapter = await _connected(client)
    with pytest.raises(AnalyticsError, match="sessions"):
        await adapter.fetch("geo", PERIOD)
