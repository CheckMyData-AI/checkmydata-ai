"""Dedup'd error catalog fed by both the runs plane and the query plane."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ErrorLog(Base):
    __tablename__ = "error_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # run|query|span|system
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    failure_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    sample_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")

    __table_args__ = (
        Index("uq_error_log_project_sig", "project_id", "signature", unique=True),
        Index("ix_error_log_project_lastseen", "project_id", "last_seen_at"),
        Index("ix_error_log_status", "status"),
    )
