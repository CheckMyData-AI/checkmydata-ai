"""Models for persisted request traces and spans (orchestrator observability)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class RequestTrace(Base):
    __tablename__ = "request_traces"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    assistant_message_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    response_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="text"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="started"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_llm_calls: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_db_queries: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_provider: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="unknown"
    )
    llm_model: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="unknown"
    )
    steps_used: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    steps_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    spans: Mapped[list[TraceSpan]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        order_by="TraceSpan.order_index",
    )

    __table_args__ = (
        Index("ix_request_traces_project_created", "project_id", "created_at"),
        Index("ix_request_traces_user_created", "user_id", "created_at"),
    )


class TraceSpan(Base):
    __tablename__ = "trace_spans"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    trace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("request_traces.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_span_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("trace_spans.id", ondelete="SET NULL"),
        nullable=True,
    )
    span_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="started"
    )
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    trace: Mapped[RequestTrace] = relationship(back_populates="spans")

    __table_args__ = (
        Index("ix_trace_spans_trace_order", "trace_id", "order_index"),
        Index("ix_trace_spans_type", "span_type"),
        Index("ix_trace_spans_status", "status"),
    )
