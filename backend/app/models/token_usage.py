import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Money, so `Numeric` rather than float (DATA-06). Summing thousands of
    #: IEEE-754 doubles is order-dependent, and since row 1b this column is
    #: summed as a spend GATE rather than shown as a report.
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_token_usage_user_created", "user_id", "created_at"),)
