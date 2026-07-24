import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LearningVote(Base):
    """One active vote per (learning, user) — AQ-7 per-user vote dedup.

    Without persistence the confirm/contradict endpoints let a single user
    bump a learning's confidence to 1.0 (★CRITICAL after 5 clicks) or
    deactivate someone else's learning with 2 contradict clicks. This table
    records who voted how so a repeated same-sign vote is a no-op and a
    sign change reverses the previous effect (see
    ``AgentLearningService.vote_learning``).

    ``user_id`` is deliberately not a hard FK: votes are lightweight audit
    rows and must survive account cleanup without cascading surprises.
    """

    __tablename__ = "learning_votes"
    __table_args__ = (
        UniqueConstraint("learning_id", "user_id", name="uq_learning_vote_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learning_id: Mapped[str] = mapped_column(
        ForeignKey("agent_learnings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    vote: Mapped[int] = mapped_column(Integer, nullable=False)  # +1 confirm / -1 contradict

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
