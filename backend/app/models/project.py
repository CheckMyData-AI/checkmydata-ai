import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    repo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    repo_branch: Mapped[str] = mapped_column(String(255), default="main")
    ssh_key_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ssh_keys.id", ondelete="SET NULL"), nullable=True
    )
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    default_llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    connections: Mapped[list["Connection"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan"
    )
    members: Mapped[list["ProjectMember"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan"
    )
    invites: Mapped[list["ProjectInvite"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan"
    )
    owner: Mapped["User | None"] = relationship()  # noqa: F821
