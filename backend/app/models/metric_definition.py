"""Metric definitions and relationships for the Data Graph."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MetricDefinition(Base):
    """A discovered or user-defined metric (e.g. 'monthly_revenue', 'active_users')."""

    __tablename__ = "metric_definitions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "name", "connection_id", name="uq_metric_def_project_name_conn"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="general")

    source_table: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_column: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aggregation: Mapped[str] = mapped_column(String(50), default="")
    formula: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(50), default="")
    data_type: Mapped[str] = mapped_column(String(50), default="numeric")

    discovery_source: Mapped[str] = mapped_column(String(50), default="auto")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    times_referenced: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MetricRelationship(Base):
    """A relationship between two metrics (correlation, dependency, causation hypothesis)."""

    __tablename__ = "metric_relationships"
    __table_args__ = (
        UniqueConstraint(
            "metric_a_id", "metric_b_id", "relationship_type", name="uq_metric_rel_pair_type"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_a_id: Mapped[str] = mapped_column(
        ForeignKey("metric_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_b_id: Mapped[str] = mapped_column(
        ForeignKey("metric_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=0.0)
    direction: Mapped[str] = mapped_column(String(20), default="bidirectional")
    description: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
