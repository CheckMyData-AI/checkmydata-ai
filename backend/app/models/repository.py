"""ProjectRepository model — supports multiple Git repositories per project."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ProjectRepository(Base):
    __tablename__ = "project_repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), default="git_ssh")
    repo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), default="main")

    ssh_key_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ssh_keys.id", ondelete="SET NULL"), nullable=True
    )
    auth_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    indexing_status: Mapped[str] = mapped_column(String(20), default="idle")
    last_indexed_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="repositories")  # noqa: F821
