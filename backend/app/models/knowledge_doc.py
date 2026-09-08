import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: The inputs this document was generated FROM (`app.knowledge.doc_cache`), so a
    #: rebuild can tell that the source has not moved and skip the LLM call.
    #: NULL means "generated before the cache existed" — unknown, not unchanged, so the
    #: first run after deploy regenerates and records it. No backfill: a hash invented
    #: from the stored document would claim the document matches inputs nobody checked.
    content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
