import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    #: Whether the run that created this checkpoint was a FULL rebuild (KNOW-08).
    #: A full-rebuild checkpoint carries `last_sha = None` and the whole blob list as
    #: `changed_files`, which an incremental resume reads as "everything changed" — so the
    #: nightly sync silently continued an abandoned full rebuild under a ceiling sized for
    #: a different job. `NULL` means a checkpoint written before this column existed:
    #: unknown, and treated as full, because resuming an unknown as incremental is the
    #: mistake this records.
    force_full: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IndexingCheckpointStep(Base):
    """Append-only row per completed checkpoint step (T22).

    Replaces the ``IndexingCheckpoint.completed_steps`` JSON list. The
    unique constraint on ``(checkpoint_id, step_name)`` preserves the
    original dedup semantic.
    """

    __tablename__ = "indexing_checkpoint_step"
    __table_args__ = (
        UniqueConstraint("checkpoint_id", "step_name", name="uq_indexing_checkpoint_step"),
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
        UniqueConstraint("checkpoint_id", "source_path", name="uq_indexing_checkpoint_doc"),
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
