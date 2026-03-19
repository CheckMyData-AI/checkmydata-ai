import hashlib
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _lesson_hash(lesson: str) -> str:
    return hashlib.sha256(lesson.strip().lower().encode()).hexdigest()[:32]


class AgentLearning(Base):
    """Per-connection lesson learned from query outcomes."""

    __tablename__ = "agent_learnings"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "category",
            "subject",
            "lesson_hash",
            name="uq_agent_learning_dedup",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    lesson: Mapped[str] = mapped_column(Text, nullable=False)
    lesson_hash: Mapped[str] = mapped_column(String(32), nullable=False)

    confidence: Mapped[float] = mapped_column(Float, default=0.6)
    source_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    times_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    times_applied: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentLearningSummary(Base):
    """Connection-level compiled summary of agent learnings."""

    __tablename__ = "agent_learning_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    total_lessons: Mapped[int] = mapped_column(Integer, default=0)
    lessons_by_category_json: Mapped[str] = mapped_column(Text, default="{}")
    compiled_prompt: Mapped[str] = mapped_column(Text, default="")
    last_compiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
