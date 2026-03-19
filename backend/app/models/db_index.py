import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DbIndex(Base):
    """Per-table database index entry with LLM-generated analysis."""

    __tablename__ = "db_index"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "table_name",
            name="uq_db_index_conn_table",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    table_schema: Mapped[str] = mapped_column(String(255), default="public")
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_data_json: Mapped[str] = mapped_column(Text, default="[]")
    ordering_column: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latest_record_at: Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    relevance_score: Mapped[int] = mapped_column(Integer, default=3)
    business_description: Mapped[str] = mapped_column(Text, default="")
    data_patterns: Mapped[str] = mapped_column(Text, default="")
    column_notes_json: Mapped[str] = mapped_column(Text, default="{}")
    column_distinct_values_json: Mapped[str] = mapped_column(Text, default="{}")
    query_hints: Mapped[str] = mapped_column(Text, default="")

    numeric_format_notes: Mapped[str] = mapped_column(Text, default="{}")

    code_match_status: Mapped[str] = mapped_column(String(50), default="unknown")
    code_match_details: Mapped[str] = mapped_column(Text, default="")

    indexed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DbIndexSummary(Base):
    """Connection-level summary of the database index."""

    __tablename__ = "db_index_summary"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    total_tables: Mapped[int] = mapped_column(Integer, default=0)
    active_tables: Mapped[int] = mapped_column(Integer, default=0)
    empty_tables: Mapped[int] = mapped_column(Integer, default=0)
    orphan_tables: Mapped[int] = mapped_column(Integer, default=0)
    phantom_tables: Mapped[int] = mapped_column(Integer, default=0)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    recommendations: Mapped[str] = mapped_column(Text, default="")

    indexing_status: Mapped[str] = mapped_column(String(20), default="idle")

    indexed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
