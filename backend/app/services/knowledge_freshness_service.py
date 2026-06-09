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
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class FreshnessWarningDetail:
    """A single freshness warning with a machine-readable recommended action.

    Phase 1 (Knowledge Catalog): the legacy ``KnowledgeFreshness.warnings``
    list (plain strings) is preserved for the prompt; this structured detail is
    additive so the UI Knowledge Health panel can render one-click re-index
    buttons that call ``task_queue.enqueue`` (the consolidated execution path).
    """

    category: str  # "db_index" | "sync" | "git" | "code_graph"
    message: str
    severity: str = "warning"  # "info" | "warning" | "critical"
    # recommended_action.kind ∈ {reindex_db, reindex_repo, resync, none}
    action_kind: str = "none"
    action_label: str = ""
    connection_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "recommended_action": {
                "kind": self.action_kind,
                "label": self.action_label,
                "connection_id": self.connection_id,
            },
        }


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
    # Structured, actionable mirror of ``warnings`` (Phase 1, additive).
    details: list[FreshnessWarningDetail] = field(default_factory=list)

    @property
    def overall_stale(self) -> bool:
        return bool(self.warnings)

    def to_summary(self) -> str | None:
        """Render warnings as a single short string suitable for the prompt."""
        if not self.warnings:
            return None
        if len(self.warnings) == 1:
            return self.warnings[0]
        return "Knowledge freshness:\n- " + "\n- ".join(self.warnings)

    def to_dict(self) -> dict:
        """Serialise for the Knowledge Health API / UI panel."""
        return {
            "overall_stale": self.overall_stale,
            "db_index_age_hours": self.db_index_age_hours,
            "db_index_stale": self.db_index_stale,
            "sync_status": self.sync_status,
            "sync_stale": self.sync_stale,
            "git_behind_commits": self.git_behind_commits,
            "git_unindexed": self.git_unindexed,
            "code_graph_symbol_count": self.code_graph_symbol_count,
            "code_graph_stale": self.code_graph_stale,
            "warnings": [d.to_dict() for d in self.details],
        }


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

        def _warn(
            message: str,
            *,
            category: str,
            action_kind: str = "none",
            action_label: str = "",
            severity: str = "warning",
        ) -> None:
            warnings.append(message)
            snapshot.details.append(
                FreshnessWarningDetail(
                    category=category,
                    message=message,
                    severity=severity,
                    action_kind=action_kind,
                    action_label=action_label,
                    connection_id=connection_id,
                )
            )

        if connection_id:
            try:
                from app.services.db_index_service import DbIndexService

                db_svc = DbIndexService()
                age = await db_svc.get_index_age(session, connection_id)
                if age is None:
                    _warn(
                        "Database index is missing — agents will fall back to live schema lookups.",
                        category="db_index",
                        action_kind="reindex_db",
                        action_label="Index database",
                    )
                else:
                    snapshot.db_index_age_hours = round(age.total_seconds() / 3600, 1)
                    if age > timedelta(hours=self.DB_INDEX_TTL_HOURS):
                        snapshot.db_index_stale = True
                        _warn(
                            "Database index is "
                            f"{snapshot.db_index_age_hours:.0f}h old "
                            f"(>{self.DB_INDEX_TTL_HOURS}h); consider re-indexing.",
                            category="db_index",
                            action_kind="reindex_db",
                            action_label="Re-index database",
                        )
            except Exception:
                logger.debug("freshness: db index check failed", exc_info=True)

            try:
                from app.services.code_db_sync_service import CodeDbSyncService

                sync_svc = CodeDbSyncService()
                snapshot.sync_status = await sync_svc.get_sync_status(session, connection_id)
                if snapshot.sync_status in ("stale", "failed"):
                    snapshot.sync_stale = True
                    _warn(
                        "Code-database sync is "
                        f"{snapshot.sync_status}; column conventions may be out of date.",
                        category="sync",
                        action_kind="resync",
                        action_label="Re-sync code & database",
                        severity="critical" if snapshot.sync_status == "failed" else "warning",
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
                    _warn(
                        "Code graph is empty — lineage and clustering features "
                        "will fall back to legacy heuristics.",
                        category="code_graph",
                        action_kind="reindex_repo",
                        action_label="Re-index repository",
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
                        _warn(
                            "Knowledge base has not been indexed yet.",
                            category="git",
                            action_kind="reindex_repo",
                            action_label="Index repository",
                        )
                    else:
                        # get_head_sha is blocking git I/O — never call it
                        # directly on the event loop.
                        head_sha = await asyncio.to_thread(tracker.get_head_sha, repo_clone_dir)
                        if head_sha and head_sha != last_sha:
                            behind = await tracker.count_commits_ahead(repo_clone_dir, last_sha)
                            # count_commits_ahead returns -1 on error; only a
                            # positive count is a real "behind" signal.
                            if behind and behind > 0:
                                snapshot.git_behind_commits = behind
                                _warn(
                                    f"Knowledge base is {behind} commit(s) behind HEAD;"
                                    " answers may reference outdated code.",
                                    category="git",
                                    action_kind="reindex_repo",
                                    action_label="Re-index repository",
                                )
                            else:
                                _warn(
                                    "Knowledge base may be out of date.",
                                    category="git",
                                    action_kind="reindex_repo",
                                    action_label="Re-index repository",
                                )
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
