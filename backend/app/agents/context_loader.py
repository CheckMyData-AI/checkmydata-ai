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
                )
            if not learnings:
                return None

            top = sorted(
                learnings,
                key=lambda lrn: (lrn.times_confirmed, lrn.confidence),
                reverse=True,
            )[:15]

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

    async def check_staleness(self, project_id: str, wf_id: str = "") -> str | None:
        try:
            from pathlib import Path

            from app.config import settings as app_settings
            from app.knowledge.git_tracker import GitTracker
            from app.models.base import async_session_factory

            repo_dir = Path(app_settings.repo_clone_base_dir) / project_id
            if not repo_dir.exists():
                return None

            git_tracker = GitTracker()
            async with async_session_factory() as session:
                last_sha = await git_tracker.get_last_indexed_sha(session, project_id)
            if not last_sha:
                return "Knowledge base has not been indexed yet."

            head_sha = git_tracker.get_head_sha(repo_dir)
            if head_sha == last_sha:
                return None

            behind = await git_tracker.count_commits_ahead(repo_dir, last_sha)
            if behind > 0:
                return (
                    f"Knowledge base is {behind} commit(s) behind the current HEAD. "
                    "Answers may be based on outdated code. Consider re-indexing."
                )
            return "Knowledge base may be out of date."
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
