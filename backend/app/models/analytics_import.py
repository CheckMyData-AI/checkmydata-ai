"""The analytics import journal (spec §1.3).

One row per ``(connection, report, period)`` recording whether that period was
collected, came back genuinely empty, or failed. The journal — not
``max(period)`` — is what decides what to fetch next, so a hole below the
high-water mark refills instead of being skipped forever
(``app.analytics.journal.pending_periods``).

The UNIQUE key doubles as the upsert conflict target: re-recording a period
updates the row rather than appending a second verdict for the same period.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalyticsImport(Base):
    __tablename__ = "analytics_imports"
    __table_args__ = (
        UniqueConstraint("connection_id", "report", "period", name="uq_analytics_imports_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "overview" | "geo" | "platform" | "trend" | "events"
    report: Mapped[str] = mapped_column(String(64), nullable=False)
    # "YYYY-MM-DD" for daily reports, "YYYY-MM" for monthly ones.
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    # "ok" | "empty" | "failed" — "empty" is a completed period with no data and
    # must never be conflated with "failed" (which stays pending).
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rows_written: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
