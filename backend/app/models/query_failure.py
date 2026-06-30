"""QueryFailure — append-only diagnostic record of failed/recovered query executions.

Captures the FULL failing SQL, the full raw DB error, the classified error type, and
the complete repair-attempt history so a failed query is diagnosable after the fact
(the data the ValidationLoop produces but previously discarded). Best-effort, written
off the request path; never updated.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class QueryFailure(Base):
    __tablename__ = "query_failures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Soft link to RequestTrace.id (no FK — traces are best-effort and may not exist).
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    db_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default="")
    question: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    failed_sql: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    error_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    failure_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    raw_error: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    attempts_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    final_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="failed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_query_failures_project_created", "project_id", "created_at"),
        Index("ix_query_failures_connection_created", "connection_id", "created_at"),
        Index("ix_query_failures_error_type", "error_type"),
    )

    def to_dict(self, *, include_attempts: bool = False) -> dict:
        import json

        d: dict = {
            "id": self.id,
            "project_id": self.project_id,
            "connection_id": self.connection_id,
            "workflow_id": self.workflow_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "db_type": self.db_type,
            "question": self.question,
            "failed_sql": self.failed_sql,
            "error_type": self.error_type,
            "failure_kind": self.failure_kind,
            "raw_error": self.raw_error,
            "attempt_count": self.attempt_count,
            "final_status": self.final_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_attempts:
            try:
                d["attempts"] = json.loads(self.attempts_json or "[]")
            except (ValueError, TypeError):
                d["attempts"] = []
        return d
