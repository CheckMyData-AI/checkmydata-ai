"""Durable audit log (F-AUTH-15).

Security-sensitive actions emit a structured logger line via ``core/audit.py``;
on Heroku that line is ephemeral and not queryable. This table persists the same
event so the audit trail survives dyno restarts and can be queried.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # Nullable (system actions); not an FK so the trail survives the subject's deletion.
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON-encoded extra kwargs, if any.
    extra: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_logs_action_created", "action", "created_at"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
    )
