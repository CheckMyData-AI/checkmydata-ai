"""Canonical lifecycle aggregate + append-only journal for background runs.

One :class:`IndexingRun` row per repo-index / db-index / code-DB-sync / daily-sync
run. It is the single source of truth for live status, progress, cancel/retry, and
history. :class:`IndexingRunEvent` is the append-only step/log journal feeding both
the live view and persisted history.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class IndexingRun(Base):
    __tablename__ = "indexing_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued")
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    events: Mapped[list[IndexingRunEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="IndexingRunEvent.ts",
    )

    __table_args__ = (
        Index("ix_indexing_runs_workflow", "workflow_id", unique=True),
        Index("ix_indexing_runs_history", "project_id", "kind", "created_at"),
        Index("ix_indexing_runs_active", "project_id", "kind", "status"),
    )


class IndexingRunEvent(Base):
    __tablename__ = "indexing_run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("indexing_runs.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    elapsed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[str] = mapped_column(String(10), nullable=False, server_default="info")

    run: Mapped[IndexingRun] = relationship(back_populates="events")

    __table_args__ = (Index("ix_indexing_run_events_run_ts", "run_id", "ts"),)
