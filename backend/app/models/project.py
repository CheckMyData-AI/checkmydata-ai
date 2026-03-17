import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
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
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    indexing_llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    indexing_llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    agent_llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sql_llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sql_llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_rule_initialized: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    connections: Mapped[list["Connection"]] = relationship(  # noqa: F821
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(  # noqa: F821
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    members: Mapped[list["ProjectMember"]] = relationship(  # noqa: F821
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    invites: Mapped[list["ProjectInvite"]] = relationship(  # noqa: F821
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    knowledge_docs: Mapped[list["KnowledgeDoc"]] = relationship(  # noqa: F821
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    commit_indices: Mapped[list["CommitIndex"]] = relationship(  # noqa: F821
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    caches: Mapped[list["ProjectCache"]] = relationship(  # noqa: F821
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    rag_feedbacks: Mapped[list["RAGFeedback"]] = relationship(  # noqa: F821
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    owner: Mapped["User | None"] = relationship()  # noqa: F821
