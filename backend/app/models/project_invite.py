import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ProjectInvite(Base):
    __tablename__ = "project_invites"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    invited_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="editor",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )

    project: Mapped["Project"] = relationship(back_populates="invites")  # noqa: F821
    inviter: Mapped["User"] = relationship()  # noqa: F821
