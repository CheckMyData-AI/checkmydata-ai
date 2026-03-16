import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RAGFeedback(Base):
    """Tracks which RAG chunks were used in a query and whether the query succeeded."""

    __tablename__ = "rag_feedback"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id"), nullable=False,
    )
    chunk_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), default="")
    distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    query_succeeded: Mapped[bool] = mapped_column(Boolean, default=True)
    question_snippet: Mapped[str] = mapped_column(Text, default="")
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
    )
