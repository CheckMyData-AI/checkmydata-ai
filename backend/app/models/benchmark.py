"""Data benchmarks — verified metric values used for sanity checking."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DataBenchmark(Base):
    """A known-good metric value used for sanity-checking future queries."""

    __tablename__ = "data_benchmarks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_key: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    metric_description: Mapped[str] = mapped_column(Text, default="")
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)

    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    source: Mapped[str] = mapped_column(String(50), default="agent_derived")
    times_confirmed: Mapped[int] = mapped_column(Integer, default=1)

    last_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
