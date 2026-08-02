"""The GA4 Data API adapter (spec §2.3, docs-study Δ1/Δ2/Δ3).

The vendor client is **injected**. Production passes nothing and the adapter builds
a ``BetaAnalyticsDataAsyncClient`` from the decrypted service-account JSON in
:meth:`GA4Adapter.connect`; every test passes a fake. That is why no unit test in
this package touches the network or needs a credential, and why a wrong request
field fails in CI rather than in a nightly collection run.

Three vendor behaviours are handled here because nothing downstream can:

**Δ1 — paging.** ``runReport`` returns 10 000 rows unless told otherwise and never
more than 250 000, while telling you the true ``row_count``. A single un-paged call
against a busy property therefore returns a *plausible* answer that is quietly
missing most of the data. :meth:`GA4Adapter.fetch` pages on ``offset`` until it has
``row_count`` rows or a page comes back short, and when its own row cap stops it
first it says so: ``truncated=True`` plus a ``degraded`` sentence the agent repeats
to the user.

**Δ2 — ``keep_empty_rows``.** See :mod:`app.analytics.ga4.reports`: without it a
zero-activity day is absent rather than zero.

**Δ3 — ``return_property_quota``.** Asking for the quota turns "the vendor is
throttling us" from a guess based on a 429 into a fact, raised as the typed
:class:`QuotaExhaustedError` so the collect service records that period failed and
keeps going instead of hammering an empty bucket.

**Retries (REQ-003, M3).** Every vendor call goes through
:func:`app.analytics.http.retry_async`, the same policy the raw-HTTP transport
uses: ``AnalyticsTransientError`` and ``QuotaExhaustedError`` are retried with
bounded exponential backoff (honouring the vendor's ``Retry-After`` when it sends
one) for ``settings.analytics_http_attempts`` attempts; auth and permission
failures are raised on the first attempt, because a wrong credential cannot
become right by waiting. This adapter cannot use ``request_with_retry`` — google's
client owns the socket — which is exactly how the policy came to be implemented,
tested, and reached by nothing: one 429 used to mark a whole period ``failed``.

Raw response bodies are never persisted — rows are parsed and the response goes out
of scope (spec §3.4).
"""

from __future__ import annotations

import asyncio
import calendar
import datetime as dt
import logging
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    RunReportRequest,
)

from app.analytics.base import AnalyticsReport, AnalyticsSourceAdapter, ReportSpec
from app.analytics.errors import (
    AnalyticsAuthError,
    AnalyticsEmpty,
    AnalyticsError,
    AnalyticsTransientError,
    QuotaExhaustedError,
)
from app.analytics.ga4.config import CREDENTIAL_SECRET_KEY, GA4Config, GA4Credentials
from app.analytics.ga4.reports import GA4_REPORTS, REPORTS_BY_NAME, GA4Field, GA4ReportSpec
from app.analytics.http import Resp, SleepFn, classify_response, retry_after_seconds, retry_async
from app.config import settings
from app.connectors.base import ConnectionConfig

logger = logging.getLogger(__name__)

#: GA4's own default page size — the value the API uses when ``limit`` is unset.
DEFAULT_PAGE_SIZE = 10_000

#: GA4's hard per-request maximum. Asking for more is not an error, it is simply
#: ignored, which is why we clamp instead of trusting the caller.
MAX_PAGE_SIZE = 250_000

#: How many rows one ``fetch`` will accumulate across pages before it stops and
#: declares itself truncated. Generous enough that no realistic daily report hits
#: it, low enough that a misbehaving vendor cannot exhaust memory.
DEFAULT_MAX_ROWS = 1_000_000

#: Quota buckets checked on every response, in the order they are reported. A
#: bucket counts as exhausted only when something was consumed *and* nothing
#: remains: an unset proto ``PropertyQuota`` is all zeros, and reading that as
#: "exhausted" would fail every request against a vendor that omits the block.
_QUOTA_BUCKETS = (
    "tokens_per_day",
    "tokens_per_hour",
    "tokens_per_project_per_hour",
    "concurrent_requests",
)

#: Network-level failures worth retrying. Anything else propagates unchanged —
#: an unexpected exception is a bug and must not be laundered into a vendor error.
_TRANSPORT_ERRORS = (TimeoutError, ConnectionError, OSError)

#: First backoff delay between vendor attempts, in seconds. Attempt *n* waits
#: ``_RETRY_BASE_DELAY * 2**n``, bounded by ``app.analytics.http.MAX_RETRY_DELAY``.
_RETRY_BASE_DELAY = 1.0


def _vendor_retry_after(exc: BaseException) -> float | None:
    """Best-effort ``Retry-After`` (seconds) from a vendor exception.

    Duck-typed on purpose: what a google-api-core error exposes depends on the
    transport it came from. A REST-derived ``GoogleAPICallError`` carries the
    HTTP response (``exc.response.headers``); some clients expose the headers or
    a parsed delay directly. Anything unrecognised returns ``None`` and the
    caller falls back to exponential backoff — a missing hint is normal, and
    guessing one would be worse than not having it.
    """
    direct = getattr(exc, "retry_after", None)
    if isinstance(direct, (int, float)) and not isinstance(direct, bool):
        return max(float(direct), 0.0)

    for holder in (getattr(exc, "response", None), exc):
        headers = getattr(holder, "headers", None)
        if isinstance(headers, Mapping):
            seconds = retry_after_seconds(headers)
            if seconds is not None:
                return seconds
    return None


def _map_client_error(exc: Exception) -> AnalyticsError | None:
    """Map a google-api-core exception onto the taxonomy, or ``None`` if unknown.

    ``GoogleAPICallError`` subclasses carry the HTTP status in ``.code``, so the
    status→error mapping is the one already written for the raw-HTTP path
    (:func:`app.analytics.http.classify_response`). One mapping, two transports.
    """
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code >= 300:
        return classify_response(Resp(status=code, headers={}, body=str(exc).encode()))
    if isinstance(exc, _TRANSPORT_ERRORS):
        return AnalyticsTransientError(f"GA4 request failed at the transport level: {exc}")
    return None


def _period_bounds(spec: GA4ReportSpec, period: str) -> tuple[str, str]:
    """Return the inclusive ``(start_date, end_date)`` a period covers.

    Raises:
        AnalyticsError: the period does not match the report's grain.
    """
    try:
        if spec.grain == "monthly":
            year, month = (int(part) for part in period.split("-", 1))
            last = calendar.monthrange(year, month)[1]
            return (
                dt.date(year, month, 1).isoformat(),
                dt.date(year, month, last).isoformat(),
            )
        day = dt.date.fromisoformat(period)
    except (TypeError, ValueError) as exc:
        raise AnalyticsError(
            f"invalid {spec.grain} period {period!r} for GA4 report {spec.name!r}: {exc}"
        ) from exc
    return day.isoformat(), day.isoformat()


def _parse_ga4_date(raw: str) -> dt.date:
    """Parse GA4's ``YYYYMMDD`` date dimension."""
    try:
        return dt.date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
    except (IndexError, TypeError, ValueError) as exc:
        raise AnalyticsError(f"GA4 returned an unparseable date value {raw!r}") from exc


def _coerce(field: GA4Field, raw: str) -> Any:
    """Coerce one raw GA4 string into the fact tables' Python type."""
    value = (raw or "").strip()
    if field.kind == "date":
        return _parse_ga4_date(value)
    if field.kind == "str":
        return value
    if not value:
        # GA4 omits nothing here, but an empty metric must read as a genuine zero
        # rather than blow up a whole period's collection.
        return 0 if field.kind == "int" else Decimal("0")
    try:
        if field.kind == "int":
            return int(value) if value.isdigit() else int(Decimal(value))
        return Decimal(value)
    except (ArithmeticError, InvalidOperation, ValueError) as exc:
        raise AnalyticsError(
            f"GA4 returned a non-numeric value {raw!r} for {field.api_name}"
        ) from exc


def _positions(headers: Any, expected: list[str], label: str) -> list[int]:
    """Return, for each expected field, its index in the vendor's header list.

    GA4 returns headers in the order requested today, but relying on that makes a
    silent column swap possible if it ever stops being true — and a swapped
    ``sessions``/``activeUsers`` pair is indistinguishable from real data once
    stored. When headers are absent (some fixtures, some transports) positional
    order is the only thing available and is used as-is.
    """
    names = [getattr(header, "name", "") for header in (headers or [])]
    if not names:
        return list(range(len(expected)))
    missing = [name for name in expected if name not in names]
    if missing:
        raise AnalyticsError(f"GA4 response is missing expected {label}(s): {', '.join(missing)}")
    return [names.index(name) for name in expected]


class GA4Adapter(AnalyticsSourceAdapter):
    """Reads the five GA4 reports for one connection's properties.

    Args:
        client: An object exposing ``await run_report(request=...)``. ``None``
            (production) builds a ``BetaAnalyticsDataAsyncClient`` in
            :meth:`connect` from the decrypted service-account JSON.
        page_size: Rows requested per call, clamped to ``MAX_PAGE_SIZE``.
        max_rows: Rows accumulated per ``fetch`` before declaring truncation.
        attempts: Vendor attempts per request before a transient failure is
            reported. ``None`` reads ``settings.analytics_http_attempts``.
        retry_base_delay: First backoff delay in seconds (see
            :data:`_RETRY_BASE_DELAY`).
        sleep: Injected delay function, so no test waits on the wall clock.
    """

    def __init__(
        self,
        client: Any | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_rows: int = DEFAULT_MAX_ROWS,
        attempts: int | None = None,
        retry_base_delay: float = _RETRY_BASE_DELAY,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._client = client
        self._injected_client = client is not None
        self._page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        self._max_rows = max(1, int(max_rows))
        # Read at construction, not import: the setting is validated at startup
        # and the adapter is built per collection run.
        resolved_attempts = settings.analytics_http_attempts if attempts is None else attempts
        self._attempts = max(1, int(resolved_attempts))
        self._retry_base_delay = max(0.0, float(retry_base_delay))
        self._sleep = sleep
        self._config: GA4Config | None = None

    # -- DataSourceAdapter ------------------------------------------------

    @property
    def source_type(self) -> str:
        return "ga4"

    async def connect(self, config: ConnectionConfig) -> None:
        """Parse the connection's knobs and make sure a client exists.

        Raises:
            AnalyticsError: the knobs are unusable (no property id, bad backfill).
            AnalyticsAuthError: no client was injected and the credential is
                missing or malformed.
        """
        self._config = GA4Config.from_connection_config(config)
        if self._injected_client:
            return

        secret = (config.extra or {}).get(CREDENTIAL_SECRET_KEY)
        if not secret:
            raise AnalyticsAuthError(
                "GA4 connection has no service-account credential — attach a vendor "
                "credential to this connection"
            )
        credentials = GA4Credentials.from_json(secret)
        self._client = self._build_client(credentials)
        logger.info(
            "GA4 adapter connected: %d property(ies), service account %s",
            len(self._config.property_ids),
            credentials.client_email,
        )

    @staticmethod
    def _build_client(credentials: GA4Credentials) -> Any:
        """Build the real async GA4 client. Imported lazily; overridable in tests."""
        from google.analytics.data_v1beta import BetaAnalyticsDataAsyncClient

        return BetaAnalyticsDataAsyncClient(credentials=credentials.build_credentials())

    async def disconnect(self) -> None:
        """Drop the client. Idempotent — the collect service may call it twice."""
        self._client = None
        self._injected_client = False
        self._config = None

    async def test_connection(self) -> bool:
        """Probe the first property with a one-row report.

        Returns ``False`` rather than raising for every vendor failure: an
        unshared property, a revoked key and a throttled quota are all "this
        connection does not work right now", and the caller shows one message.
        """
        try:
            config = self._require_config()
            spec = GA4_REPORTS[0]
            today = dt.date.today().isoformat()
            request = self._build_request(
                spec, config.property_ids[0], today, today, offset=0, limit=1
            )
            await self._run_report(request)
        except AnalyticsError as exc:
            logger.info("GA4 test_connection failed: %s", exc)
            return False
        return True

    # -- AnalyticsSourceAdapter -------------------------------------------

    def available_reports(self) -> list[ReportSpec]:
        return [report.to_spec() for report in GA4_REPORTS]

    async def fetch(self, report: str, period: str) -> AnalyticsReport:
        """Fetch one report for one period across every configured property.

        Rows from all properties are unioned into one result, each tagged with its
        ``property_id`` (the first column) so the fact-table natural key survives.
        """
        spec = REPORTS_BY_NAME.get(report)
        if spec is None:
            raise ValueError(
                f"unknown GA4 report {report!r}; expected one of {list(REPORTS_BY_NAME)}"
            )
        config = self._require_config()
        start_date, end_date = _period_bounds(spec, period)

        rows: list[list[Any]] = []
        truncated = False
        capped_properties: list[str] = []
        for property_id in config.property_ids:
            property_rows, property_truncated = await self._fetch_property(
                spec, property_id, start_date, end_date
            )
            rows.extend(property_rows)
            if property_truncated:
                truncated = True
                capped_properties.append(property_id)

        if not rows:
            raise AnalyticsEmpty(
                f"GA4 returned no rows for report {spec.name!r} on period {period!r}"
            )

        degraded: str | None = None
        if truncated:
            degraded = (
                f"GA4 report '{spec.name}' for {period} exceeded the {self._max_rows:,}-row "
                f"fetch cap on property/properties {', '.join(capped_properties)}; "
                f"only the first {len(rows):,} rows were collected."
            )
            logger.warning("GA4 fetch truncated: %s", degraded)

        return AnalyticsReport(
            columns=spec.columns,
            rows=rows,
            truncated=truncated,
            degraded=degraded,
        )

    # -- internals ---------------------------------------------------------

    def _require_config(self) -> GA4Config:
        if self._config is None or self._client is None:
            raise AnalyticsError("GA4 adapter is not connected — call connect() first")
        return self._config

    async def _fetch_property(
        self, spec: GA4ReportSpec, property_id: str, start_date: str, end_date: str
    ) -> tuple[list[list[Any]], bool]:
        """Page one property's rows. Returns ``(rows, truncated)`` (Δ1)."""
        rows: list[list[Any]] = []
        offset = 0
        row_count = 0
        while True:
            budget = self._max_rows - len(rows)
            if budget <= 0:
                # We stopped, not the vendor. Only claim truncation when the
                # vendor said there was genuinely more than we took.
                return rows, row_count > len(rows)

            limit = min(self._page_size, budget)
            response = await self._run_report(
                self._build_request(spec, property_id, start_date, end_date, offset, limit)
            )
            page = self._parse_rows(spec, property_id, response)
            rows.extend(page)
            row_count = int(getattr(response, "row_count", 0) or 0)

            if len(page) < limit:
                # A short page is the vendor saying "that is all there is".
                return rows, False
            offset += len(page)
            if row_count and len(rows) >= row_count:
                return rows, False

    def _build_request(
        self,
        spec: GA4ReportSpec,
        property_id: str,
        start_date: str,
        end_date: str,
        offset: int,
        limit: int,
    ) -> RunReportRequest:
        config = self._require_config()
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name=name) for name in spec.dimension_names],
            metrics=[Metric(name=name) for name in spec.metric_names],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            offset=offset,
            limit=limit,
            keep_empty_rows=spec.keep_empty_rows,  # Δ2
            return_property_quota=True,  # Δ3
        )
        if config.currency_code:
            request.currency_code = config.currency_code
        if spec.filter_dimension and config.event_names:
            request.dimension_filter = FilterExpression(
                filter=Filter(
                    field_name=spec.filter_dimension,
                    in_list_filter=Filter.InListFilter(
                        values=list(config.event_names), case_sensitive=True
                    ),
                )
            )
        return request

    async def _run_report(self, request: RunReportRequest) -> Any:
        """Call the vendor, translating its failures into the taxonomy and retrying.

        One page, one retry budget: only the failed request is repeated, so a
        blip on page seven never restarts the report from page one (the request
        carries its own ``offset``, which makes it safe to repeat).
        """
        client = self._client
        if client is None:  # pragma: no cover - guarded by _require_config
            raise AnalyticsError("GA4 adapter is not connected — call connect() first")

        hint: float | None = None

        async def attempt() -> Any:
            # The hint belongs to the attempt that just failed; clear it first so
            # a later failure without a header cannot inherit an earlier one.
            nonlocal hint
            hint = None
            try:
                response = await client.run_report(request=request)
            except AnalyticsError:
                raise
            except Exception as exc:
                mapped = _map_client_error(exc)
                if mapped is None:
                    # Not a vendor failure — a bug. It must surface as itself,
                    # unretried and unwrapped.
                    raise
                hint = _vendor_retry_after(exc)
                raise mapped from exc
            # Inside the retried attempt on purpose (Δ3): an exhausted bucket is
            # a retryable condition, and a quota window that rolls over between
            # attempts heals the very request that hit it.
            self._check_quota(getattr(response, "property_quota", None))
            return response

        return await retry_async(
            attempt,
            attempts=self._attempts,
            base_delay=self._retry_base_delay,
            sleep=self._sleep,
            retry_after=lambda: hint,
            label=f"GA4 runReport {request.property}",
        )

    @staticmethod
    def _check_quota(quota: Any) -> None:
        """Raise :class:`QuotaExhaustedError` when a reported bucket is spent (Δ3)."""
        if quota is None:
            return
        for bucket in _QUOTA_BUCKETS:
            status = getattr(quota, bucket, None)
            if status is None:
                continue
            consumed = int(getattr(status, "consumed", 0) or 0)
            remaining = int(getattr(status, "remaining", 0) or 0)
            if consumed <= 0:
                # Nothing consumed means the vendor did not populate this bucket;
                # an all-zero proto default must not read as exhaustion.
                continue
            if remaining <= 0:
                raise QuotaExhaustedError(
                    f"GA4 quota {bucket} is exhausted (consumed={consumed}, remaining=0)"
                )
            logger.debug("GA4 quota %s: %d remaining", bucket, remaining)

    @staticmethod
    def _parse_rows(spec: GA4ReportSpec, property_id: str, response: Any) -> list[list[Any]]:
        """Turn one response page into fact-table rows in ``spec.columns`` order."""
        raw_rows = list(getattr(response, "rows", None) or [])
        if not raw_rows:
            return []

        dim_positions = _positions(
            getattr(response, "dimension_headers", None), spec.dimension_names, "dimension"
        )
        metric_positions = _positions(
            getattr(response, "metric_headers", None), spec.metric_names, "metric"
        )

        parsed: list[list[Any]] = []
        for raw in raw_rows:
            dimension_values = raw.dimension_values
            metric_values = raw.metric_values
            row: list[Any] = [property_id]
            try:
                for field, index in zip(spec.dimensions, dim_positions, strict=True):
                    row.append(_coerce(field, dimension_values[index].value))
                for field, index in zip(spec.metrics, metric_positions, strict=True):
                    row.append(_coerce(field, metric_values[index].value))
            except IndexError as exc:
                raise AnalyticsError(
                    f"GA4 row for report {spec.name!r} has fewer values than headers"
                ) from exc
            parsed.append(row)
        return parsed
