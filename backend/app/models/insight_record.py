"""Persistent insight records for the Memory Layer."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InsightRecord(Base):
    """A discovered insight: anomaly, opportunity, loss, pattern, or observation."""

    __tablename__ = "insight_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), nullable=True, index=True
    )

    insight_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="info")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    source_metrics_json: Mapped[str] = mapped_column(Text, default="[]")
    source_query: Mapped[str | None] = mapped_column(Text, nullable=True)

    recommended_action: Mapped[str] = mapped_column(Text, default="")
    expected_impact: Mapped[str] = mapped_column(Text, default="")

    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    user_verdict: Mapped[str | None] = mapped_column(String(30), nullable=True)
    user_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    times_surfaced: Mapped[int] = mapped_column(Integer, default=1)
    times_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    times_dismissed: Mapped[int] = mapped_column(Integer, default=0)

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TrustScore(Base):
    """Trust/provenance metadata for an insight."""

    __tablename__ = "trust_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    insight_id: Mapped[str] = mapped_column(
        ForeignKey("insight_records.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    data_freshness_hours: Mapped[float] = mapped_column(Float, default=0.0)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    validation_method: Mapped[str] = mapped_column(String(100), default="auto")
    validation_details: Mapped[str] = mapped_column(Text, default="")
    cross_validated: Mapped[bool] = mapped_column(default=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
