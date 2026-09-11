"""Seven ways the analytics path reported something other than what happened.

P1 row 12, the collection half; ANA-01/02/03/04/07/11/12. Every one is an honesty
defect rather than a crash: the data reaches the user, labelled wrongly.

- **ANA-04 / ANA-03 — the taxonomy had no class for "this request can never work".**
  404 became `AnalyticsEmpty`, whose own docstring says the period is DONE and never
  retried — so a deleted property records every period as *collected, and it was zero*,
  the connection badge says `ok`, and the agent answers over the fabricated zero the
  module exists to prevent. 400 became the base `AnalyticsError`, which the collector
  isolates and continues — so a retired metric re-issues 30 doomed requests a day,
  for ever.
- **ANA-11 — one property's failure discarded every other property's rows.** `fetch`
  accumulates across `property_ids` and any raise propagates out of the whole loop.
- **ANA-02 — the request that legally spends the last quota token was destroyed.**
  `_check_quota` ran inside the retried attempt and raised before `return response`,
  so a complete 2xx page was thrown away and two more doomed calls were issued at
  exactly the moment quota was scarcest.
- **ANA-12 — a refetch overwrote but never deleted.** The tail refetch exists because
  vendors revise, and GA4's revisions include removals; a dimension value that vanished
  from the fresh response kept counting into totals presented as real measurements.
- **ANA-01 — a quiet day was reported as "the vendor truncated this period".** The
  `error` column carries two meanings and every reader keyed the truncation caveat on
  `status in DONE_STATUSES and error`, which a correct `empty` row satisfies.
- **ANA-07 — a figure with no window behind it shipped bare.** Grounding is satisfied
  by `list_reports()`/`coverage()`, which return no measurement at all, and every
  honesty gate downstream is keyed on a window that was never opened.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.analytics.errors import (
    RETRYABLE_ERRORS,
    AnalyticsEmpty,
    AnalyticsError,
    AnalyticsInvalidRequestError,
    QuotaExhaustedError,
)
from app.analytics.http import Resp, classify_response


class TestARequestThatCanNeverWorkStopsTheReport:
    """ANA-03 / ANA-04."""

    def test_404_is_not_an_empty_period(self) -> None:
        err = classify_response(Resp(status=404, headers={}, body=b"NotFound"))
        assert not isinstance(err, AnalyticsEmpty), (
            "404 maps to AnalyticsEmpty, which journals the period `empty` — a DONE "
            "status that never refills. A deleted property therefore reads as "
            "'collected, and it was zero' for ever, and the connection badge says ok "
            "(ANA-04)"
        )
        assert isinstance(err, AnalyticsInvalidRequestError)

    def test_400_is_not_a_per_period_accident(self) -> None:
        err = classify_response(Resp(status=400, headers={}, body=b"INVALID_ARGUMENT"))
        assert isinstance(err, AnalyticsInvalidRequestError), (
            "400 maps to the base AnalyticsError, which the collector isolates and "
            "continues — so a retired GA4 metric re-issues every period in the window, "
            "once a day, indefinitely (ANA-03)"
        )

    def test_it_is_never_retried(self) -> None:
        assert not issubclass(AnalyticsInvalidRequestError, RETRYABLE_ERRORS), (
            "an invalid request cannot be fixed by repeating it"
        )

    def test_an_empty_period_is_still_possible(self) -> None:
        """The class keeps its one honest meaning: a 2xx that carried no rows."""
        assert issubclass(AnalyticsEmpty, AnalyticsError)
        assert classify_response(Resp(status=200, headers={}, body=b"")) is None

    def test_the_collector_stops_the_report_on_it(self) -> None:
        import inspect

        from app.services.analytics_collect_service import AnalyticsCollectService

        source = inspect.getsource(AnalyticsCollectService._collect_report)
        stop_clause = source.split("Configuration error")[0]
        assert "AnalyticsInvalidRequestError" in stop_clause, (
            "the stop-the-report branch is keyed on the exception class and an "
            "invalid request is not in it, so the whole window is re-attempted every "
            "run (ANA-03)"
        )


class TestOnePropertysFailureDoesNotDiscardAnother:
    """ANA-11."""

    @pytest.mark.asyncio
    async def test_a_healthy_property_survives_a_dead_one(self) -> None:
        from app.analytics.ga4.adapter import GA4Adapter
        from app.analytics.ga4.config import GA4Config

        adapter = GA4Adapter()
        adapter._config = GA4Config(property_ids=("good", "dead"))
        adapter._client = object()

        async def fake_fetch_property(spec, property_id, start, end):
            if property_id == "dead":
                raise AnalyticsInvalidRequestError("HTTP 404: property not found")
            return [[property_id, dt.date(2026, 9, 1), 5, 5, 5, 5, 0.0, 0]], False

        adapter._fetch_property = fake_fetch_property  # type: ignore[method-assign]

        report = await adapter.fetch("overview", "2026-09-01")

        assert report.rows, (
            "a raise from one property propagates out of the whole loop and discards "
            "every other property's already-fetched rows — and the period is then "
            "journalled `empty`, a DONE status that never refills (ANA-11)"
        )
        assert report.degraded and "dead" in report.degraded, (
            "the surviving rows are published with no sign that a property was lost"
        )

    @pytest.mark.asyncio
    async def test_every_property_failing_still_raises(self) -> None:
        from app.analytics.ga4.adapter import GA4Adapter
        from app.analytics.ga4.config import GA4Config

        adapter = GA4Adapter()
        adapter._config = GA4Config(property_ids=("a", "b"))
        adapter._client = object()

        async def all_dead(spec, property_id, start, end):
            raise AnalyticsInvalidRequestError("HTTP 404")

        adapter._fetch_property = all_dead  # type: ignore[method-assign]

        with pytest.raises(AnalyticsInvalidRequestError):
            await adapter.fetch("overview", "2026-09-01")


class _Request:
    """Only the label needs a `.property`; the stub client ignores the rest."""

    property = "properties/1"


class TestASuccessfulPageIsNeverDiscarded:
    """ANA-02."""

    @pytest.mark.asyncio
    async def test_the_page_that_spends_the_last_token_is_kept(self) -> None:
        from app.analytics.ga4.adapter import GA4Adapter

        class _Bucket:
            consumed = 10
            remaining = 0

        class _Quota:
            tokens_per_day = _Bucket()

        class _Response:
            property_quota = _Quota()
            rows = []
            row_count = 0

        calls = 0

        class _Client:
            async def run_report(self, *, request):
                nonlocal calls
                calls += 1
                return _Response()

        adapter = GA4Adapter()
        adapter._client = _Client()

        response = await adapter._run_report(_Request())

        assert response is not None, (
            "GA4's `remaining` is what is left AFTER this request, so remaining==0 is "
            "exactly the request that succeeded and emptied the bucket — and its rows "
            "were thrown away inside the retried attempt (ANA-02)"
        )
        assert calls == 1, (
            f"{calls} vendor calls were made for one page: the raise is retryable, so "
            "two more doomed requests are issued at the moment quota is scarcest"
        )

    @pytest.mark.asyncio
    async def test_the_next_request_is_refused_instead(self) -> None:
        from app.analytics.ga4.adapter import GA4Adapter

        class _Client:
            async def run_report(self, *, request):  # pragma: no cover - must not run
                raise AssertionError("a request was issued against a bucket known empty")

        adapter = GA4Adapter()
        adapter._client = _Client()
        adapter._quota_exhausted = {"1": "tokens_per_day"}

        with pytest.raises(QuotaExhaustedError):
            await adapter._run_report(_Request())


class TestARefetchRemovesWhatTheVendorRemoved:
    """ANA-12."""

    @pytest.mark.asyncio
    async def test_a_row_the_vendor_revised_away_does_not_survive(self) -> None:
        import uuid

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.analytics.base import AnalyticsReport
        from app.models.analytics_ga4 import GA4GeoDaily
        from app.models.base import Base
        from app.services.analytics_collect_service import GA4_FACT_TABLES, AnalyticsCollectService

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        service = AnalyticsCollectService()
        table = GA4_FACT_TABLES["geo"]
        columns = ["property_id", "date", "country", "sessions", "active_users"]
        connection_id = uuid.uuid4().hex

        def report(countries: list[str]) -> AnalyticsReport:
            return AnalyticsReport(
                columns=columns,
                rows=[["p1", dt.date(2026, 9, 1), c, 5, 5] for c in countries],
            )

        async with sm() as session:
            await service._upsert(session, connection_id, table, report(["US", "SPAM"]))
            await service._upsert(session, connection_id, table, report(["US"]))
            rows = (await session.execute(select(GA4GeoDaily.country))).scalars().all()
        await engine.dispose()

        assert sorted(rows) == ["US"], (
            "the tail refetch exists because vendors revise, and GA4's revisions include "
            "removals (spam-filtered events, reattributed geo). The upsert is INSERT … "
            "ON CONFLICT DO UPDATE with no delete, so a dimension value that vanished "
            f"from the fresh response keeps counting into totals presented as real "
            f"measurements. Stored: {sorted(rows)} (ANA-12)"
        )

    @pytest.mark.asyncio
    async def test_a_property_that_did_not_report_is_left_alone(self) -> None:
        """The sweep is scoped to what the fresh response covered.

        With per-property isolation (ANA-11) a failed property contributes no rows,
        and deleting its history because it is absent would turn one outage into
        data loss.
        """
        import uuid

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.analytics.base import AnalyticsReport
        from app.models.analytics_ga4 import GA4GeoDaily
        from app.models.base import Base
        from app.services.analytics_collect_service import GA4_FACT_TABLES, AnalyticsCollectService

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        service = AnalyticsCollectService()
        table = GA4_FACT_TABLES["geo"]
        columns = ["property_id", "date", "country", "sessions", "active_users"]
        connection_id = uuid.uuid4().hex

        def report(pairs: list[tuple[str, str]]) -> AnalyticsReport:
            return AnalyticsReport(
                columns=columns,
                rows=[[pid, dt.date(2026, 9, 1), c, 5, 5] for pid, c in pairs],
            )

        async with sm() as session:
            await service._upsert(
                session, connection_id, table, report([("p1", "US"), ("p2", "DE")])
            )
            await service._upsert(session, connection_id, table, report([("p1", "US")]))
            rows = (
                await session.execute(select(GA4GeoDaily.property_id, GA4GeoDaily.country))
            ).all()
        await engine.dispose()

        assert sorted(tuple(r) for r in rows) == [("p1", "US"), ("p2", "DE")], (
            f"p2's row was swept although this fetch never covered p2. Stored: {rows}"
        )
