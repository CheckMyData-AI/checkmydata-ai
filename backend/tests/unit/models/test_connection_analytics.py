"""Model-level tests for the analytics source spine (T2 — spec §1.1–§1.4).

Proves the invariants both the ORM and the migration have to hold:

- a GA4 connection persists with ``db_type`` / ``db_port`` / ``db_name`` all
  ``None`` (an analytics source has no host, port or database);
- a classic database connection still round-trips unchanged;
- every ``ga4_*`` natural key is UNIQUE — that constraint is the conflict
  target of the collector's upsert, so without it a re-run silently duplicates
  a day instead of updating it;
- ``analytics_imports`` is UNIQUE on ``(connection_id, report, period)``;
- deleting a connection cascades the journal *and* all five fact tables to
  zero rows;
- deleting a vendor credential a connection still references is refused
  (FK RESTRICT) instead of orphaning the connection.

``PRAGMA foreign_keys=ON`` is enabled via :func:`enable_sqlite_fk` — SQLite
ignores every ``ondelete=`` clause without it, which would make the cascade
and RESTRICT tests pass for the wrong reason.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every mapper
from app.models.analytics_ga4 import (
    GA4EventDaily,
    GA4GeoDaily,
    GA4OverviewDaily,
    GA4PlatformDaily,
    GA4TrendDaily,
)
from app.models.analytics_import import AnalyticsImport
from app.models.base import Base, enable_sqlite_fk
from app.models.connection import Connection
from app.models.project import Project
from app.models.vendor_credential import VendorCredential

PROPERTY_ID = "294380179"
DAY = date(2026, 7, 15)


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


async def _project(db: AsyncSession) -> Project:
    proj = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def _credential(db: AsyncSession) -> VendorCredential:
    cred = VendorCredential(
        name="ga4-sa",
        provider="ga4",
        secret_encrypted="gAAAAA-ciphertext",
        fingerprint="0123456789abcdef",
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return cred


async def _ga4_connection(db: AsyncSession, credential_id: str | None = None) -> Connection:
    proj = await _project(db)
    conn = Connection(
        project_id=proj.id,
        name="ga4-prod",
        source_type="ga4",
        db_type=None,
        db_port=None,
        db_name=None,
        vendor_credential_id=credential_id,
        source_config_json='{"property_ids": ["294380179"], "backfill_days": 30}',
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn


async def _count(db: AsyncSession, model: Any) -> int:
    return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


# Natural key (spec §1.4) -> a payload that is *different* on the duplicate insert,
# so a passing test proves the key collided rather than the whole row.
GA4_TABLES: list[tuple[Any, dict[str, Any], dict[str, Any]]] = [
    (
        GA4OverviewDaily,
        {},
        {
            "sessions": 100,
            "active_users": 80,
            "new_users": 20,
            "screen_page_views": 300,
            "event_count": 900,
            "total_revenue": Decimal("1234.5600"),
        },
    ),
    (GA4GeoDaily, {"country": "Cyprus"}, {"sessions": 10, "active_users": 8}),
    (
        GA4PlatformDaily,
        {"platform": "web", "device_category": "mobile"},
        {"sessions": 11, "active_users": 9},
    ),
    (
        GA4TrendDaily,
        {"channel_group": "Organic Search"},
        {"sessions": 12, "active_users": 10, "key_events": 3},
    ),
    (
        GA4EventDaily,
        {"event_name": "pin_show_promo"},
        {"event_count": 42, "active_users": 7},
    ),
]


class TestConnectionColumns:
    async def test_analytics_connection_persists_without_db_fields(self, db: AsyncSession):
        """A GA4 connection has no host/port/database — all three must be nullable."""
        conn = await _ga4_connection(db)

        row = (await db.execute(select(Connection).where(Connection.id == conn.id))).scalar_one()
        assert row.source_type == "ga4"
        assert row.db_type is None
        assert row.db_port is None
        assert row.db_name is None
        # New knobs carry their server defaults.
        assert row.collection_enabled is True
        assert row.collection_hour == 3
        assert row.vendor_credential_id is None

    async def test_database_connection_round_trips_unchanged(self, db: AsyncSession):
        """The existing shape must be untouched by the analytics columns."""
        proj = await _project(db)
        conn = Connection(
            project_id=proj.id,
            name="pg-prod",
            source_type="database",
            db_type="postgres",
            db_host="db.internal",
            db_port=5432,
            db_name="analytics",
            db_user="reader",
        )
        db.add(conn)
        await db.commit()

        row = (await db.execute(select(Connection).where(Connection.id == conn.id))).scalar_one()
        assert (row.source_type, row.db_type, row.db_host, row.db_port, row.db_name) == (
            "database",
            "postgres",
            "db.internal",
            5432,
            "analytics",
        )
        assert row.is_read_only is True
        assert row.vendor_credential_id is None
        assert row.source_config_json is None

    async def test_collection_hour_and_enabled_are_persisted(self, db: AsyncSession):
        proj = await _project(db)
        conn = Connection(
            project_id=proj.id,
            name="ga4-off",
            source_type="ga4",
            collection_enabled=False,
            collection_hour=17,
        )
        db.add(conn)
        await db.commit()

        row = (await db.execute(select(Connection).where(Connection.id == conn.id))).scalar_one()
        assert row.collection_enabled is False
        assert row.collection_hour == 17


class TestVendorCredentialLink:
    async def test_connection_references_credential(self, db: AsyncSession):
        cred = await _credential(db)
        conn = await _ga4_connection(db, credential_id=cred.id)
        assert conn.vendor_credential_id == cred.id

    async def test_delete_credential_in_use_is_restricted(self, db: AsyncSession):
        """FK RESTRICT: deleting a credential still in use fails loudly."""
        cred = await _credential(db)
        await _ga4_connection(db, credential_id=cred.id)

        # SQLite enforces RESTRICT immediately, Postgres at statement end — so the
        # DELETE and the COMMIT both live inside the expectation.
        with pytest.raises(IntegrityError):
            await db.execute(
                VendorCredential.__table__.delete().where(VendorCredential.id == cred.id)
            )
            await db.commit()
        await db.rollback()

        assert await _count(db, VendorCredential) == 1
        assert await _count(db, Connection) == 1

    async def test_delete_unused_credential_succeeds(self, db: AsyncSession):
        cred = await _credential(db)
        await db.execute(VendorCredential.__table__.delete().where(VendorCredential.id == cred.id))
        await db.commit()
        assert await _count(db, VendorCredential) == 0


class TestAnalyticsImportJournal:
    async def test_unique_connection_report_period(self, db: AsyncSession):
        conn = await _ga4_connection(db)
        db.add(
            AnalyticsImport(
                connection_id=conn.id,
                report="overview",
                period="2026-07-15",
                status="ok",
                rows_written=1,
            )
        )
        await db.commit()

        db.add(
            AnalyticsImport(
                connection_id=conn.id,
                report="overview",
                period="2026-07-15",
                status="failed",
                error="quota",
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
        assert await _count(db, AnalyticsImport) == 1

    async def test_same_period_different_report_coexists(self, db: AsyncSession):
        conn = await _ga4_connection(db)
        db.add_all(
            [
                AnalyticsImport(
                    connection_id=conn.id, report="overview", period="2026-07-15", status="ok"
                ),
                AnalyticsImport(
                    connection_id=conn.id, report="geo", period="2026-07-15", status="empty"
                ),
            ]
        )
        await db.commit()
        assert await _count(db, AnalyticsImport) == 2

    async def test_defaults(self, db: AsyncSession):
        conn = await _ga4_connection(db)
        row = AnalyticsImport(
            connection_id=conn.id, report="trend", period="2026-07", status="empty"
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        assert row.rows_written == 0
        assert row.error is None
        assert row.fetched_at is not None


class TestGA4FactTables:
    @pytest.mark.parametrize(
        ("model", "key_extra", "metrics"),
        GA4_TABLES,
        ids=[m.__tablename__ for m, _, _ in GA4_TABLES],
    )
    async def test_natural_key_rejects_duplicate(
        self, db: AsyncSession, model: Any, key_extra: dict, metrics: dict
    ):
        conn = await _ga4_connection(db)
        key = {"connection_id": conn.id, "property_id": PROPERTY_ID, "date": DAY, **key_extra}
        db.add(model(**key, **metrics))
        await db.commit()

        # Same natural key, different metrics -> the key is what collides.
        bumped = {k: (v + 1 if isinstance(v, int) else v) for k, v in metrics.items()}
        db.add(model(**key, **bumped))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
        assert await _count(db, model) == 1

    @pytest.mark.parametrize(
        ("model", "key_extra", "metrics"),
        GA4_TABLES,
        ids=[m.__tablename__ for m, _, _ in GA4_TABLES],
    )
    async def test_different_day_is_a_new_row(
        self, db: AsyncSession, model: Any, key_extra: dict, metrics: dict
    ):
        conn = await _ga4_connection(db)
        base = {"connection_id": conn.id, "property_id": PROPERTY_ID, **key_extra}
        db.add_all(
            [
                model(**base, date=DAY, **metrics),
                model(**base, date=date(2026, 7, 16), **metrics),
            ]
        )
        await db.commit()
        assert await _count(db, model) == 2

    async def test_revenue_keeps_four_decimal_places(self, db: AsyncSession):
        conn = await _ga4_connection(db)
        row = GA4OverviewDaily(
            connection_id=conn.id,
            property_id=PROPERTY_ID,
            date=DAY,
            sessions=1,
            total_revenue=Decimal("1234.5678"),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        assert Decimal(str(row.total_revenue)) == Decimal("1234.5678")

    async def test_counts_default_to_zero_not_null(self, db: AsyncSession):
        """A collected-but-empty day is a zero, not a gap (docs-study Δ2)."""
        conn = await _ga4_connection(db)
        row = GA4OverviewDaily(connection_id=conn.id, property_id=PROPERTY_ID, date=DAY)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        assert row.sessions == 0
        assert row.active_users == 0
        assert row.event_count == 0
        assert Decimal(str(row.total_revenue)) == Decimal("0")


class TestConnectionCascade:
    async def test_delete_connection_cascades_journal_and_facts(self, db: AsyncSession):
        conn = await _ga4_connection(db)
        db.add(
            AnalyticsImport(
                connection_id=conn.id,
                report="overview",
                period="2026-07-15",
                status="ok",
                rows_written=1,
            )
        )
        for model, key_extra, metrics in GA4_TABLES:
            db.add(
                model(
                    connection_id=conn.id,
                    property_id=PROPERTY_ID,
                    date=DAY,
                    **key_extra,
                    **metrics,
                )
            )
        await db.commit()

        assert await _count(db, AnalyticsImport) == 1
        for model, _, _ in GA4_TABLES:
            assert await _count(db, model) == 1

        await db.execute(Connection.__table__.delete().where(Connection.id == conn.id))
        await db.commit()

        assert await _count(db, Connection) == 0
        assert await _count(db, AnalyticsImport) == 0
        for model, _, _ in GA4_TABLES:
            assert await _count(db, model) == 0, f"{model.__tablename__} was not cascaded"
