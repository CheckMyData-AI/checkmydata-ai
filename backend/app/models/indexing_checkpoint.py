import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IndexingCheckpoint(Base):
    """Persists intermediate indexing state for pipeline resumability.

    One row per project (unique constraint). Created when indexing starts,
    deleted on successful completion. If the process crashes, the row
    remains and allows the next run to resume from the last completed step.

    T22: ``completed_steps`` and ``processed_doc_paths`` used to be JSON
    ``TEXT`` blobs that were read, appended to, and rewritten on every
    update — an O(n) operation that became quadratic over the course of a
    long indexing run. They are now stored in dedicated append-only tables
    (:class:`IndexingCheckpointStep`, :class:`IndexingCheckpointDoc`). The
    original columns remain for backwards-compat with existing on-disk
    rows but are no longer written by new code.
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

    # Legacy JSON fields — retained for compatibility. See T22.
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
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class IndexingCheckpointStep(Base):
    """Append-only row per completed checkpoint step (T22).

    Replaces the ``IndexingCheckpoint.completed_steps`` JSON list. The
    unique constraint on ``(checkpoint_id, step_name)`` preserves the
    original dedup semantic.
    """

    __tablename__ = "indexing_checkpoint_step"
    __table_args__ = (
        UniqueConstraint(
            "checkpoint_id", "step_name", name="uq_indexing_checkpoint_step"
        ),
        Index("ix_indexing_checkpoint_step_cp", "checkpoint_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    checkpoint_id: Mapped[str] = mapped_column(
        ForeignKey("indexing_checkpoint.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class IndexingCheckpointDoc(Base):
    """Append-only row per processed document path (T22).

    Replaces the ``IndexingCheckpoint.processed_doc_paths`` JSON list. A
    unique constraint on ``(checkpoint_id, source_path)`` prevents
    duplicates — callers can simply swallow
    :class:`sqlalchemy.exc.IntegrityError` or filter against an existing
    set when bulk-inserting.
    """

    __tablename__ = "indexing_checkpoint_doc"
    __table_args__ = (
        UniqueConstraint(
            "checkpoint_id", "source_path", name="uq_indexing_checkpoint_doc"
        ),
        Index("ix_indexing_checkpoint_doc_cp", "checkpoint_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    checkpoint_id: Mapped[str] = mapped_column(
        ForeignKey("indexing_checkpoint.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
