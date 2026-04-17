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

        if repo_clone_dir is not None:
            try:
                from app.knowledge.git_tracker import GitTracker

                if repo_clone_dir.exists():
                    tracker = GitTracker()
                    last_sha = await tracker.get_last_indexed_sha(session, project_id)
                    if not last_sha:
                        snapshot.git_unindexed = True
                        warnings.append("Knowledge base has not been indexed yet.")
                    else:
                        head_sha = tracker.get_head_sha(repo_clone_dir)
                        if head_sha and head_sha != last_sha:
                            behind = await tracker.count_commits_ahead(repo_clone_dir, last_sha)
                            if behind:
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
