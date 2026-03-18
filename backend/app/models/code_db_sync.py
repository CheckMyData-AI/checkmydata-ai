import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CodeDbSync(Base):
    """Per-table code-database synchronization entry with LLM-generated analysis."""

    __tablename__ = "code_db_sync"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "table_name",
            name="uq_code_db_sync_conn_table",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)

    entity_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entity_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_columns_json: Mapped[str] = mapped_column(Text, default="[]")
    used_in_files_json: Mapped[str] = mapped_column(Text, default="[]")
    read_count: Mapped[int] = mapped_column(Integer, default=0)
    write_count: Mapped[int] = mapped_column(Integer, default=0)

    data_format_notes: Mapped[str] = mapped_column(Text, default="")
    column_sync_notes_json: Mapped[str] = mapped_column(Text, default="{}")
    business_logic_notes: Mapped[str] = mapped_column(Text, default="")
    conversion_warnings: Mapped[str] = mapped_column(Text, default="")
    query_recommendations: Mapped[str] = mapped_column(Text, default="")

    sync_status: Mapped[str] = mapped_column(String(50), default="unknown")
    confidence_score: Mapped[int] = mapped_column(Integer, default=3)

    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CodeDbSyncSummary(Base):
    """Connection-level summary of the code-database synchronization."""

    __tablename__ = "code_db_sync_summary"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    total_tables: Mapped[int] = mapped_column(Integer, default=0)
    synced_tables: Mapped[int] = mapped_column(Integer, default=0)
    code_only_tables: Mapped[int] = mapped_column(Integer, default=0)
    db_only_tables: Mapped[int] = mapped_column(Integer, default=0)
    mismatch_tables: Mapped[int] = mapped_column(Integer, default=0)

    global_notes: Mapped[str] = mapped_column(Text, default="")
    data_conventions: Mapped[str] = mapped_column(Text, default="")
    query_guidelines: Mapped[str] = mapped_column(Text, default="")

    sync_status: Mapped[str] = mapped_column(String(20), default="idle")

    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
