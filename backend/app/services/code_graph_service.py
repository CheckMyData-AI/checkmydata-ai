"""Persistence and queries for the code knowledge graph (M2).

Two write paths:

* :meth:`save` — "full replace": transactionally deletes the project's rows
  and inserts the supplied graph. Used on full (re)index runs.
* :meth:`save_incremental` — merges a changed-files-only graph into the
  persisted one (preserving unchanged files, replacing changed files, and
  dropping deleted files). Used on incremental runs so the graph stays
  globally complete instead of collapsing to the changed subset.

Reads are indexed by ``(project_id, ...)`` lookups for low latency.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select, update

from app.knowledge.ast_parser import Symbol
from app.knowledge.code_graph import CodeGraph, GraphEdge
from app.models.code_graph import CodeCluster, CodeGraphEdge, CodeGraphSymbol

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class CodeGraphService:
    """CRUD for code graph symbols and edges, plus graph-shaped read helpers."""

    # ------------------------------------------------------------------
    # Write path: full replace per indexing run.
    # ------------------------------------------------------------------

    async def save(
        self,
        session: AsyncSession,
        project_id: str,
        graph: CodeGraph,
    ) -> tuple[int, int]:
        """Replace the project's symbols + edges atomically.

        Returns ``(symbol_count, edge_count)``. Callers should commit the
        outer transaction. We batch inserts in chunks of 1000 to avoid
        oversize parameter lists.
        """
        await session.execute(
            delete(CodeGraphSymbol).where(CodeGraphSymbol.project_id == project_id)
        )
        await session.execute(delete(CodeGraphEdge).where(CodeGraphEdge.project_id == project_id))

        sym_rows = [
            {
                "project_id": project_id,
                "uid": s.uid,
                "kind": s.kind,
                "name": s.name,
                "file_path": s.file_path,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "parent_uid": s.parent_uid,
                "language": s.language,
                "decorators_json": json.dumps(list(s.decorators), ensure_ascii=False),
                "signature": s.signature,
                "docstring": s.docstring,
                "cluster_id": None,
            }
            for s in graph.symbols.values()
        ]
        edge_rows = [
            {
                "project_id": project_id,
                "src_uid": e.src_uid,
                "dst_uid": e.dst_uid,
                "edge_type": e.edge_type,
                "confidence": float(e.confidence),
                "attrs_json": json.dumps(e.attrs, ensure_ascii=False),
            }
            for e in graph.edges
        ]
        await self._bulk_insert(session, CodeGraphSymbol, sym_rows)
        await self._bulk_insert(session, CodeGraphEdge, edge_rows)
        await session.flush()
        logger.info(
            "code_graph_service: replaced project=%s symbols=%d edges=%d",
            project_id[:8],
            len(sym_rows),
            len(edge_rows),
        )
        return len(sym_rows), len(edge_rows)

    async def save_incremental(
        self,
        session: AsyncSession,
        project_id: str,
        new_graph: CodeGraph,
        affected_files: set[str] | list[str],
    ) -> tuple[int, int]:
        """Merge a partial (changed-files-only) graph into the persisted graph.

        On incremental indexing runs ``new_graph`` only contains symbols for
        the files that changed in this commit range. A naive :meth:`save`
        would delete the entire project graph and reinsert only that subset,
        corrupting M5 lineage / M6 clustering for unchanged files. Instead we
        load the existing graph, drop every symbol/edge belonging to an
        ``affected_files`` path (changed *or* deleted), splice in ``new_graph``,
        and persist the union.

        When the project has no persisted graph yet this degrades to a plain
        :meth:`save` of ``new_graph``.
        """
        existing = await self.load_graph(session, project_id)
        if existing is None:
            return await self.save(session, project_id, new_graph)
        merged = self._merge_graphs(existing, new_graph, set(affected_files))
        return await self.save(session, project_id, merged)

    @staticmethod
    def _merge_graphs(
        existing: CodeGraph,
        new_graph: CodeGraph,
        affected_files: set[str],
    ) -> CodeGraph:
        """Produce a merged graph: existing minus affected files, plus new_graph.

        Symbols whose ``file_path`` is in ``affected_files`` are removed from
        the existing graph (the changed files are re-supplied by ``new_graph``;
        deleted files simply vanish). Edges are kept from the existing graph
        only when their *source* file is not affected; all edges from
        ``new_graph`` are added. ``file:<path>`` import-edge sources are
        attributed to ``<path>``.
        """
        existing_sym_file = {
            uid: sym.file_path for uid, sym in existing.symbols.items()
        }

        def _edge_source_file(src_uid: str) -> str | None:
            if src_uid.startswith("file:"):
                return src_uid[len("file:") :]
            return existing_sym_file.get(src_uid)

        merged_symbols = [
            sym
            for sym in existing.symbols.values()
            if sym.file_path not in affected_files
        ]
        merged_symbols.extend(new_graph.symbols.values())

        merged_edges = [
            edge
            for edge in existing.edges
            if _edge_source_file(edge.src_uid) not in affected_files
        ]
        merged_edges.extend(new_graph.edges)

        return CodeGraph(symbols=merged_symbols, edges=merged_edges)

    @staticmethod
    async def _bulk_insert(
        session: AsyncSession, model_cls: Any, rows: list[dict[str, Any]]
    ) -> None:
        if not rows:
            return
        batch_size = 1000
        for i in range(0, len(rows), batch_size):
            session.add_all(model_cls(**r) for r in rows[i : i + batch_size])

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    async def get_callers(
        self,
        session: AsyncSession,
        project_id: str,
        target_uid: str,
        *,
        edge_type: str = "CALLS",
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> list[CodeGraphSymbol]:
        """Symbols whose outgoing edge of ``edge_type`` lands on ``target_uid``."""
        result = await session.execute(
            select(CodeGraphSymbol)
            .join(
                CodeGraphEdge,
                CodeGraphEdge.src_uid == CodeGraphSymbol.uid,
            )
            .where(CodeGraphSymbol.project_id == project_id)
            .where(CodeGraphEdge.project_id == project_id)
            .where(CodeGraphEdge.dst_uid == target_uid)
            .where(CodeGraphEdge.edge_type == edge_type)
            .where(CodeGraphEdge.confidence >= min_confidence)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_callees(
        self,
        session: AsyncSession,
        project_id: str,
        source_uid: str,
        *,
        edge_type: str = "CALLS",
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> list[CodeGraphSymbol]:
        """Symbols ``source_uid`` directly references via ``edge_type``."""
        result = await session.execute(
            select(CodeGraphSymbol)
            .join(
                CodeGraphEdge,
                CodeGraphEdge.dst_uid == CodeGraphSymbol.uid,
            )
            .where(CodeGraphSymbol.project_id == project_id)
            .where(CodeGraphEdge.project_id == project_id)
            .where(CodeGraphEdge.src_uid == source_uid)
            .where(CodeGraphEdge.edge_type == edge_type)
            .where(CodeGraphEdge.confidence >= min_confidence)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def query_by_name(
        self,
        session: AsyncSession,
        project_id: str,
        name: str,
        *,
        limit: int = 50,
    ) -> list[CodeGraphSymbol]:
        """Symbols matching the given short name exactly."""
        result = await session.execute(
            select(CodeGraphSymbol)
            .where(CodeGraphSymbol.project_id == project_id)
            .where(CodeGraphSymbol.name == name)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count(self, session: AsyncSession, project_id: str) -> tuple[int, int]:
        """Cheap (symbol_count, edge_count) for freshness/metrics."""
        from sqlalchemy import func as sa_func

        sym_count = await session.scalar(
            select(sa_func.count(CodeGraphSymbol.id)).where(
                CodeGraphSymbol.project_id == project_id
            )
        )
        edge_count = await session.scalar(
            select(sa_func.count(CodeGraphEdge.id)).where(CodeGraphEdge.project_id == project_id)
        )
        return int(sym_count or 0), int(edge_count or 0)

    async def load_symbols(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> list[CodeGraphSymbol]:
        """Load all symbols for a project; used by M5 lineage + M6 clustering."""
        result = await session.execute(
            select(CodeGraphSymbol).where(CodeGraphSymbol.project_id == project_id)
        )
        return list(result.scalars().all())

    async def load_edges(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        edge_type: str | None = None,
        min_confidence: float = 0.0,
    ) -> list[CodeGraphEdge]:
        """Load edges for a project, optionally filtered by type/confidence."""
        stmt = select(CodeGraphEdge).where(CodeGraphEdge.project_id == project_id)
        if edge_type is not None:
            stmt = stmt.where(CodeGraphEdge.edge_type == edge_type)
        if min_confidence > 0:
            stmt = stmt.where(CodeGraphEdge.confidence >= min_confidence)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def load_graph(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> CodeGraph | None:
        """Reconstruct an in-memory :class:`CodeGraph` from persisted rows.

        Used by the pipeline runner on resume paths where the in-memory
        ``state.code_graph`` was lost (e.g. an incremental run that produced
        no parsed files but the project still has a graph from an earlier
        full index). Returns ``None`` if the project has zero symbols.
        """
        symbol_rows = await self.load_symbols(session, project_id)
        if not symbol_rows:
            return None
        edge_rows = await self.load_edges(session, project_id)
        symbols = [self.to_symbol(row) for row in symbol_rows]
        edges = [self.to_edge(row) for row in edge_rows]
        return CodeGraph(symbols=symbols, edges=edges)

    @staticmethod
    def to_symbol(row: CodeGraphSymbol) -> Symbol:
        """Convert a DB row into an in-memory :class:`Symbol` (lossless)."""
        try:
            decorators = tuple(json.loads(row.decorators_json or "[]"))
        except Exception:
            decorators = ()
        return Symbol(
            uid=row.uid,
            kind=row.kind,
            name=row.name,
            file_path=row.file_path,
            start_line=row.start_line,
            end_line=row.end_line,
            parent_uid=row.parent_uid,
            language=row.language,
            decorators=decorators,
            signature=row.signature or "",
            docstring=row.docstring or "",
        )

    @staticmethod
    def to_edge(row: CodeGraphEdge) -> GraphEdge:
        """Convert a DB row into an in-memory :class:`GraphEdge`."""
        try:
            attrs = json.loads(row.attrs_json or "{}")
            if not isinstance(attrs, dict):
                attrs = {}
        except Exception:
            attrs = {}
        return GraphEdge(
            src_uid=row.src_uid,
            dst_uid=row.dst_uid,
            edge_type=row.edge_type,
            confidence=float(row.confidence),
            attrs=attrs,
        )

    # ------------------------------------------------------------------
    # M6: clustering persistence + lookups
    # ------------------------------------------------------------------

    async def save_clusters(
        self,
        session: AsyncSession,
        project_id: str,
        clusters: list[Any],
    ) -> int:
        """Replace stored clusters and update symbol ``cluster_id`` fields.

        ``clusters`` is a list of :class:`app.knowledge.code_clustering.Cluster`
        (untyped here to avoid circular imports). Two writes happen
        atomically inside the caller's transaction:

        1. ``code_clusters`` rows are wiped + reinserted.
        2. ``code_graph_symbols.cluster_id`` is bulk-updated using the
           membership map encoded in ``cluster.member_uids``.
        """
        # 1. Reset existing cluster metadata.
        await session.execute(delete(CodeCluster).where(CodeCluster.project_id == project_id))

        if not clusters:
            await session.execute(
                update(CodeGraphSymbol)
                .where(CodeGraphSymbol.project_id == project_id)
                .values(cluster_id=None)
            )
            await session.flush()
            return 0

        rows = [
            {
                "project_id": project_id,
                "cluster_id": c.cluster_id,
                "label": c.label,
                "description": c.description,
                "symbol_count": c.symbol_count,
                "table_names_json": json.dumps(list(c.table_names), ensure_ascii=False),
                "file_paths_json": json.dumps(list(c.file_paths), ensure_ascii=False),
            }
            for c in clusters
        ]
        await self._bulk_insert(session, CodeCluster, rows)

        # 2. Update symbol membership. We do this in batches keyed by
        # cluster_id; each UPDATE fires once per cluster (small N).
        for cluster in clusters:
            uids = list(cluster.member_uids)
            if not uids:
                continue
            for i in range(0, len(uids), 1000):
                chunk = uids[i : i + 1000]
                await session.execute(
                    update(CodeGraphSymbol)
                    .where(CodeGraphSymbol.project_id == project_id)
                    .where(CodeGraphSymbol.uid.in_(chunk))
                    .values(cluster_id=cluster.cluster_id)
                )
        # 3. Null out symbols not in any cluster (idempotency).
        all_member_uids: set[str] = set()
        for c in clusters:
            all_member_uids.update(c.member_uids)
        if all_member_uids:
            await session.execute(
                update(CodeGraphSymbol)
                .where(CodeGraphSymbol.project_id == project_id)
                .where(CodeGraphSymbol.uid.notin_(all_member_uids))
                .values(cluster_id=None)
            )
        await session.flush()
        logger.info(
            "code_graph_service: saved %d clusters for project=%s",
            len(rows),
            project_id[:8],
        )
        return len(rows)

    async def get_clusters(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> list[CodeCluster]:
        """All clusters for a project ordered by descending symbol count."""
        result = await session.execute(
            select(CodeCluster)
            .where(CodeCluster.project_id == project_id)
            .order_by(CodeCluster.symbol_count.desc(), CodeCluster.cluster_id)
        )
        return list(result.scalars().all())

    async def get_cluster_by_label(
        self,
        session: AsyncSession,
        project_id: str,
        label_substring: str,
    ) -> list[CodeCluster]:
        """Case-insensitive substring match against cluster ``label``."""
        if not label_substring:
            return []
        from sqlalchemy import func as sa_func

        result = await session.execute(
            select(CodeCluster)
            .where(CodeCluster.project_id == project_id)
            .where(sa_func.lower(CodeCluster.label).like(f"%{label_substring.lower()}%"))
            .order_by(CodeCluster.symbol_count.desc())
        )
        return list(result.scalars().all())

    async def get_tables_in_cluster(
        self,
        session: AsyncSession,
        project_id: str,
        cluster_id_or_label: str,
    ) -> list[str]:
        """Resolve a cluster handle (id or label substring) to its tables."""
        if not cluster_id_or_label:
            return []
        # 1. Exact cluster_id match.
        result = await session.execute(
            select(CodeCluster)
            .where(CodeCluster.project_id == project_id)
            .where(CodeCluster.cluster_id == cluster_id_or_label)
            .limit(1)
        )
        cluster = result.scalar_one_or_none()
        if cluster is None:
            # 2. Label substring fallback.
            label_matches = await self.get_cluster_by_label(
                session, project_id, cluster_id_or_label
            )
            cluster = label_matches[0] if label_matches else None
        if cluster is None:
            return []
        try:
            tables = json.loads(cluster.table_names_json or "[]")
        except Exception:
            tables = []
        return [t for t in tables if isinstance(t, str)]
