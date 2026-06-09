"""KnowledgeCatalogService — unified read-facade over the knowledge stores.

Phase 1 of the Knowledge Architecture roadmap. This service does **not** own
any storage; it assembles a structured, traceable :class:`ContextPack` (and a
lightweight ``knowledge_health`` view) by reading from the existing services:

- ``DbIndexService``            → ``table`` artifacts
- ``CodeDbSyncService``         → ``lineage_edge`` artifacts + per-table sync notes
- ``AgentLearningService``      → ``learning`` artifacts (per-connection)
- ``InsightMemoryService``      → ``insight`` artifacts
- ``CustomRulesEngine``         → ``rule`` artifacts
- ChromaDB / HybridRetriever    → ``rag_chunk`` artifacts (optional)
- ``KnowledgeFreshnessService`` → aggregated, actionable freshness

Every section is independently guarded so a failing store degrades gracefully
(vision invariant #5) rather than failing the whole pack. See
``docs/KNOWLEDGE_CATALOG.md`` for the artifact contract.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.knowledge.context_pack import Artifact, ContextPack

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.agents.context_planner import ContextPlan

logger = logging.getLogger(__name__)


def _age_hours(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    try:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - ts
        return round(delta.total_seconds() / 3600, 1)
    except Exception:
        return None


def _iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    try:
        return ts.isoformat()
    except Exception:
        return None


class KnowledgeCatalogService:
    """Read-facade assembling a :class:`ContextPack` from existing stores."""

    def __init__(self, *, vector_store: Any | None = None) -> None:
        # Optional — only needed to populate ``rag_chunks``. The health view and
        # the structured artifacts work without it.
        self._vector_store = vector_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_knowledge_health(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        connection_id: str | None,
        repo_clone_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Return an actionable freshness snapshot + artifact counts for the UI."""
        freshness = await self._freshness(
            session,
            project_id=project_id,
            connection_id=connection_id,
            repo_clone_dir=repo_clone_dir,
        )
        counts = await self._artifact_counts(
            session, project_id=project_id, connection_id=connection_id
        )
        return {
            "project_id": project_id,
            "connection_id": connection_id,
            "freshness": freshness,
            "artifact_counts": counts,
        }

    async def get_context_pack(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        connection_id: str | None,
        question: str = "",
        budget_tokens: int = 8000,
        table_limit: int = 40,
        learning_limit: int = 15,
        insight_limit: int = 5,
        rag_results: int = 3,
        repo_clone_dir: Path | None = None,
        plan: ContextPlan | None = None,
    ) -> ContextPack:
        """Assemble the unified, traceable context bundle for the orchestrator.

        When a Phase 4 :class:`~app.agents.context_planner.ContextPlan` is
        supplied, only the categories it requests are loaded (query-aware lazy
        loading) and its per-category limits override the defaults. Without a
        plan every category loads at the default limits (legacy behaviour).
        Every artifact is enriched with a trust-layer view before returning.
        """
        from app.agents.context_planner import ContextNeed

        def _wants(need: ContextNeed) -> bool:
            return plan is None or plan.wants(need)

        def _limit(need: ContextNeed, default: int) -> int:
            return plan.limit_for(need) if plan is not None else default

        if plan is not None:
            budget_tokens = plan.budget_tokens

        pack = ContextPack(
            project_id=project_id,
            connection_id=connection_id,
            question=question,
        )
        sources: set[str] = set()

        sync_by_table: dict[str, Any] = {}
        if connection_id:
            # Sync rows back both lineage and table sync_notes; load them when
            # either category is wanted.
            need_lineage = _wants(ContextNeed.LINEAGE)
            need_tables = _wants(ContextNeed.TABLES)
            if need_lineage or need_tables:
                sync_rows = await self._load_sync_rows(session, connection_id)
                sync_by_table = {r.table_name: r for r in sync_rows}
                if need_lineage:
                    pack.lineage = self._lineage_artifacts(sync_rows, connection_id)
                    if pack.lineage:
                        sources.add("lineage")

            if need_tables:
                pack.tables = await self._table_artifacts(
                    session,
                    connection_id=connection_id,
                    limit=_limit(ContextNeed.TABLES, table_limit),
                    sync_by_table=sync_by_table,
                )
                if pack.tables:
                    sources.add("db_index")

            if _wants(ContextNeed.LEARNINGS):
                pack.learnings = await self._learning_artifacts(
                    session,
                    connection_id=connection_id,
                    limit=_limit(ContextNeed.LEARNINGS, learning_limit),
                )
                if pack.learnings:
                    sources.add("learnings")

        if _wants(ContextNeed.INSIGHTS):
            pack.insights = await self._insight_artifacts(
                session, project_id=project_id, limit=_limit(ContextNeed.INSIGHTS, insight_limit)
            )
            if pack.insights:
                sources.add("insights")

        if _wants(ContextNeed.RULES):
            pack.rules = self._rule_artifacts(project_id=project_id)
            if pack.rules:
                sources.add("rules")

        if _wants(ContextNeed.RAG) and question and self._vector_store is not None:
            pack.rag_chunks = self._rag_artifacts(
                project_id=project_id,
                question=question,
                n_results=_limit(ContextNeed.RAG, rag_results),
            )
            if pack.rag_chunks:
                sources.add("rag")

        pack.freshness = await self._freshness(
            session,
            project_id=project_id,
            connection_id=connection_id,
            repo_clone_dir=repo_clone_dir,
        )
        pack.sources_used = sorted(sources)
        pack.token_budget = {"total": budget_tokens}
        if plan is not None:
            pack.plan = plan.to_dict()
        self._enrich_trust(pack)
        return pack

    @staticmethod
    def _enrich_trust(pack: ContextPack) -> None:
        """Attach a trust-layer view (confidence_label, freshness_label, badge)
        to every artifact, reusing :class:`TrustService` so badges are
        consistent with insight presentation elsewhere."""
        from app.core.trust_layer import TrustedInsight, TrustService

        for art in pack.all_artifacts():
            age = art.freshness.get("age_hours")
            try:
                age_h = float(age) if age is not None else 0.0
            except (TypeError, ValueError):
                age_h = 0.0
            # Reuse TrustedInsight's label logic without constructing a full
            # insight: the labels are pure functions of confidence/freshness.
            ti = TrustedInsight(
                insight_id=art.id,
                title=art.title,
                description="",
                insight_type=art.type,
                severity="info",
                confidence=art.confidence,
                data_freshness_hours=age_h,
            )
            art.trust = {
                "confidence_label": ti.confidence_label,
                "freshness_label": ti.freshness_label,
                "badge": TrustService.format_trust_badge(art.confidence),
            }

    # ------------------------------------------------------------------
    # Section builders (each independently guarded)
    # ------------------------------------------------------------------

    async def _table_artifacts(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        limit: int,
        sync_by_table: dict[str, Any],
    ) -> list[Artifact]:
        try:
            from app.services.db_index_service import DbIndexService

            rows = await DbIndexService().get_index(session, connection_id)
        except Exception:
            logger.debug("catalog: table load failed", exc_info=True)
            return []

        artifacts: list[Artifact] = []
        for row in rows[:limit]:
            sync = sync_by_table.get(row.table_name)
            sync_notes = []
            if sync is not None:
                if getattr(sync, "conversion_warnings", ""):
                    sync_notes.append(sync.conversion_warnings)
                if getattr(sync, "business_logic_notes", ""):
                    sync_notes.append(sync.business_logic_notes)
            schema = getattr(row, "table_schema", "public") or "public"
            indexed_at = getattr(row, "indexed_at", None)
            artifacts.append(
                Artifact(
                    id=f"table:{connection_id}::{schema}.{row.table_name}",
                    type="table",
                    title=row.table_name,
                    summary=(row.business_description or "")[:280],
                    provenance={
                        "source": "db_index",
                        "source_ref": f"connection:{connection_id}",
                        "produced_by": "DbIndexPipeline",
                        "commit_sha": None,
                    },
                    freshness={
                        "indexed_at": _iso(indexed_at),
                        "age_hours": _age_hours(indexed_at),
                    },
                    confidence=min(1.0, (getattr(row, "relevance_score", 3) or 3) / 5.0),
                    payload={
                        "schema": schema,
                        "column_count": getattr(row, "column_count", 0),
                        "row_count": getattr(row, "row_count", None),
                        "code_match_status": getattr(row, "code_match_status", "unknown"),
                        "sync_notes": sync_notes,
                    },
                )
            )
        return artifacts

    async def _load_sync_rows(self, session: AsyncSession, connection_id: str) -> list[Any]:
        try:
            from app.services.code_db_sync_service import CodeDbSyncService

            return await CodeDbSyncService().get_sync(session, connection_id)
        except Exception:
            logger.debug("catalog: sync load failed", exc_info=True)
            return []

    def _lineage_artifacts(self, sync_rows: list[Any], connection_id: str) -> list[Artifact]:
        artifacts: list[Artifact] = []
        for row in sync_rows:
            entity = getattr(row, "entity_name", None)
            if not entity:
                continue
            synced_at = getattr(row, "synced_at", None)
            artifacts.append(
                Artifact(
                    id=f"lineage:{connection_id}::{entity}->{row.table_name}",
                    type="lineage_edge",
                    title=f"{entity} → {row.table_name}",
                    summary=(getattr(row, "data_format_notes", "") or "")[:200],
                    provenance={
                        "source": "code_db_sync",
                        "source_ref": f"connection:{connection_id}",
                        "produced_by": "CodeDbSyncPipeline",
                        "entity_file_path": getattr(row, "entity_file_path", None),
                    },
                    freshness={"indexed_at": _iso(synced_at), "age_hours": _age_hours(synced_at)},
                    confidence=min(1.0, (getattr(row, "confidence_score", 3) or 3) / 5.0),
                    payload={
                        "entity_name": entity,
                        "table_name": row.table_name,
                        "read_count": getattr(row, "read_count", 0),
                        "write_count": getattr(row, "write_count", 0),
                    },
                )
            )
        return artifacts

    async def _learning_artifacts(
        self, session: AsyncSession, *, connection_id: str, limit: int
    ) -> list[Artifact]:
        try:
            from app.services.agent_learning_service import AgentLearningService

            svc = AgentLearningService()
            rows = await svc.get_learnings(
                session, connection_id, min_confidence=0.6, active_only=True, limit=200
            )
            rows = sorted(rows, key=AgentLearningService.priority_score, reverse=True)[:limit]
        except Exception:
            logger.debug("catalog: learnings load failed", exc_info=True)
            return []

        artifacts: list[Artifact] = []
        for lrn in rows:
            artifacts.append(
                Artifact(
                    id=f"learning:{connection_id}::{lrn.id}",
                    type="learning",
                    title=f"[{lrn.category}] {lrn.subject}",
                    summary=(lrn.lesson or "")[:280],
                    provenance={
                        "source": "learnings",
                        "source_ref": f"connection:{connection_id}",
                        "produced_by": "AgentLearningService",
                    },
                    freshness={
                        "indexed_at": _iso(getattr(lrn, "updated_at", None)),
                        "age_hours": _age_hours(getattr(lrn, "updated_at", None)),
                    },
                    confidence=float(getattr(lrn, "confidence", 0.0) or 0.0),
                    payload={
                        "category": lrn.category,
                        "times_confirmed": getattr(lrn, "times_confirmed", 0),
                    },
                )
            )
        return artifacts

    async def _insight_artifacts(
        self, session: AsyncSession, *, project_id: str, limit: int
    ) -> list[Artifact]:
        try:
            from app.core.insight_memory import InsightMemoryService

            rows = await InsightMemoryService().get_insights(
                session, project_id, status="active", min_confidence=0.5, limit=limit
            )
        except Exception:
            logger.debug("catalog: insights load failed", exc_info=True)
            return []

        artifacts: list[Artifact] = []
        for ins in rows:
            artifacts.append(
                Artifact(
                    id=f"insight:{project_id}::{ins.id}",
                    type="insight",
                    title=(ins.title or "")[:200],
                    summary=(getattr(ins, "recommended_action", "") or "")[:200],
                    provenance={
                        "source": "insights",
                        "source_ref": f"project:{project_id}",
                        "produced_by": "InsightMemoryService",
                    },
                    freshness={
                        "indexed_at": _iso(getattr(ins, "updated_at", None)),
                        "age_hours": _age_hours(getattr(ins, "updated_at", None)),
                    },
                    confidence=float(getattr(ins, "confidence", 0.0) or 0.0),
                    payload={
                        "severity": getattr(ins, "severity", "info"),
                        "insight_type": getattr(ins, "insight_type", ""),
                    },
                )
            )
        return artifacts

    def _rule_artifacts(self, *, project_id: str) -> list[Artifact]:
        try:
            from app.knowledge.custom_rules import CustomRulesEngine

            rules = CustomRulesEngine().load_rules()
        except Exception:
            logger.debug("catalog: rules load failed", exc_info=True)
            return []

        artifacts: list[Artifact] = []
        for rule in rules:
            artifacts.append(
                Artifact(
                    id=f"rule:{project_id}::{rule.name}",
                    type="rule",
                    title=rule.name,
                    summary=(rule.content or "")[:280],
                    provenance={
                        "source": "rules",
                        "source_ref": rule.file_path,
                        "produced_by": "CustomRulesEngine",
                    },
                    confidence=1.0,
                    payload={"format": rule.format},
                )
            )
        return artifacts

    def _rag_artifacts(self, *, project_id: str, question: str, n_results: int) -> list[Artifact]:
        if self._vector_store is None:
            return []
        try:
            chunks = self._vector_store.query(project_id, question, n_results=n_results)
        except Exception:
            logger.debug("catalog: rag query failed", exc_info=True)
            return []

        artifacts: list[Artifact] = []
        for i, chunk in enumerate(chunks or []):
            doc = (chunk.get("document") or "").strip()
            if not doc:
                continue
            meta = chunk.get("metadata") or {}
            source = meta.get("source_path") or meta.get("source") or "doc"
            artifacts.append(
                Artifact(
                    id=f"rag:{project_id}::{meta.get('chunk_id', i)}",
                    type="rag_chunk",
                    title=str(source),
                    summary=doc[:400],
                    provenance={
                        "source": "rag",
                        "source_ref": str(source),
                        "produced_by": "embed_and_store",
                        "commit_sha": meta.get("commit_sha"),
                    },
                    freshness={"indexed_at": meta.get("indexed_at")},
                    confidence=0.5,
                    payload={"file_path": meta.get("file_path") or source},
                )
            )
        return artifacts

    async def _freshness(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        connection_id: str | None,
        repo_clone_dir: Path | None,
    ) -> dict[str, Any]:
        try:
            from app.config import settings
            from app.services.knowledge_freshness_service import KnowledgeFreshnessService

            if repo_clone_dir is None:
                repo_clone_dir = Path(settings.repo_clone_base_dir) / project_id
            snapshot = await KnowledgeFreshnessService().evaluate(
                session,
                project_id=project_id,
                connection_id=connection_id,
                repo_clone_dir=repo_clone_dir,
            )
            return snapshot.to_dict()
        except Exception:
            logger.debug("catalog: freshness evaluation failed", exc_info=True)
            return {"overall_stale": False, "warnings": []}

    async def _artifact_counts(
        self, session: AsyncSession, *, project_id: str, connection_id: str | None
    ) -> dict[str, int]:
        counts = {"tables": 0, "learnings": 0, "insights": 0, "rules": 0, "lineage": 0}
        if connection_id:
            try:
                from app.services.db_index_service import DbIndexService

                counts["tables"] = len(await DbIndexService().get_index(session, connection_id))
            except Exception:
                logger.debug("catalog: table count failed", exc_info=True)
            try:
                from app.services.code_db_sync_service import CodeDbSyncService

                rows = await CodeDbSyncService().get_sync(session, connection_id)
                counts["lineage"] = sum(1 for r in rows if getattr(r, "entity_name", None))
            except Exception:
                logger.debug("catalog: lineage count failed", exc_info=True)
            try:
                from app.services.agent_learning_service import AgentLearningService

                counts["learnings"] = len(
                    await AgentLearningService().get_learnings(
                        session, connection_id, min_confidence=0.0, active_only=True
                    )
                )
            except Exception:
                logger.debug("catalog: learnings count failed", exc_info=True)
        try:
            from app.core.insight_memory import InsightMemoryService

            counts["insights"] = len(
                await InsightMemoryService().get_insights(session, project_id, status="active")
            )
        except Exception:
            logger.debug("catalog: insight count failed", exc_info=True)
        try:
            from app.knowledge.custom_rules import CustomRulesEngine

            counts["rules"] = len(CustomRulesEngine().load_rules())
        except Exception:
            logger.debug("catalog: rule count failed", exc_info=True)
        return counts
