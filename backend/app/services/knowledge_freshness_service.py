"""KnowledgeFreshnessService — unified view of knowledge-base freshness.

Combines three independent signals into a single human-friendly summary that
the orchestrator surfaces as ``staleness_warning`` so the agent (and the user)
know whether to trust the answers:

- DB index age — was the schema introspected recently? (``DbIndexService``)
- Code-DB sync status — does the live schema still match the indexed view?
  (``CodeDbSyncService``)
- Git head vs indexed SHA — does the knowledge base match the current code?
  (``GitTracker``)

Returning ``None`` means everything is fresh enough to be silent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeFreshness:
    """Structured snapshot of knowledge-base freshness for a project."""

    db_index_age_hours: float | None = None
    db_index_stale: bool = False
    sync_status: str | None = None
    sync_stale: bool = False
    git_behind_commits: int | None = None
    git_unindexed: bool = False
    # M6: code-graph signal. ``code_graph_symbol_count`` is the canonical
    # "did we run M2/M5/M6?" answer; the SHA equality check is folded into
    # ``git_behind_commits`` since both come from the same indexer run.
    code_graph_symbol_count: int = 0
    code_graph_stale: bool = False
    warnings: list[str] = None  # type: ignore[assignment]

    def to_summary(self) -> str | None:
        """Render warnings as a single short string suitable for the prompt."""
        if not self.warnings:
            return None
        if len(self.warnings) == 1:
            return self.warnings[0]
        return "Knowledge freshness:\n- " + "\n- ".join(self.warnings)


class KnowledgeFreshnessService:
    """Unified freshness check across DB index, code-DB sync, and git head."""

    DB_INDEX_TTL_HOURS = 24

    async def evaluate(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        connection_id: str | None,
        repo_clone_dir: Path | None = None,
    ) -> KnowledgeFreshness:
        warnings: list[str] = []
        snapshot = KnowledgeFreshness(warnings=warnings)

        if connection_id:
            try:
                from app.services.db_index_service import DbIndexService

                db_svc = DbIndexService()
                age = await db_svc.get_index_age(session, connection_id)
                if age is None:
                    warnings.append(
                        "Database index is missing — agents will fall back to live schema lookups."
                    )
                else:
                    snapshot.db_index_age_hours = round(age.total_seconds() / 3600, 1)
                    if age > timedelta(hours=self.DB_INDEX_TTL_HOURS):
                        snapshot.db_index_stale = True
                        warnings.append(
                            "Database index is "
                            f"{snapshot.db_index_age_hours:.0f}h old (>{self.DB_INDEX_TTL_HOURS}h);"
                            " consider re-indexing."
                        )
            except Exception:
                logger.debug("freshness: db index check failed", exc_info=True)

            try:
                from app.services.code_db_sync_service import CodeDbSyncService

                sync_svc = CodeDbSyncService()
                snapshot.sync_status = await sync_svc.get_sync_status(session, connection_id)
                if snapshot.sync_status in ("stale", "failed"):
                    snapshot.sync_stale = True
                    warnings.append(
                        "Code-database sync is "
                        f"{snapshot.sync_status}; column conventions may be out of date."
                    )
            except Exception:
                logger.debug("freshness: sync status check failed", exc_info=True)

        # M6: code-graph freshness — empty graph means M2 either never ran
        # or was wiped. We only check when code_graph_enabled is set so
        # disabled installs don't see a noisy warning.
        try:
            from app.config import settings

            if settings.code_graph_enabled:
                from app.services.code_graph_service import CodeGraphService

                cg_svc = CodeGraphService()
                sym_count, _ = await cg_svc.count(session, project_id)
                snapshot.code_graph_symbol_count = sym_count
                if sym_count == 0:
                    snapshot.code_graph_stale = True
                    warnings.append(
                        "Code graph is empty — lineage and clustering features "
                        "will fall back to legacy heuristics."
                    )
        except Exception:
            logger.debug("freshness: code graph check failed", exc_info=True)

        if repo_clone_dir is not None:
            try:
                import asyncio

                from app.knowledge.git_tracker import GitTracker

                if repo_clone_dir.exists():
                    tracker = GitTracker()
                    last_sha = await tracker.get_last_indexed_sha(session, project_id)
                    if not last_sha:
                        snapshot.git_unindexed = True
                        warnings.append("Knowledge base has not been indexed yet.")
                    else:
                        # get_head_sha is blocking git I/O — never call it
                        # directly on the event loop.
                        head_sha = await asyncio.to_thread(
                            tracker.get_head_sha, repo_clone_dir
                        )
                        if head_sha and head_sha != last_sha:
                            behind = await tracker.count_commits_ahead(repo_clone_dir, last_sha)
                            # count_commits_ahead returns -1 on error; only a
                            # positive count is a real "behind" signal.
                            if behind and behind > 0:
                                snapshot.git_behind_commits = behind
                                warnings.append(
                                    f"Knowledge base is {behind} commit(s) behind HEAD;"
                                    " answers may reference outdated code."
                                )
                            else:
                                warnings.append("Knowledge base may be out of date.")
            except Exception:
                logger.debug("freshness: git head check failed", exc_info=True)

        return snapshot

    async def evaluate_summary(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        connection_id: str | None,
        repo_clone_dir: Path | None = None,
    ) -> str | None:
        snapshot = await self.evaluate(
            session,
            project_id=project_id,
            connection_id=connection_id,
            repo_clone_dir=repo_clone_dir,
        )
        return snapshot.to_summary()
