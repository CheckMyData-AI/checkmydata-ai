import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IndexingCheckpoint(Base):
    """Persists intermediate indexing state for pipeline resumability.

    One row per project (unique constraint). Created when indexing starts,
    deleted on successful completion. If the process crashes, the row
    remains and allows the next run to resume from the last completed step.
    """

    __tablename__ = "indexing_checkpoint"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    last_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
    )

    completed_steps: Mapped[str] = mapped_column(Text, default="[]")
    changed_files_json: Mapped[str] = mapped_column(Text, default="[]")
    deleted_files_json: Mapped[str] = mapped_column(Text, default="[]")
    profile_json: Mapped[str] = mapped_column(Text, default="{}")
    knowledge_json: Mapped[str] = mapped_column(Text, default="{}")
    processed_doc_paths: Mapped[str] = mapped_column(Text, default="[]")
    total_docs: Mapped[int] = mapped_column(Integer, default=0)

    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_step: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )
