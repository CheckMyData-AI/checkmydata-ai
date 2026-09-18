"""The analytics import journal (spec §2.5, REQ-005).

One row per ``(connection, report, period)`` recording whether that period was
collected (``ok``), came back genuinely empty (``empty``) or failed
(``failed``). The journal — not the newest period on file — decides what to
fetch next.

**The watermark rule.** Pending is ``expected − done``:

.. code-block:: text

    pending = sorted(set(expected) - {p for p, s in journal if s in ("ok", "empty")})
              ∪ the last `tail` entries of `expected`

Never ``max(period)``. A high-water mark passes every ordinary case and then
silently drops the one that matters: when day 3 fails but days 4 and 5 succeed,
day 3 sits *below* the mark and is skipped forever, leaving a hole no retry
ever fills. Set arithmetic refills it. That is why a ``failed`` period stays
pending until it actually succeeds, and why ``empty`` — a completed period with
genuinely no data — counts as done and is never retried.

The ``tail`` union exists because vendors revise recent data: the last ``tail``
expected periods are always refetched even when they are already ``ok``.

``record`` and ``prune`` commit. The journal's value is that its verdicts
survive a crash mid-run, which they cannot do if they sit uncommitted in a
session the collector later abandons. Call ``record`` *after* adding the
period's fact rows to the same session so the rows and their verdict land in
one transaction.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.source_types import clamp_backfill_days
from app.models.analytics_import import AnalyticsImport

logger = logging.getLogger(__name__)

JournalStatus = Literal["ok", "empty", "partial", "failed"]

#: Statuses that complete a period. ``empty`` belongs here: a period the vendor
#: genuinely has no data for is finished, not broken. ``partial`` does NOT (A-01):
#: some of the period's sources answered and some did not, so the rows are real and
#: they are not all of them — the period is owed another attempt, and "pending" is
#: exactly the state that arranges one.
DONE_STATUSES: frozenset[str] = frozenset({"ok", "empty"})

#: Every status the journal accepts. An unrecognised one would make the period
#: look "not done" forever, so it is rejected at the door rather than stored.
#: Prefix of a journal note that is NOT a defect: the period was collected in full and
#: the vendor is still revising it (the refetch tail). `error` on a done row otherwise
#: means "the vendor handed over part of this period", and the agent publishes that as a
#: LOWER BOUND — a different and wrong claim about a number that is merely not final.
#: One definition, because the writer (the collect service) and the reader (the
#: analytics agent) must agree byte for byte or the split silently stops working.
PROVISIONAL_NOTE_PREFIX = "provisional:"

VALID_STATUSES: frozenset[str] = frozenset({"ok", "empty", "partial", "failed"})

#: Columns the upsert refreshes on conflict — the natural key is never among them.
_UPSERT_COLUMNS = ("status", "rows_written", "error", "fetched_at")

#: Dialects with a native ``ON CONFLICT DO UPDATE`` (the app DB is Postgres in
#: production, SQLite in dev). Anything else takes the portable fallback.
_UPSERT_DIALECTS = frozenset({"postgresql", "sqlite"})


def _dialect_name(session: AsyncSession) -> str:
    """The bound dialect (``postgresql`` / ``sqlite`` / …). Patchable in tests."""
    return str(session.get_bind().dialect.name)


def _upsert_insert(dialect: str) -> Any:
    """The dialect's ``ON CONFLICT DO UPDATE``-capable ``insert`` constructor.

    Returns ``Any`` on purpose: the two constructors are structurally identical
    for our use but nominally unrelated types, so naming the union buys nothing.
    Only dialects in :data:`_UPSERT_DIALECTS` reach this.
    """
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


async def pending_periods(
    session: AsyncSession,
    *,
    connection_id: str,
    report: str,
    expected: list[str],
    tail: int,
) -> list[str]:
    """Periods of ``report`` still owed for ``connection_id``, ascending.

    Args:
        session: Async session bound to the app database.
        connection_id: The connection whose journal is consulted.
        report: Report name — the journal key is per-report, so one report's
            success never marks another's period done.
        expected: Every period the caller wants on file, as ``YYYY-MM-DD`` or
            ``YYYY-MM`` strings (both sort correctly lexicographically).
            Duplicates and input order do not matter.
        tail: How many of the most recent expected periods to refetch
            unconditionally, because vendors revise recent data. ``0`` means
            no tail — note ``expected[-0:]`` would be the *whole* list, so this
            is branched on explicitly. Values above ``len(expected)`` clamp.

    Returns:
        The sorted, de-duplicated periods to fetch. Never contains a period
        absent from ``expected``, even if the journal holds one.
    """
    rows = (
        await session.execute(
            select(AnalyticsImport.period, AnalyticsImport.status).where(
                AnalyticsImport.connection_id == connection_id,
                AnalyticsImport.report == report,
            )
        )
    ).all()
    done = {period for period, status in rows if status in DONE_STATUSES}

    wanted = sorted(set(expected))
    # expected − done. Set difference, never a high-water mark: a `failed` day
    # below the newest success has to refill, not be skipped forever.
    pending = set(wanted) - done
    if tail > 0:
        pending |= set(wanted[-tail:])
    return sorted(pending)


async def record(
    session: AsyncSession,
    *,
    connection_id: str,
    report: str,
    period: str,
    status: JournalStatus | str,
    rows_written: int = 0,
    error: str | None = None,
) -> None:
    """Upsert one ``(connection, report, period)`` verdict and commit.

    Recording the same triple twice leaves exactly one row carrying the latest
    verdict — the UNIQUE constraint ``uq_analytics_imports_key`` is the conflict
    target — so a retry that succeeds overwrites the failure (and clears its
    stale ``error``) instead of appending a second, contradictory row.

    Args:
        session: Async session bound to the app database.
        connection_id: Connection the period belongs to.
        report: Report name (``overview`` | ``geo`` | ``platform`` | ``trend`` |
            ``events``).
        period: ``YYYY-MM-DD`` or ``YYYY-MM``.
        status: ``ok`` | ``empty`` | ``partial`` | ``failed``. Only the first two
            complete a period; ``partial`` keeps the rows and keeps it pending.
        rows_written: Fact rows persisted for this period.
        error: Human-readable failure, safe to surface — never a credential.

    Raises:
        ValueError: ``status`` is not one of :data:`VALID_STATUSES`.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"unknown journal status {status!r}; expected one of {sorted(VALID_STATUSES)}"
        )

    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "connection_id": connection_id,
        "report": report,
        "period": period,
        "status": status,
        "rows_written": rows_written,
        "error": error,
        "fetched_at": now,
    }
    updates = {column: values[column] for column in _UPSERT_COLUMNS}

    dialect = _dialect_name(session)
    if dialect in _UPSERT_DIALECTS:
        stmt = _upsert_insert(dialect)(AnalyticsImport).values(**values)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["connection_id", "report", "period"],
                set_=updates,
            )
        )
    else:
        # Portable fallback for a dialect without ON CONFLICT. Read-then-write is
        # not atomic under concurrent collectors; the UNIQUE constraint stays the
        # backstop, so the loser of a race raises rather than duplicating a period.
        logger.debug("journal upsert falling back to select-then-write on dialect %s", dialect)
        existing = (
            await session.execute(
                select(AnalyticsImport).where(
                    AnalyticsImport.connection_id == connection_id,
                    AnalyticsImport.report == report,
                    AnalyticsImport.period == period,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(AnalyticsImport(**values))
        else:
            for column, value in updates.items():
                setattr(existing, column, value)

    await session.commit()


async def widest_live_window_days(session: AsyncSession) -> int:
    """The longest backfill window any analytics connection is configured for (A-07).

    What the prune must not cut into. Read from the connections themselves rather than
    assumed from the setting: `source_config.backfill_days` overrides it per connection,
    and the overriding one is exactly the case the old prune got wrong.
    """
    from app.config import settings as app_settings
    from app.models.connection import Connection
    from app.services.connection_service import is_analytics_source

    widest = int(app_settings.analytics_backfill_days)
    rows = (await session.execute(select(Connection))).scalars().all()
    for conn in rows:
        if not is_analytics_source(conn.source_type) or not getattr(conn, "is_active", True):
            continue
        raw = conn.source_config_json or ""
        if not raw:
            continue
        try:
            configured = json.loads(raw).get("backfill_days")
        except (TypeError, ValueError):
            continue
        days = clamp_backfill_days(configured)
        if days is not None:
            widest = max(widest, days)
    return widest


async def prune(
    session: AsyncSession,
    *,
    older_than_days: int = 400,
    protect_days: int = 0,
) -> int:
    """Delete journal rows for periods older than the windows anybody still collects.

    A-07: this pruned on ``fetched_at``, which is when the row was WRITTEN, while a
    connection may ask for up to 3 650 days of history. So a period inside a live
    backfill window lost its journal row after 400 days, re-entered ``pending``, and was
    collected again — about 3 000 vendor calls at once, past the job's 1 800 s ceiling,
    every ~400 days, for ever. Two changes make that impossible: the age that counts is
    the **period's**, not the row's, and *protect_days* keeps everything inside the
    widest window any connection is currently configured for.

    Args:
        session: Async session bound to the app database.
        older_than_days: Retention window in days; must be at least 1.
        protect_days: Never delete a period newer than this many days, whatever the
            retention says. The caller passes the widest live backfill window.

    Returns:
        How many rows were deleted.

    Raises:
        ValueError: ``older_than_days`` is below 1 — ``0`` would delete the
            entire journal and make every period look never-collected.
    """
    if older_than_days < 1:
        raise ValueError(f"older_than_days must be >= 1, got {older_than_days}")

    horizon = max(older_than_days, max(protect_days, 0))
    cutoff_date = (datetime.now(UTC) - timedelta(days=horizon)).date()
    # The period is stored as the string the report's grain produces: `YYYY-MM-DD` for a
    # daily report and `YYYY-MM` for a monthly one. Both sort as dates do, so the
    # comparison is a string one and needs no per-row parsing — and a monthly period is
    # only dropped once the whole month is behind the cutoff.
    daily_cutoff = cutoff_date.isoformat()
    monthly_cutoff = cutoff_date.strftime("%Y-%m")
    # Annotated Any: a DELETE yields a CursorResult, which carries `rowcount`,
    # but AsyncSession.execute is typed as returning the narrower Result.
    result: Any = await session.execute(
        delete(AnalyticsImport).where(
            or_(
                and_(
                    func.length(AnalyticsImport.period) == 10, AnalyticsImport.period < daily_cutoff
                ),
                and_(
                    func.length(AnalyticsImport.period) == 7,
                    AnalyticsImport.period < monthly_cutoff,
                ),
            )
        )
    )
    await session.commit()
    deleted = int(result.rowcount or 0)
    if deleted:
        logger.info(
            "Pruned %d analytics journal row(s) for periods before %s", deleted, daily_cutoff
        )
    return deleted
