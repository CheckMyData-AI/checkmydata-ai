"""Tests for the scheduled analytics collection service (T7 — spec §3.1, REQ-007/008).

The three properties that matter, in order:

1. **Per-period isolation.** One bad period must never take the run down with
   it. It is journalled ``failed``, it shows up in the outcome, and every other
   period still lands in its fact table.
2. **An auth/permission failure stops that report — and only that report.** The
   credential is wrong, so every remaining period of that report would fail the
   same way and burn quota proving it; the other reports still run because they
   might be readable with the same key (GA4 shares a key across reports but not
   necessarily the same property scopes, and a bad *report* is worth
   distinguishing from a bad *credential*). Both halves are asserted — an
   implementation that ``continue``s instead of stopping fails the first half,
   one that aborts the whole run fails the second.
3. **Rerunning is a no-op on the data.** The upsert is keyed on the fact
   tables' natural keys, so collecting the same day twice leaves one row.

The vendor is faked but the *report specs are real*: the fake builds its rows
from :data:`app.analytics.ga4.reports.GA4_REPORTS`, so the positional
column-to-fact-table mapping is exercised against the shipped specs and the
shipped models rather than against a convenient fiction. No network, no
credentials, no clock — ``today`` is injected.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every mapper
from app.analytics.base import AnalyticsReport, AnalyticsSourceAdapter, ReportSpec
from app.analytics.errors import (
    AnalyticsAuthError,
    AnalyticsEmpty,
    AnalyticsError,
    AnalyticsPermissionError,
    AnalyticsTransientError,
    QuotaExhaustedError,
)
from app.analytics.ga4.reports import GA4_REPORTS, REPORTS_BY_NAME, GA4ReportSpec
from app.connectors.base import ConnectionConfig
from app.models.analytics_ga4 import GA4GeoDaily, GA4OverviewDaily
from app.models.analytics_import import AnalyticsImport
from app.models.base import Base, enable_sqlite_fk
from app.models.connection import Connection
from app.models.project import Project
from app.services.analytics_collect_service import (
    ANALYTICS_SOURCE_TYPES,
    GA4_FACT_TABLES,
    AnalyticsCollectService,
    period_range,
)

PROPERTY_ID = "294380179"

#: "Today" for every test. Collection therefore ends on 2026-07-15 (yesterday).
TODAY = dt.date(2026, 7, 16)
YESTERDAY = dt.date(2026, 7, 15)

BACKFILL_DAYS = 5
#: 2026-07-11 … 2026-07-15
EXPECTED_DAYS = [(YESTERDAY - dt.timedelta(days=offset)).isoformat() for offset in range(4, -1, -1)]


# ---------------------------------------------------------------------------
# Fake vendor
# ---------------------------------------------------------------------------


def _sample_value(kind: str, column: str, period: str) -> Any:
    """One deterministic value of the right Python type for a spec field."""
    if kind == "date":
        return dt.date.fromisoformat(period)
    if kind == "str":
        return f"{column}-value"
    if kind == "int":
        return 7
    return Decimal("12.3400")


class FakeAdapter(AnalyticsSourceAdapter):
    """A vendor that answers from the real GA4 report specs.

    ``failures`` maps ``(report, period)`` — or ``(report, None)`` for "every
    period of this report" — onto the exception to raise instead of returning
    rows, which is how each isolation case is provoked.
    """

    def __init__(
        self,
        *,
        reports: tuple[GA4ReportSpec, ...] = GA4_REPORTS,
        failures: dict[tuple[str, str | None], Exception] | None = None,
        rows_per_period: int = 1,
        truncated_reports: frozenset[str] = frozenset(),
        connect_error: Exception | None = None,
    ) -> None:
        self._reports = reports
        self._failures = failures or {}
        self._rows_per_period = rows_per_period
        self._truncated_reports = truncated_reports
        self._connect_error = connect_error
        self.calls: list[tuple[str, str]] = []
        self.connected = False
        self.disconnect_calls = 0
        self.config: ConnectionConfig | None = None

    @property
    def source_type(self) -> str:
        return "ga4"

    async def connect(self, config: ConnectionConfig) -> None:
        if self._connect_error is not None:
            raise self._connect_error
        self.config = config
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False
        self.disconnect_calls += 1

    async def test_connection(self) -> bool:
        return True

    def available_reports(self) -> list[ReportSpec]:
        return [report.to_spec() for report in self._reports]

    async def fetch(self, report: str, period: str) -> AnalyticsReport:
        self.calls.append((report, period))
        failure = self._failures.get((report, period)) or self._failures.get((report, None))
        if failure is not None:
            raise failure
        spec = REPORTS_BY_NAME[report]
        rows = [
            [
                PROPERTY_ID,
                *(
                    _sample_value(field.kind, f"{field.column}{index}", period)
                    for field in spec.fields
                ),
            ]
            for index in range(self._rows_per_period)
        ]
        truncated = spec.name in self._truncated_reports
        return AnalyticsReport(
            columns=spec.columns,
            rows=rows,
            truncated=truncated,
            degraded=(f"GA4 report '{spec.name}' for {period} was capped." if truncated else None),
        )

    def periods_for(self, report: str) -> list[str]:
        return [period for name, period in self.calls if name == report]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_fk(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def connection_id(db: AsyncSession) -> str:
    project = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.commit()
    conn = Connection(
        project_id=project.id,
        name="ga4-prod",
        source_type="ga4",
        source_config_json=json.dumps(
            {"property_ids": [PROPERTY_ID], "backfill_days": BACKFILL_DAYS}
        ),
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn.id


def _service(adapter: FakeAdapter, *, tail: int = 0) -> AnalyticsCollectService:
    """A service wired to *adapter* with a frozen clock and an explicit tail."""
    return AnalyticsCollectService(
        adapter_factory=lambda conn: adapter,
        today=lambda: TODAY,
        refetch_tail_periods=tail,
    )


def _only(*names: str) -> tuple[GA4ReportSpec, ...]:
    return tuple(REPORTS_BY_NAME[name] for name in names)


async def _journal(db: AsyncSession, report: str) -> dict[str, AnalyticsImport]:
    rows = (
        (await db.execute(select(AnalyticsImport).where(AnalyticsImport.report == report)))
        .scalars()
        .all()
    )
    return {row.period: row for row in rows}


async def _count(db: AsyncSession, model: Any) -> int:
    return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


# ---------------------------------------------------------------------------
# period_range
# ---------------------------------------------------------------------------


class TestPeriodRange:
    def test_daily_window_ends_yesterday_never_today(self):
        """Today is always partial in GA4, so it is never asked for."""
        periods = period_range("daily", backfill_days=BACKFILL_DAYS, today=TODAY)

        assert periods == EXPECTED_DAYS
        assert periods[-1] == YESTERDAY.isoformat()
        assert TODAY.isoformat() not in periods

    def test_daily_window_length_equals_backfill_days(self):
        periods = period_range("daily", backfill_days=30, today=TODAY)

        assert len(periods) == 30
        assert periods[0] == (YESTERDAY - dt.timedelta(days=29)).isoformat()

    def test_monthly_window_is_deduplicated_year_months(self):
        periods = period_range("monthly", backfill_days=90, today=dt.date(2026, 3, 5))

        # 2025-12-05 … 2026-03-04 inclusive.
        assert periods == ["2025-12", "2026-01", "2026-02", "2026-03"]
        assert len(periods) == len(set(periods))

    def test_backfill_below_one_still_yields_yesterday(self):
        """A zero/negative knob must not produce an empty (silently idle) window."""
        assert period_range("daily", backfill_days=0, today=TODAY) == [YESTERDAY.isoformat()]


# ---------------------------------------------------------------------------
# Contract wiring
# ---------------------------------------------------------------------------


class TestReportTableContract:
    def test_every_ga4_report_has_a_fact_table(self):
        assert set(GA4_FACT_TABLES) == {spec.name for spec in GA4_REPORTS}

    def test_report_columns_match_the_fact_table_columns_exactly(self):
        """Drift between reports.py and the models would corrupt the upsert."""
        for spec in GA4_REPORTS:
            table = GA4_FACT_TABLES[spec.name]
            model_columns = {c.name for c in table.model.__table__.columns}
            assert set(spec.columns) | {"id", "connection_id", "fetched_at"} == model_columns, (
                f"report {spec.name!r} columns {spec.columns} do not match "
                f"{table.model.__tablename__}"
            )

    def test_key_columns_are_a_prefix_subset_of_the_report_columns(self):
        for spec in GA4_REPORTS:
            table = GA4_FACT_TABLES[spec.name]
            assert set(table.key_columns) <= set(spec.columns)

    def test_ga4_is_an_analytics_source_type(self):
        assert "ga4" in ANALYTICS_SOURCE_TYPES


# ---------------------------------------------------------------------------
# The collect loop
# ---------------------------------------------------------------------------


class TestCollect:
    async def test_happy_path_writes_every_period_and_journals_ok(
        self, db: AsyncSession, connection_id: str
    ):
        adapter = FakeAdapter(reports=_only("overview"))

        outcome = await _service(adapter).collect_in_session(db, connection_id)

        assert outcome.status == "ok"
        assert outcome.errors == []
        assert outcome.periods_ok == BACKFILL_DAYS
        assert outcome.rows_written == BACKFILL_DAYS
        assert await _count(db, GA4OverviewDaily) == BACKFILL_DAYS
        journal = await _journal(db, "overview")
        assert sorted(journal) == EXPECTED_DAYS
        assert {row.status for row in journal.values()} == {"ok"}

    async def test_row_values_land_in_the_right_columns(self, db: AsyncSession, connection_id: str):
        """Positional mapping is the upsert contract — prove it, don't assume it."""
        adapter = FakeAdapter(reports=_only("overview"))

        await _service(adapter).collect_in_session(db, connection_id)

        row = (
            (await db.execute(select(GA4OverviewDaily).where(GA4OverviewDaily.date == YESTERDAY)))
            .scalars()
            .one()
        )
        assert row.property_id == PROPERTY_ID
        assert row.connection_id == connection_id
        assert row.sessions == 7
        assert row.total_revenue == Decimal("12.3400")

    async def test_one_transient_period_fails_alone(self, db: AsyncSession, connection_id: str):
        """Per-period isolation: the other four days still land; outcome is partial."""
        broken = EXPECTED_DAYS[2]
        adapter = FakeAdapter(
            reports=_only("overview"),
            failures={("overview", broken): AnalyticsTransientError("GA4 said 503")},
        )

        outcome = await _service(adapter).collect_in_session(db, connection_id)

        assert outcome.status == "partial"
        assert outcome.periods_ok == BACKFILL_DAYS - 1
        assert outcome.rows_written == BACKFILL_DAYS - 1
        assert len(outcome.errors) == 1
        assert broken in outcome.errors[0]
        assert await _count(db, GA4OverviewDaily) == BACKFILL_DAYS - 1
        # Every period was attempted, and the broken one is journalled failed.
        assert adapter.periods_for("overview") == EXPECTED_DAYS
        journal = await _journal(db, "overview")
        assert journal[broken].status == "failed"
        assert "503" in (journal[broken].error or "")
        assert {p for p, row in journal.items() if row.status == "ok"} == set(EXPECTED_DAYS) - {
            broken
        }

    async def test_quota_exhaustion_is_isolated_to_its_period(
        self, db: AsyncSession, connection_id: str
    ):
        adapter = FakeAdapter(
            reports=_only("overview"),
            failures={("overview", EXPECTED_DAYS[0]): QuotaExhaustedError("tokens_per_day spent")},
        )

        outcome = await _service(adapter).collect_in_session(db, connection_id)

        assert outcome.status == "partial"
        assert adapter.periods_for("overview") == EXPECTED_DAYS

    async def test_bare_analytics_error_is_journalled_not_raised(
        self, db: AsyncSession, connection_id: str
    ):
        """``fetch`` may raise a bare ``AnalyticsError`` for an unusable payload."""
        adapter = FakeAdapter(
            reports=_only("overview"),
            failures={("overview", EXPECTED_DAYS[1]): AnalyticsError("unparseable date '20xx'")},
        )

        outcome = await _service(adapter).collect_in_session(db, connection_id)

        assert outcome.status == "partial"
        assert adapter.periods_for("overview") == EXPECTED_DAYS
        journal = await _journal(db, "overview")
        assert journal[EXPECTED_DAYS[1]].status == "failed"

    async def test_empty_period_is_journalled_empty_and_not_retried(
        self, db: AsyncSession, connection_id: str
    ):
        quiet_day = EXPECTED_DAYS[0]
        adapter = FakeAdapter(
            reports=_only("overview"),
            failures={("overview", quiet_day): AnalyticsEmpty("no rows")},
        )

        outcome = await _service(adapter).collect_in_session(db, connection_id)

        assert outcome.status == "ok"  # an empty period is not an error
        assert outcome.periods_empty == 1
        assert outcome.periods_ok == BACKFILL_DAYS - 1
        assert (await _journal(db, "overview"))[quiet_day].status == "empty"

        # A second run (tail=0) must not ask for it again — a genuinely quiet
        # day is finished, not broken.
        adapter.calls.clear()
        await _service(adapter).collect_in_session(db, connection_id)
        assert adapter.periods_for("overview") == []

    async def test_failed_period_is_retried_on_the_next_run(
        self, db: AsyncSession, connection_id: str
    ):
        broken = EXPECTED_DAYS[1]
        adapter = FakeAdapter(
            reports=_only("overview"),
            failures={("overview", broken): AnalyticsTransientError("boom")},
        )
        await _service(adapter).collect_in_session(db, connection_id)

        healed = FakeAdapter(reports=_only("overview"))
        outcome = await _service(healed).collect_in_session(db, connection_id)

        assert healed.periods_for("overview") == [broken]
        assert outcome.status == "ok"
        assert (await _journal(db, "overview"))[broken].status == "ok"
        assert (await _journal(db, "overview"))[broken].error is None

    # -- the auth rule, both halves --------------------------------------

    async def test_auth_error_stops_that_report(self, db: AsyncSession, connection_id: str):
        """A wrong credential must not be re-proved once per remaining period."""
        adapter = FakeAdapter(
            reports=_only("overview", "geo"),
            failures={("overview", None): AnalyticsAuthError("401 invalid_grant")},
        )

        outcome = await _service(adapter).collect_in_session(db, connection_id)

        # Exactly one overview fetch: the loop broke out of the report.
        assert adapter.periods_for("overview") == [EXPECTED_DAYS[0]]
        journal = await _journal(db, "overview")
        assert list(journal) == [EXPECTED_DAYS[0]]
        assert journal[EXPECTED_DAYS[0]].status == "failed"
        assert outcome.status == "partial"

    async def test_auth_error_in_one_report_leaves_the_others_running(
        self, db: AsyncSession, connection_id: str
    ):
        adapter = FakeAdapter(
            reports=_only("overview", "geo"),
            failures={("overview", None): AnalyticsAuthError("401 invalid_grant")},
        )

        outcome = await _service(adapter).collect_in_session(db, connection_id)

        assert adapter.periods_for("geo") == EXPECTED_DAYS
        assert await _count(db, GA4GeoDaily) == BACKFILL_DAYS
        assert outcome.rows_written == BACKFILL_DAYS
        assert outcome.status == "partial"

    async def test_permission_error_stops_that_report_too(
        self, db: AsyncSession, connection_id: str
    ):
        adapter = FakeAdapter(
            reports=_only("overview", "geo"),
            failures={("overview", None): AnalyticsPermissionError("403 not shared")},
        )

        await _service(adapter).collect_in_session(db, connection_id)

        assert adapter.periods_for("overview") == [EXPECTED_DAYS[0]]
        assert adapter.periods_for("geo") == EXPECTED_DAYS

    # -- idempotency ------------------------------------------------------

    async def test_rerun_writes_no_duplicate_rows(self, db: AsyncSession, connection_id: str):
        adapter = FakeAdapter(reports=_only("overview", "geo"), rows_per_period=2)

        await _service(adapter, tail=2).collect_in_session(db, connection_id)
        first_overview = await _count(db, GA4OverviewDaily)
        first_geo = await _count(db, GA4GeoDaily)

        await _service(adapter, tail=2).collect_in_session(db, connection_id)

        assert await _count(db, GA4OverviewDaily) == first_overview
        assert await _count(db, GA4GeoDaily) == first_geo
        # One journal row per (report, period), not two.
        assert len(await _journal(db, "overview")) == BACKFILL_DAYS

    async def test_tail_periods_are_refetched_even_when_ok(
        self, db: AsyncSession, connection_id: str
    ):
        adapter = FakeAdapter(reports=_only("overview"))
        await _service(adapter, tail=2).collect_in_session(db, connection_id)

        adapter.calls.clear()
        await _service(adapter, tail=2).collect_in_session(db, connection_id)

        assert adapter.periods_for("overview") == EXPECTED_DAYS[-2:]

    # -- degradation ------------------------------------------------------

    async def test_truncated_report_persists_its_degraded_caveat(
        self, db: AsyncSession, connection_id: str
    ):
        """A capped fetch is still ``ok`` data — but the caveat has to survive."""
        adapter = FakeAdapter(reports=_only("overview"), truncated_reports=frozenset({"overview"}))

        outcome = await _service(adapter).collect_in_session(db, connection_id)

        assert outcome.status == "ok"
        row = (await _journal(db, "overview"))[EXPECTED_DAYS[0]]
        assert row.status == "ok"
        assert row.error is not None and "capped" in row.error

    # -- run-level failures ------------------------------------------------

    async def test_connect_failure_fails_the_run_without_fetching(
        self, db: AsyncSession, connection_id: str
    ):
        adapter = FakeAdapter(connect_error=AnalyticsAuthError("credential is not JSON"))

        outcome = await _service(adapter).collect_in_session(db, connection_id)

        assert outcome.status == "failed"
        assert outcome.rows_written == 0
        assert any("credential is not JSON" in error for error in outcome.errors)
        assert adapter.calls == []

    async def test_missing_connection_exits_cleanly(self, db: AsyncSession):
        """Deleted mid-collect: resolve first, exit without inventing a failure."""
        outcome = await _service(FakeAdapter()).collect_in_session(db, "does-not-exist")

        assert outcome.status == "ok"
        assert outcome.rows_written == 0
        assert outcome.errors == []

    async def test_non_analytics_connection_is_rejected(self, db: AsyncSession):
        project = Project(name="p")
        db.add(project)
        await db.commit()
        conn = Connection(
            project_id=project.id, name="pg", source_type="database", db_type="postgres"
        )
        db.add(conn)
        await db.commit()

        outcome = await _service(FakeAdapter()).collect_in_session(db, conn.id)

        assert outcome.status == "failed"
        assert any("not an analytics source" in error for error in outcome.errors)

    async def test_adapter_is_always_disconnected(self, db: AsyncSession, connection_id: str):
        adapter = FakeAdapter(
            reports=_only("overview"),
            failures={("overview", None): AnalyticsTransientError("boom")},
        )

        await _service(adapter).collect_in_session(db, connection_id)

        assert adapter.disconnect_calls == 1
        assert adapter.connected is False

    async def test_unknown_report_does_not_abort_the_run(
        self, db: AsyncSession, connection_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        """A report with no fact table is a wiring bug — report it, keep going."""
        rogue = GA4ReportSpec(
            name="rogue",
            grain="daily",
            description="not mapped to any table",
            dimensions=REPORTS_BY_NAME["overview"].dimensions,
            metrics=REPORTS_BY_NAME["overview"].metrics,
        )
        monkeypatch.setitem(REPORTS_BY_NAME, "rogue", rogue)
        adapter = FakeAdapter(reports=(rogue, REPORTS_BY_NAME["geo"]))

        outcome = await _service(adapter).collect_in_session(db, connection_id)

        assert outcome.status == "partial"
        assert any("rogue" in error for error in outcome.errors)
        assert await _count(db, GA4GeoDaily) == BACKFILL_DAYS

    async def test_config_carries_the_decrypted_secret_and_knobs(
        self, db: AsyncSession, connection_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The adapter is handed the plaintext credential, never the ciphertext."""
        from app.analytics.ga4.config import CREDENTIAL_SECRET_KEY, SOURCE_CONFIG_KEY
        from app.models.vendor_credential import VendorCredential

        adapter = FakeAdapter(reports=_only("overview"))
        service = _service(adapter)

        captured: list[str] = []

        async def fake_secret(_session, credential_id):
            captured.append(credential_id)
            return '{"client_email": "sa@x.iam"}'

        monkeypatch.setattr(service, "_resolve_secret", fake_secret)
        credential = VendorCredential(
            name="ga4-sa", provider="ga4", secret_encrypted="ciphertext", fingerprint="abc123"
        )
        db.add(credential)
        await db.commit()
        conn = await db.get(Connection, connection_id)
        assert conn is not None
        conn.vendor_credential_id = credential.id
        await db.commit()

        await service.collect_in_session(db, connection_id)

        assert captured == [credential.id]
        assert adapter.config is not None
        assert adapter.config.extra[CREDENTIAL_SECRET_KEY] == '{"client_email": "sa@x.iam"}'
        assert adapter.config.extra[SOURCE_CONFIG_KEY]["property_ids"] == [PROPERTY_ID]
        assert adapter.config.connection_id == connection_id
        # No fabricated database endpoint on an analytics connection.
        assert adapter.config.db_host == ""
        assert adapter.config.db_port == 0


# ---------------------------------------------------------------------------
# The pipeline plugin
# ---------------------------------------------------------------------------


class TestAnalyticsPipeline:
    """The plugin face of the same collection: registry wiring and status."""

    def test_every_analytics_source_type_resolves_to_the_pipeline(self):
        from app.pipelines.analytics_pipeline import AnalyticsPipeline
        from app.pipelines.registry import get_pipeline

        for source_type in ANALYTICS_SOURCE_TYPES:
            assert isinstance(get_pipeline(source_type), AnalyticsPipeline)

    async def test_index_reports_a_partial_run_as_successful_but_not_clean(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Rows landed, so the step succeeded — but the errors must travel with it."""
        import app.services.analytics_collect_service as collect_mod
        from app.analytics.outcome import CollectOutcome
        from app.pipelines.analytics_pipeline import AnalyticsPipeline
        from app.pipelines.base import PipelineContext

        class FakeService:
            async def collect(self, connection_id: str):
                return CollectOutcome(rows_written=12, periods_ok=3, errors=["quota spent"])

        monkeypatch.setattr(collect_mod, "AnalyticsCollectService", FakeService)

        result = await AnalyticsPipeline().index(
            "conn-1", PipelineContext(project_id="p1", workflow_id="wf1")
        )

        assert result.success is True
        assert result.items_processed == 12
        assert result.error == "quota spent"
        assert result.metadata["status"] == "partial"

    async def test_index_reports_a_failed_run_as_unsuccessful(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import app.services.analytics_collect_service as collect_mod
        from app.analytics.outcome import CollectOutcome
        from app.pipelines.analytics_pipeline import AnalyticsPipeline
        from app.pipelines.base import PipelineContext

        class FakeService:
            async def collect(self, connection_id: str):
                return CollectOutcome(errors=["401 invalid_grant"])

        monkeypatch.setattr(collect_mod, "AnalyticsCollectService", FakeService)

        result = await AnalyticsPipeline().index(
            "conn-1", PipelineContext(project_id="p1", workflow_id="wf1")
        )

        assert result.success is False
        assert result.error == "401 invalid_grant"

    async def test_index_survives_an_exploding_service(self, monkeypatch: pytest.MonkeyPatch):
        import app.services.analytics_collect_service as collect_mod
        from app.pipelines.analytics_pipeline import AnalyticsPipeline
        from app.pipelines.base import PipelineContext

        class ExplodingService:
            async def collect(self, connection_id: str):
                raise RuntimeError("database is on fire")

        monkeypatch.setattr(collect_mod, "AnalyticsCollectService", ExplodingService)

        result = await AnalyticsPipeline().index(
            "conn-1", PipelineContext(project_id="p1", workflow_id="wf1")
        )

        assert result.success is False
        assert "on fire" in (result.error or "")

    async def test_status_distinguishes_collected_from_never_collected(
        self, db: AsyncSession, connection_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        import app.models.base as base_mod
        from app.pipelines.analytics_pipeline import AnalyticsPipeline

        adapter = FakeAdapter(reports=_only("overview"))
        await _service(adapter).collect_in_session(db, connection_id)

        class _Factory:
            def __call__(self):
                return _PassthroughSession(db)

        monkeypatch.setattr(base_mod, "async_session_factory", _Factory())
        pipeline = AnalyticsPipeline()

        collected = await pipeline.get_status(connection_id)
        never = await pipeline.get_status("some-other-connection")

        assert collected.is_indexed is True
        assert collected.items_count == BACKFILL_DAYS
        assert collected.is_stale is False
        assert collected.last_indexed_at is not None
        assert never.is_indexed is False
        assert never.is_stale is True
        assert never.last_indexed_at is None

    async def test_sync_with_code_is_a_declared_no_op(self):
        from app.pipelines.analytics_pipeline import AnalyticsPipeline
        from app.pipelines.base import PipelineContext

        pipeline = AnalyticsPipeline()
        result = await pipeline.sync_with_code(
            "conn-1", PipelineContext(project_id="p1", workflow_id="wf1")
        )

        assert result.success is True
        assert pipeline.get_agent_tools() == []


class _PassthroughSession:
    """Hands the test's own session to code that opens its own via the factory."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_exc: Any) -> bool:
        return False
