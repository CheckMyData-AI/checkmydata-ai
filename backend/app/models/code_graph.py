"""SQLAlchemy models for the code knowledge graph (M2).

Stores symbols and typed edges extracted from a project's source tree.
Refreshed on every successful indexing run via "full replace" semantics in
:class:`app.services.code_graph_service.CodeGraphService`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime as SADateTime
from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CodeGraphSymbol(Base):
    """A function / method / class / interface / enum extracted from source."""

    __tablename__ = "code_graph_symbols"
    __table_args__ = (
        Index("ix_code_graph_symbols_project", "project_id"),
        Index("ix_code_graph_symbols_project_name", "project_id", "name"),
        Index(
            "ix_code_graph_symbols_project_file",
            "project_id",
            "file_path",
        ),
        Index("ix_code_graph_symbols_uid", "uid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    uid: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_uid: Mapped[str | None] = mapped_column(String(512), nullable=True)
    language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decorators_json: Mapped[str] = mapped_column(Text, default="[]")
    signature: Mapped[str] = mapped_column(Text, default="")
    docstring: Mapped[str] = mapped_column(Text, default="")
    # M6 — populated by the clustering step.
    cluster_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        SADateTime(timezone=True), server_default=func.now()
    )


class CodeGraphEdge(Base):
    """A typed directed edge between two symbols (or file -> symbol for IMPORTS)."""

    __tablename__ = "code_graph_edges"
    __table_args__ = (
        Index("ix_code_graph_edges_project", "project_id"),
        Index("ix_code_graph_edges_src", "project_id", "src_uid"),
        Index("ix_code_graph_edges_dst", "project_id", "dst_uid"),
        Index("ix_code_graph_edges_type", "project_id", "edge_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    src_uid: Mapped[str] = mapped_column(String(512), nullable=False)
    dst_uid: Mapped[str] = mapped_column(String(512), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    attrs_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        SADateTime(timezone=True), server_default=func.now()
    )


class CodeCluster(Base):
    """M6: a functional cluster of code symbols (Louvain community).

    Symbol membership is stored on :class:`CodeGraphSymbol.cluster_id` so
    we don't have to maintain a separate join table. This row holds
    cluster-level metadata only: LLM-generated label/description and the
    aggregated table names + file paths that touch the cluster (used by the
    ``get_tables_in_cluster`` SQL agent tool).
    """

    __tablename__ = "code_clusters"
    __table_args__ = (
        Index("ix_code_clusters_project", "project_id"),
        # Unique per (project, cluster_id) — matches the migration.
        Index(
            "uq_code_clusters_project_cluster",
            "project_id",
            "cluster_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    table_names_json: Mapped[str] = mapped_column(Text, default="[]")
    file_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        SADateTime(timezone=True), server_default=func.now()
    )
