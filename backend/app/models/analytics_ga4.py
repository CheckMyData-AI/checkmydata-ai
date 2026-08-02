"""GA4 fact tables — the local cache the agent actually answers from (spec §1.4).

Five narrow daily tables, one per report. Every row carries
``(connection_id, property_id, date)`` plus that report's dimensions; the
combination is the table's natural key and is UNIQUE, which makes it the
conflict target of ``INSERT … ON CONFLICT DO UPDATE`` — a re-collected day
updates in place instead of doubling.

Counts are ``BigInteger`` and money is ``Numeric(18, 4)``; **never float**. GA4
metrics are exact integers and a float would silently round large event counts
and misreport revenue. Metrics are NOT NULL with a 0 default so a collected day
with no traffic is stored as a genuine zero (docs-study Δ2 keeps empty rows) and
"zero" never becomes indistinguishable from "never collected" — the journal
(:mod:`app.models.analytics_import`) is the only thing that says the latter.

``datetime`` is imported as ``dt`` because these tables have a column literally
named ``date``; ``Mapped[dt.date]`` keeps the annotation unambiguous.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

#: Revenue precision shared by every money column here.
MONEY = Numeric(18, 4)


def _pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


def _connection_fk() -> Mapped[str]:
    """FK to the owning connection. CASCADE: deleting a connection erases its cache."""
    return mapped_column(
        String(36),
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
    )


def _count() -> Mapped[int]:
    return mapped_column(BigInteger, nullable=False, default=0, server_default="0")


def _fetched_at() -> Mapped[dt.datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class GA4OverviewDaily(Base):
    """Property-wide daily totals. Natural key ``(connection, property, date)``."""

    __tablename__ = "ga4_overview_daily"
    __table_args__ = (
        UniqueConstraint("connection_id", "property_id", "date", name="uq_ga4_overview_daily_key"),
        Index("ix_ga4_overview_daily_conn_date", "connection_id", "date"),
    )

    id: Mapped[str] = _pk()
    connection_id: Mapped[str] = _connection_fk()
    property_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)

    sessions: Mapped[int] = _count()
    active_users: Mapped[int] = _count()
    new_users: Mapped[int] = _count()
    screen_page_views: Mapped[int] = _count()
    event_count: Mapped[int] = _count()
    total_revenue: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0"), server_default="0"
    )

    fetched_at: Mapped[dt.datetime] = _fetched_at()


class GA4GeoDaily(Base):
    """Daily sessions/users by country."""

    __tablename__ = "ga4_geo_daily"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "property_id", "date", "country", name="uq_ga4_geo_daily_key"
        ),
        Index("ix_ga4_geo_daily_conn_date", "connection_id", "date"),
    )

    id: Mapped[str] = _pk()
    connection_id: Mapped[str] = _connection_fk()
    property_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    country: Mapped[str] = mapped_column(String(128), nullable=False)

    sessions: Mapped[int] = _count()
    active_users: Mapped[int] = _count()

    fetched_at: Mapped[dt.datetime] = _fetched_at()


class GA4PlatformDaily(Base):
    """Daily sessions/users by platform and device category."""

    __tablename__ = "ga4_platform_daily"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "property_id",
            "date",
            "platform",
            "device_category",
            name="uq_ga4_platform_daily_key",
        ),
        Index("ix_ga4_platform_daily_conn_date", "connection_id", "date"),
    )

    id: Mapped[str] = _pk()
    connection_id: Mapped[str] = _connection_fk()
    property_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    device_category: Mapped[str] = mapped_column(String(64), nullable=False)

    sessions: Mapped[int] = _count()
    active_users: Mapped[int] = _count()

    fetched_at: Mapped[dt.datetime] = _fetched_at()


class GA4TrendDaily(Base):
    """Daily acquisition trend by default channel group."""

    __tablename__ = "ga4_trend_daily"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "property_id",
            "date",
            "channel_group",
            name="uq_ga4_trend_daily_key",
        ),
        Index("ix_ga4_trend_daily_conn_date", "connection_id", "date"),
    )

    id: Mapped[str] = _pk()
    connection_id: Mapped[str] = _connection_fk()
    property_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    channel_group: Mapped[str] = mapped_column(String(128), nullable=False)

    sessions: Mapped[int] = _count()
    active_users: Mapped[int] = _count()
    key_events: Mapped[int] = _count()

    fetched_at: Mapped[dt.datetime] = _fetched_at()


class GA4EventDaily(Base):
    """Daily counts for the events a connection asked to track."""

    __tablename__ = "ga4_event_daily"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "property_id",
            "date",
            "event_name",
            name="uq_ga4_event_daily_key",
        ),
        Index("ix_ga4_event_daily_conn_date", "connection_id", "date"),
    )

    id: Mapped[str] = _pk()
    connection_id: Mapped[str] = _connection_fk()
    property_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)

    event_count: Mapped[int] = _count()
    active_users: Mapped[int] = _count()

    fetched_at: Mapped[dt.datetime] = _fetched_at()


#: Every GA4 fact table, in report order — used by cleanup and coverage code.
GA4_FACT_MODELS = (
    GA4OverviewDaily,
    GA4GeoDaily,
    GA4PlatformDaily,
    GA4TrendDaily,
    GA4EventDaily,
)
