"""ContextLoader — loads orchestrator context lazily by intent.

Extracted from ``OrchestratorAgent`` to keep the orchestrator slim.
Contains helpers for table maps, KB checks, MCP checks, learnings,
staleness warnings, and project overviews.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.agents.base import AgentContext
from app.connectors.base import ConnectionConfig, connector_key
from app.core.workflow_tracker import WorkflowTracker
from app.knowledge.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class ContextData:
    """Aggregated context loaded for the orchestrator."""

    has_connection: bool = False
    has_kb: bool = False
    has_mcp: bool = False
    table_map: str = ""
    db_type: str | None = None
    project_overview: str | None = None
    recent_learnings: str | None = None
    staleness_warning: str | None = None
    active_insights: str | None = None


class ContextLoader:
    """Loads orchestrator context lazily based on intent."""

    def __init__(
        self,
        *,
        vector_store: VectorStore,
        tracker: WorkflowTracker,
        mcp_cache: dict[str, tuple[bool, float]],
        mcp_cache_ttl: float = 60.0,
    ) -> None:
        self._vector_store = vector_store
        self._tracker = tracker
        self._mcp_cache = mcp_cache
        self._MCP_CACHE_TTL = mcp_cache_ttl

    async def has_mcp_sources(self, project_id: str, wf_id: str = "") -> bool:
        """Check if the project has any MCP-type connections (cached for 60s)."""
        cached = self._mcp_cache.get(project_id)
        if cached:
            has, ts = cached
            if (time.monotonic() - ts) < self._MCP_CACHE_TTL:
                return has

        try:
            from app.models.base import async_session_factory
            from app.services.connection_service import ConnectionService

            conn_svc = ConnectionService()
            async with async_session_factory() as session:
                connections = await conn_svc.list_by_project(session, project_id)
                result = any(c.source_type == "mcp" for c in connections)
            self._mcp_cache[project_id] = (result, time.monotonic())
            return result
        except Exception:
            logger.debug("Failed to check MCP sources", exc_info=True)
            if wf_id:
                try:
                    await self._tracker.emit(
                        wf_id,
                        "orchestrator:warning",
                        "degraded",
                        "MCP source check failed; MCP tools unavailable this request",
                    )
                except Exception:
                    logger.debug("Failed to emit MCP degradation warning", exc_info=True)
            return False

    def has_knowledge_base(self, project_id: str) -> bool:
        try:
            collection = self._vector_store.get_or_create_collection(project_id)
            return collection.count() > 0
        except Exception:
            return False

    async def build_table_map(self, connection_id: str, wf_id: str = "") -> str:
        try:
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                entries = await svc.get_index(session, connection_id)
            return svc.build_table_map(entries)
        except Exception:
            logger.debug("Failed to build table map", exc_info=True)
            if wf_id:
                try:
                    await self._tracker.emit(
                        wf_id,
                        "orchestrator:warning",
                        "degraded",
                        "Schema map unavailable; SQL quality may be reduced",
                    )
                except Exception:
                    logger.debug("Failed to emit schema-map degradation warning", exc_info=True)
            return ""

    async def resolve_connection_id(
        self,
        project_id: str,
        cfg: ConnectionConfig,
    ) -> str | None:
        from app.models.base import async_session_factory
        from app.services.connection_service import ConnectionService

        target_key = connector_key(cfg)
        conn_svc = ConnectionService()
        async with async_session_factory() as session:
            connections = await conn_svc.list_by_project(session, project_id)
            for c in connections:
                c_cfg = await conn_svc.to_config(session, c)
                if connector_key(c_cfg) == target_key:
                    return c.id
        return None

    async def load_project_overview(self, project_id: str) -> str | None:
        """Load the pre-generated project knowledge overview."""
        try:
            from sqlalchemy import select

            from app.models.base import async_session_factory
            from app.models.project_cache import ProjectCache

            async with async_session_factory() as session:
                result = await session.execute(
                    select(ProjectCache.overview_text).where(ProjectCache.project_id == project_id)
                )
                text = result.scalar_one_or_none()
                if isinstance(text, str) and text:
                    return text
                return None
        except Exception:
            logger.debug("Failed to load project overview", exc_info=True)
            return None

    async def load_recent_learnings(
        self,
        context: AgentContext,
    ) -> str | None:
        """Load high-confidence / recent learnings for orchestrator context."""
        cfg = context.connection_config
        if not cfg or not cfg.connection_id:
            return None
        try:
            from app.models.base import async_session_factory
            from app.services.agent_learning_service import AgentLearningService

            svc = AgentLearningService()
            async with async_session_factory() as session:
                learnings = await svc.get_learnings(
                    session,
                    cfg.connection_id,
                    min_confidence=0.6,
                    active_only=True,
                    limit=15,
                )
            if not learnings:
                return None

            top = sorted(
                learnings,
                key=lambda lrn: (lrn.times_confirmed, lrn.confidence),
                reverse=True,
            )

            lines = ["RECENT AGENT LEARNINGS (verified insights):"]
            for lrn in top:
                conf = int(lrn.confidence * 100)
                lines.append(f"- [{lrn.category}] {lrn.subject}: {lrn.lesson} ({conf}%)")
            return "\n".join(lines)
        except Exception:
            logger.debug(
                "Failed to load recent learnings for orchestrator",
                exc_info=True,
            )
            return None

    async def load_relevant_insights(
        self,
        project_id: str,
        *,
        limit: int = 5,
        min_confidence: float = 0.5,
    ) -> str | None:
        """Load top-N active insights to inject into the orchestrator prompt.

        Returned text is a compact, agent-friendly summary; ``None`` when there
        are no relevant insights or the lookup fails. Surfacing insights here
        makes the agent aware of recent anomalies / known-good findings before
        deciding how to answer the next question.
        """
        if not project_id:
            return None
        try:
            from app.core.insight_memory import InsightMemoryService
            from app.models.base import async_session_factory

            svc = InsightMemoryService()
            async with async_session_factory() as session:
                insights = await svc.get_insights(
                    session,
                    project_id,
                    status="active",
                    min_confidence=min_confidence,
                    limit=limit,
                )
            if not insights:
                return None

            lines = ["ACTIVE INSIGHTS (recent findings — consider when answering):"]
            for ins in insights:
                conf = int(ins.confidence * 100)
                title = (ins.title or "")[:160]
                action = ""
                if ins.recommended_action:
                    action = f" → {ins.recommended_action[:140]}"
                lines.append(f"- [{ins.severity}] [{ins.insight_type}] {title} ({conf}%){action}")
            return "\n".join(lines)
        except Exception:
            logger.debug("Failed to load active insights", exc_info=True)
            return None

    async def load_relevant_knowledge(
        self,
        project_id: str,
        question: str,
        *,
        n_results: int = 3,
        max_chars: int = 1500,
    ) -> str | None:
        """Run a RAG query against the project's knowledge base for ``question``.

        Returns a compact, agent-friendly text block of the top ``n_results``
        chunks, capped at ``max_chars``, or ``None`` when the collection is
        empty / the lookup fails. Wiring this into ``_run_unified_agent`` lets
        the orchestrator reuse documentation context for normal SQL questions
        instead of only at repair-time.
        """
        if not project_id or not question or not question.strip():
            return None
        try:
            chunks = self._vector_store.query(project_id, question, n_results=n_results)
            if not chunks:
                return None
            lines = ["RELEVANT KNOWLEDGE (top documentation snippets):"]
            total = 0
            for chunk in chunks:
                doc = (chunk.get("document") or "").strip()
                if not doc:
                    continue
                meta = chunk.get("metadata") or {}
                source = meta.get("source_path") or meta.get("source") or "doc"
                snippet = doc[:400]
                line = f"- [{source}] {snippet}"
                total += len(line)
                if total > max_chars:
                    break
                lines.append(line)
            if len(lines) == 1:
                return None
            return "\n".join(lines)
        except Exception:
            logger.debug("Failed to load relevant knowledge", exc_info=True)
            return None

    async def check_staleness(
        self,
        project_id: str,
        wf_id: str = "",
        *,
        connection_id: str | None = None,
    ) -> str | None:
        """Return a single freshness warning combining DB index, sync, and git signals."""
        try:
            from pathlib import Path

            from app.config import settings as app_settings
            from app.models.base import async_session_factory
            from app.services.knowledge_freshness_service import (
                KnowledgeFreshnessService,
            )

            repo_dir = Path(app_settings.repo_clone_base_dir) / project_id
            svc = KnowledgeFreshnessService()
            async with async_session_factory() as session:
                return await svc.evaluate_summary(
                    session,
                    project_id=project_id,
                    connection_id=connection_id,
                    repo_clone_dir=repo_dir,
                )
        except Exception:
            logger.debug("Staleness check failed", exc_info=True)
            if wf_id:
                try:
                    await self._tracker.emit(
                        wf_id,
                        "orchestrator:warning",
                        "degraded",
                        "Staleness check failed; unable to verify knowledge base freshness",
                    )
                except Exception:
                    logger.debug("Failed to emit staleness degradation warning", exc_info=True)
            return None
