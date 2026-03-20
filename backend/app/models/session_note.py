"""Agent working memory — persistent notes about data observations per connection."""

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _note_hash(note: str) -> str:
    return hashlib.sha256(note.strip().lower().encode()).hexdigest()[:32]


VALID_NOTE_CATEGORIES = frozenset(
    {
        "data_observation",
        "column_mapping",
        "business_logic",
        "calculation_note",
        "user_preference",
        "verified_benchmark",
    }
)


class SessionNote(Base):
    """Per-connection agent observation persisted across sessions."""

    __tablename__ = "session_notes"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "category",
            "subject",
            "note_hash",
            name="uq_session_note_dedup",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    note_hash: Mapped[str] = mapped_column(String(32), nullable=False)

    source_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
