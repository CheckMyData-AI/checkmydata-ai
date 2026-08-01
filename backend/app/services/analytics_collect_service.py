"""Scheduled collection of analytics vendor reports into local fact tables.

Spec §3.1 (REQ-007, REQ-008). One run = one connection. For each report the
adapter offers, the service works out which periods are *expected*, asks the
journal which of those are still *pending*, fetches them one at a time, upserts
the rows into the matching ``ga4_*`` table and records the verdict — then
returns a :class:`~app.analytics.outcome.CollectOutcome` that tells the truth
about what happened.

Three rules shape the loop, and each exists because the obvious alternative
lies to the user:

**Per-period isolation.** A period that fails is journalled ``failed``, added to
the outcome's errors, and the run moves on. Letting one bad payload abort the
run would leave the remaining twenty-nine days uncollected with nothing but a
stack trace to say why.

**An auth or permission failure stops that report.** Those are configuration
errors (:mod:`app.analytics.errors`): the credential is wrong or the property
was never shared, so every remaining period would fail identically while
burning vendor quota to prove it. The *other* reports still run — a report
whose dimensions the credential cannot see is worth distinguishing from a
credential that works for nothing.

**Rerunning changes nothing.** Every write is an ``INSERT … ON CONFLICT DO
UPDATE`` on the fact table's natural key, so a period collected twice leaves
one row, and today's data can be safely refetched tomorrow when the vendor has
revised it (``analytics_refetch_tail_periods``).

The collection window always ends **yesterday**: today is partial at every
vendor, and a partial day stored as if it were final is indistinguishable from
a real slump.

Nothing here touches the network directly. The vendor adapter is injectable, so
the tests drive the whole loop — including the upsert against the real models —
without a credential or a socket.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import journal
from app.analytics.base import AnalyticsReport, AnalyticsSourceAdapter, Grain
from app.analytics.errors import (
    AnalyticsAuthError,
    AnalyticsEmpty,
    AnalyticsError,
    AnalyticsPermissionError,
)
from app.analytics.ga4.config import CREDENTIAL_SECRET_KEY, SOURCE_CONFIG_KEY
from app.analytics.outcome import CollectOutcome
from app.config import settings
from app.connectors.base import ConnectionConfig
from app.models.analytics_ga4 import (
    GA4EventDaily,
    GA4GeoDaily,
    GA4OverviewDaily,
    GA4PlatformDaily,
    GA4TrendDaily,
)
from app.models.connection import Connection

logger = logging.getLogger(__name__)

#: Every ``Connection.source_type`` served by an analytics adapter. The cron's
#: selection query, the pipeline registry and the agent's tool gating all read
#: this one tuple so a new vendor is added in exactly one place.
ANALYTICS_SOURCE_TYPES: tuple[str, ...] = ("ga4", "appstore", "googleplay")


@dataclass(frozen=True)
class FactTable:
    """Where one report's rows land, and what makes a row unique there.

    Attributes:
        model: The ORM model backing the report's fact table.
        key_columns: The natural key *besides* ``connection_id`` — together they
            are the table's UNIQUE constraint and therefore the upsert's
            conflict target. Everything else in the report's columns is payload
            and is overwritten on conflict.
    """

    model: type[Any]
    key_columns: tuple[str, ...]


#: GA4 report name -> fact table (spec §1.4). Keys must match
#: :data:`app.analytics.ga4.reports.GA4_REPORTS`; a unit test asserts both that
#: the sets agree and that each report's columns are exactly its table's
#: columns, because a silent mismatch would write the right numbers into the
#: wrong column.
GA4_FACT_TABLES: dict[str, FactTable] = {
    "overview": FactTable(GA4OverviewDaily, ("property_id", "date")),
    "geo": FactTable(GA4GeoDaily, ("property_id", "date", "country")),
    "platform": FactTable(GA4PlatformDaily, ("property_id", "date", "platform", "device_category")),
    "trend": FactTable(GA4TrendDaily, ("property_id", "date", "channel_group")),
    "events": FactTable(GA4EventDaily, ("property_id", "date", "event_name")),
}

#: Source type -> its report/fact-table map. ``appstore``/``googleplay`` are
#: accepted source types (m1/m2) but have no tables yet; asking for one raises
#: a clear error rather than writing nowhere.
FACT_TABLES_BY_SOURCE: dict[str, dict[str, FactTable]] = {"ga4": GA4_FACT_TABLES}

#: Dialects with a native ``ON CONFLICT DO UPDATE``. Mirrors the journal's
#: approach (:mod:`app.analytics.journal`) so both writers behave identically on
#: Postgres (production) and SQLite (dev).
_UPSERT_DIALECTS = frozenset({"postgresql", "sqlite"})


def _dialect_name(session: AsyncSession) -> str:
    """The bound dialect (``postgresql`` / ``sqlite`` / …)."""
    return str(session.get_bind().dialect.name)


def _upsert_insert(dialect: str) -> Any:
    """The dialect's ``ON CONFLICT DO UPDATE``-capable ``insert`` constructor.

    ``Any`` on purpose: the two constructors are structurally identical for this
    use but nominally unrelated types. Only dialects in :data:`_UPSERT_DIALECTS`
    reach here.
    """
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


def period_range(grain: Grain, *, backfill_days: int, today: dt.date) -> list[str]:
    """The periods a report is expected to hold, oldest first.

    The window always ends **yesterday**: vendors do not finalise the current
    day, and a half-collected today looks exactly like a crash in traffic.

    Args:
        grain: ``"daily"`` → ``YYYY-MM-DD`` periods; ``"monthly"`` → the
            de-duplicated ``YYYY-MM`` months the same window touches. One report
            never mixes the two (the journal keys on the string).
        backfill_days: Width of the window in days. Values below 1 are clamped
            to 1 so a misconfigured connection still collects yesterday rather
            than going silently idle.
        today: The current date in the scheduler's timezone.

    Returns:
        Sorted, de-duplicated period strings.
    """
    end = today - dt.timedelta(days=1)
    days = max(1, backfill_days)
    start = end - dt.timedelta(days=days - 1)

    if grain == "monthly":
        months: list[str] = []
        cursor = start.replace(day=1)
        while cursor <= end:
            months.append(f"{cursor.year:04d}-{cursor.month:02d}")
            cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return months

    return [(start + dt.timedelta(days=offset)).isoformat() for offset in range(days)]


def build_adapter(source_type: str) -> AnalyticsSourceAdapter:
    """Instantiate the vendor adapter for ``source_type``.

    The vendor packages are imported lazily so that importing this module (which
    the cron, the pipeline registry and the agent all do) does not drag in
    ``google-analytics-data``.

    Raises:
        ValueError: no adapter is registered for this source type.
    """
    if source_type == "ga4":
        from app.analytics.ga4.adapter import GA4Adapter

        return GA4Adapter()
    raise ValueError(
        f"no analytics adapter for source_type {source_type!r}; "
        f"supported: {sorted(FACT_TABLES_BY_SOURCE)}"
    )


def _decode_source_config(conn: Connection) -> dict[str, Any]:
    """Decode ``source_config_json``; a corrupt blob must not 500 the whole run."""
    if not conn.source_config_json:
        return {}
    try:
        parsed = json.loads(conn.source_config_json)
    except (TypeError, ValueError):
        logger.warning(
            "Connection %s has unparseable source_config_json; treating it as empty",
            conn.id[:8],
        )
        return {}
    return parsed if isinstance(parsed, dict) else {}


class AnalyticsCollectService:
    """Collects one analytics connection's reports into its fact tables.

    Args:
        adapter_factory: Builds the vendor adapter for a connection. Injected in
            tests so the whole loop runs against a fake vendor; production uses
            :func:`build_adapter`.
        today: Supplies the current date in the scheduler's timezone. Injected
            so the expected-period window is deterministic in tests.
        refetch_tail_periods: How many recent periods are refetched even when
            already ``ok``. Defaults to ``settings.analytics_refetch_tail_periods``.
    """

    def __init__(
        self,
        *,
        adapter_factory: Callable[[Connection], AnalyticsSourceAdapter] | None = None,
        today: Callable[[], dt.date] | None = None,
        refetch_tail_periods: int | None = None,
    ) -> None:
        self._adapter_factory = adapter_factory or (lambda conn: build_adapter(conn.source_type))
        self._today = today or _today_in_schedule_timezone
        self._tail = (
            refetch_tail_periods
            if refetch_tail_periods is not None
            else settings.analytics_refetch_tail_periods
        )

    # -- entry points -----------------------------------------------------

    async def collect(self, connection_id: str) -> CollectOutcome:
        """Collect one connection, owning the session. The worker job's entry point."""
        from app.models.base import async_session_factory

        async with async_session_factory() as session:
            return await self.collect_in_session(session, connection_id)

    async def collect_in_session(self, session: AsyncSession, connection_id: str) -> CollectOutcome:
        """Collect one connection using *session*.

        The session is committed repeatedly — once per period, by
        :func:`app.analytics.journal.record`, together with that period's fact
        rows — so a crash mid-run leaves every completed period durable and
        correctly journalled rather than rolling the whole run back.

        Returns:
            The run's outcome. ``ok`` with zero rows means nothing was due;
            errors with zero rows is ``failed``. The two never collapse.
        """
        outcome = CollectOutcome()

        conn = await session.get(Connection, connection_id)
        if conn is None:
            # Deleted between dispatch and execution (spec §7). Not a failure:
            # there is nothing left to collect and nobody to tell.
            logger.info("Analytics collect: connection %s no longer exists", connection_id[:8])
            return outcome

        if conn.source_type not in ANALYTICS_SOURCE_TYPES:
            outcome.errors.append(
                f"Connection '{conn.name}' is not an analytics source "
                f"(source_type={conn.source_type!r})."
            )
            return outcome

        tables = FACT_TABLES_BY_SOURCE.get(conn.source_type)
        if not tables:
            outcome.errors.append(
                f"No fact tables are defined for source type '{conn.source_type}' yet."
            )
            return outcome

        try:
            adapter = self._adapter_factory(conn)
        except ValueError as exc:
            outcome.errors.append(str(exc))
            return outcome

        try:
            config = await self._build_config(session, conn)
            await adapter.connect(config)
        except AnalyticsError as exc:
            # A bad credential or unusable knobs: nothing can be collected, and
            # no period is at fault, so the run fails without journalling.
            outcome.errors.append(f"{conn.name}: {exc}")
            logger.warning("Analytics collect: connect failed for %s: %s", conn.id[:8], exc)
            return outcome

        try:
            backfill_days = self._backfill_days(conn)
            for spec in adapter.available_reports():
                await self._collect_report(
                    session,
                    adapter=adapter,
                    conn=conn,
                    report=spec.name,
                    grain=spec.grain,
                    table=tables.get(spec.name),
                    backfill_days=backfill_days,
                    outcome=outcome,
                )
        finally:
            await adapter.disconnect()

        logger.info(
            "Analytics collect finished: connection=%s status=%s rows=%d ok=%d empty=%d errors=%d",
            conn.id[:8],
            outcome.status,
            outcome.rows_written,
            outcome.periods_ok,
            outcome.periods_empty,
            len(outcome.errors),
        )
        return outcome

    # -- one report --------------------------------------------------------

    async def _collect_report(
        self,
        session: AsyncSession,
        *,
        adapter: AnalyticsSourceAdapter,
        conn: Connection,
        report: str,
        grain: Grain,
        table: FactTable | None,
        backfill_days: int,
        outcome: CollectOutcome,
    ) -> None:
        """Fetch and store every pending period of one report.

        Returns early — never raises — so one report can never take the run
        down with it.
        """
        if table is None:
            # The adapter offers a report nothing knows how to store. That is a
            # wiring bug, not a vendor failure: say so and keep collecting the
            # reports that do have a home.
            message = f"{conn.name}: report '{report}' has no fact table; skipped."
            logger.error("Analytics collect: %s", message)
            outcome.errors.append(message)
            return

        expected = period_range(grain, backfill_days=backfill_days, today=self._today())
        pending = await journal.pending_periods(
            session,
            connection_id=conn.id,
            report=report,
            expected=expected,
            tail=self._tail,
        )
        if not pending:
            return

        for period in pending:
            try:
                fetched = await adapter.fetch(report, period)
            except AnalyticsEmpty as exc:
                await journal.record(
                    session,
                    connection_id=conn.id,
                    report=report,
                    period=period,
                    status="empty",
                    error=str(exc) or None,
                )
                outcome.periods_empty += 1
                continue
            except (AnalyticsAuthError, AnalyticsPermissionError) as exc:
                # Configuration error: every remaining period of this report
                # would fail the same way. Stop the report, keep the run.
                message = f"{conn.name}/{report}: {exc}"
                await journal.record(
                    session,
                    connection_id=conn.id,
                    report=report,
                    period=period,
                    status="failed",
                    error=str(exc),
                )
                outcome.errors.append(message)
                logger.warning(
                    "Analytics collect: report %r stopped after a credential error: %s",
                    report,
                    exc,
                )
                return
            except AnalyticsError as exc:
                # Transient, quota, or a bare AnalyticsError from an unusable
                # payload — all isolated to this period. Anything that is *not*
                # an AnalyticsError (e.g. ValueError for an unknown report name)
                # is a programming error and propagates.
                await journal.record(
                    session,
                    connection_id=conn.id,
                    report=report,
                    period=period,
                    status="failed",
                    error=str(exc),
                )
                outcome.errors.append(f"{conn.name}/{report} {period}: {exc}")
                continue

            try:
                written = await self._upsert(session, conn.id, table, fetched)
            except SQLAlchemyError as exc:
                # The fetch was fine; the write was not. Roll back the partial
                # flush before the journal commits its verdict, or `record`
                # would carry the broken state along with it.
                await session.rollback()
                await journal.record(
                    session,
                    connection_id=conn.id,
                    report=report,
                    period=period,
                    status="failed",
                    error=f"could not store rows: {exc}",
                )
                outcome.errors.append(f"{conn.name}/{report} {period}: could not store rows: {exc}")
                logger.exception("Analytics collect: upsert failed for %s %s", report, period)
                continue

            if fetched.degraded:
                logger.warning("Analytics collect degraded: %s", fetched.degraded)
            # ``record`` commits, so the rows and their verdict land together.
            # A ``degraded`` sentence rides along in ``error`` on an otherwise
            # ``ok`` row: the status is the verdict, the text is the caveat the
            # agent has to repeat when it quotes this period.
            await journal.record(
                session,
                connection_id=conn.id,
                report=report,
                period=period,
                status="ok",
                rows_written=written,
                error=fetched.degraded,
            )
            outcome.periods_ok += 1
            outcome.rows_written += written

    # -- storage -----------------------------------------------------------

    async def _upsert(
        self,
        session: AsyncSession,
        connection_id: str,
        table: FactTable,
        fetched: AnalyticsReport,
    ) -> int:
        """Upsert one period's rows on the fact table's natural key.

        Returns:
            How many rows were written (inserted or updated).
        """
        values = _rows_to_values(connection_id, table, fetched)
        if not values:
            return 0

        payload_columns = [
            column
            for column in fetched.columns
            if column not in table.key_columns and column != "connection_id"
        ]
        conflict_columns = ["connection_id", *table.key_columns]

        dialect = _dialect_name(session)
        if dialect in _UPSERT_DIALECTS:
            stmt = _upsert_insert(dialect)(table.model).values(values)
            updates = {
                column: getattr(stmt.excluded, column)
                for column in (*payload_columns, "fetched_at")
            }
            await session.execute(
                stmt.on_conflict_do_update(index_elements=conflict_columns, set_=updates)
            )
        else:
            # Portable fallback for a dialect without ON CONFLICT. Read-then-write
            # is not atomic under concurrent collectors; the UNIQUE constraint
            # stays the backstop, so the loser of a race raises rather than
            # duplicating a row.
            logger.debug("Analytics upsert falling back to select-then-write on %s", dialect)
            await self._upsert_portable(session, table, values, payload_columns, conflict_columns)

        await session.flush()
        return len(values)

    @staticmethod
    async def _upsert_portable(
        session: AsyncSession,
        table: FactTable,
        values: list[dict[str, Any]],
        payload_columns: Sequence[str],
        conflict_columns: Sequence[str],
    ) -> None:
        for record in values:
            existing = (
                await session.execute(
                    select(table.model).where(
                        *[
                            getattr(table.model, column) == record[column]
                            for column in conflict_columns
                        ]
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(table.model(**record))
                continue
            for column in (*payload_columns, "fetched_at"):
                setattr(existing, column, record[column])

    # -- configuration ------------------------------------------------------

    async def _build_config(self, session: AsyncSession, conn: Connection) -> ConnectionConfig:
        """Build the adapter's :class:`ConnectionConfig` for *conn*.

        An analytics source has no host, port or database, so those fields are
        left empty rather than defaulted: nothing must be able to read a
        plausible-looking ``127.0.0.1:5432`` off a GA4 connection. ``db_type``
        carries the vendor id, which is what an analytics adapter dispatches on.
        The decrypted secret is placed in ``extra`` and never logged.
        """
        secret: str | None = None
        if conn.vendor_credential_id:
            secret = await self._resolve_secret(session, conn.vendor_credential_id)

        extra: dict[str, Any] = {SOURCE_CONFIG_KEY: _decode_source_config(conn)}
        if secret:
            extra[CREDENTIAL_SECRET_KEY] = secret

        return ConnectionConfig(
            connection_id=conn.id,
            db_type=conn.source_type,
            db_host="",
            db_port=0,
            db_name="",
            is_read_only=True,
            extra=extra,
        )

    @staticmethod
    async def _resolve_secret(session: AsyncSession, credential_id: str) -> str | None:
        """Decrypt the connection's vendor credential.

        ``user_id=None`` marks this a trusted internal call: the scheduler runs
        without a request principal, and the connection's own ownership was
        settled when the credential was attached.
        """
        from app.services.vendor_credential_service import VendorCredentialService

        return await VendorCredentialService().get_decrypted(session, credential_id, user_id=None)

    def _backfill_days(self, conn: Connection) -> int:
        """The connection's backfill window, falling back to the global default."""
        raw: Any = _decode_source_config(conn).get("backfill_days")
        if raw is None or raw == "":
            # ``or`` would swallow an explicit 0 here; only an absent/blank
            # value falls back, and a 0 is caught below as non-positive.
            return settings.analytics_backfill_days
        try:
            days = int(raw)
        except (TypeError, ValueError):
            logger.warning(
                "Connection %s has a non-numeric backfill_days (%r); using the default",
                conn.id[:8],
                raw,
            )
            return settings.analytics_backfill_days
        return days if days > 0 else settings.analytics_backfill_days


def _today_in_schedule_timezone() -> dt.date:
    """Today in the scheduler's timezone, so the window agrees with the cron."""
    from zoneinfo import ZoneInfo

    return dt.datetime.now(ZoneInfo(settings.daily_knowledge_sync_timezone)).date()


def _rows_to_values(
    connection_id: str, table: FactTable, fetched: AnalyticsReport
) -> list[dict[str, Any]]:
    """Map positional vendor rows onto fact-table column dicts, de-duplicated.

    Duplicates *within one batch* are collapsed last-wins: Postgres refuses an
    ``ON CONFLICT DO UPDATE`` that would touch the same row twice, so a vendor
    that repeats a dimension combination would otherwise fail the whole period
    instead of storing it.

    Raises:
        ValueError: a row's arity does not match ``fetched.columns`` — the
            positional contract is broken and guessing would silently shift
            every value one column left.
    """
    columns = fetched.columns
    now = dt.datetime.now(dt.UTC)
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}

    for row in fetched.rows:
        if len(row) != len(columns):
            raise ValueError(
                f"analytics row has {len(row)} value(s) but the report declares "
                f"{len(columns)} column(s): {columns}"
            )
        record: dict[str, Any] = dict(zip(columns, row, strict=True))
        record["connection_id"] = connection_id
        record["id"] = str(uuid.uuid4())
        record["fetched_at"] = now
        by_key[_natural_key(record, table.key_columns)] = record

    return list(by_key.values())


def _natural_key(record: Mapping[str, Any], key_columns: Iterable[str]) -> tuple[Any, ...]:
    return tuple(record[column] for column in key_columns)
