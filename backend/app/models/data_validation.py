"""Data validation feedback and investigation models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DataValidationFeedback(Base):
    """Structured user feedback on data accuracy (beyond thumbs up/down)."""

    __tablename__ = "data_validation_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    query: Mapped[str] = mapped_column(Text, nullable=False)
    metric_description: Mapped[str] = mapped_column(Text, default="")
    agent_value: Mapped[str] = mapped_column(Text, default="")
    user_expected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    deviation_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    verdict: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataInvestigation(Base):
    """Tracks a full 'Wrong Data' investigation session."""

    __tablename__ = "data_investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    validation_feedback_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_validation_feedback.id", ondelete="SET NULL"), nullable=True
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    trigger_message_id: Mapped[str] = mapped_column(String(36), nullable=False)

    status: Mapped[str] = mapped_column(String(30), default="collecting_info")
    phase: Mapped[str] = mapped_column(String(50), default="collect_info")

    user_complaint_type: Mapped[str] = mapped_column(String(50), default="other")
    user_complaint_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_expected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    problematic_column: Mapped[str | None] = mapped_column(String(255), nullable=True)

    investigation_log_json: Mapped[str] = mapped_column(Text, default="[]")
    original_query: Mapped[str] = mapped_column(Text, default="")
    original_result_summary: Mapped[str] = mapped_column(Text, default="{}")
    corrected_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause_category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    learnings_created_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes_created_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    benchmarks_updated_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
