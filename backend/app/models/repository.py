"""ProjectRepository model — supports multiple Git repositories per project."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.project import Project


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

    indexing_status: Mapped[str] = mapped_column(String(20), default="idle")
    last_indexed_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: This repository's own webhook secret, Fernet-encrypted like every other secret
    #: in the schema (AUTH-05). One process-wide `GIT_WEBHOOK_SECRET` proved only
    #: "someone holds the deployment's secret", never "someone controls THIS
    #: project's repository" — so any tenant given the string could sign a body and
    #: drive any other tenant's worker into `generate_docs` on demand. NULL means the
    #: project predates per-project secrets and has none; the handler refuses rather
    #: than falling back to the global one, because a fallback is the hole.
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="repositories")  # noqa: F821
