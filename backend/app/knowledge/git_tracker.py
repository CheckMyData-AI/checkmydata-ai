import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from git import Repo
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commit_index import CommitIndex

logger = logging.getLogger(__name__)


@dataclass
class ChangedFilesResult:
    """Separates changed/added files from deleted files."""
    changed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


class GitTracker:
    """Tracks indexed commits and computes changed files for incremental re-indexing."""

    async def get_last_indexed_sha(
        self,
        session: AsyncSession,
        project_id: str,
        branch: str | None = None,
    ) -> str | None:
        stmt = (
            select(CommitIndex)
            .where(CommitIndex.project_id == project_id)
        )
        if branch:
            stmt = stmt.where(CommitIndex.branch == branch)
        stmt = stmt.order_by(CommitIndex.created_at.desc()).limit(1)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return row.commit_sha if row else None

    def get_head_sha(self, repo_dir: Path) -> str:
        repo = Repo(str(repo_dir))
        return repo.head.commit.hexsha

    def get_changed_files(
        self, repo_dir: Path, from_sha: str | None, to_sha: str,
    ) -> ChangedFilesResult:
        repo = Repo(str(repo_dir))

        if from_sha is None:
            all_files = [
                item.path
                for item in repo.commit(to_sha).tree.traverse()
                if item.type == "blob"
            ]
            return ChangedFilesResult(changed=all_files)

        try:
            diff = repo.commit(from_sha).diff(repo.commit(to_sha))
        except Exception:
            logger.warning(
                "Could not diff %s..%s, falling back to full index",
                from_sha, to_sha,
            )
            all_files = [
                item.path
                for item in repo.commit(to_sha).tree.traverse()
                if item.type == "blob"
            ]
            return ChangedFilesResult(changed=all_files)

        changed: set[str] = set()
        deleted: set[str] = set()
        for d in diff:
            if d.deleted_file:
                if d.a_path:
                    deleted.add(d.a_path)
            else:
                if d.a_path:
                    changed.add(d.a_path)
                if d.b_path:
                    changed.add(d.b_path)

        return ChangedFilesResult(
            changed=list(changed),
            deleted=list(deleted),
        )

    async def record_index(
        self,
        session: AsyncSession,
        project_id: str,
        commit_sha: str,
        commit_message: str,
        indexed_files: list[str],
        branch: str = "main",
    ) -> None:
        entry = CommitIndex(
            project_id=project_id,
            commit_sha=commit_sha,
            branch=branch,
            commit_message=commit_message,
            indexed_files=json.dumps(indexed_files),
            status="completed",
        )
        session.add(entry)
        await session.commit()

    async def get_last_indexed_record(
        self,
        session: AsyncSession,
        project_id: str,
        branch: str | None = None,
    ) -> CommitIndex | None:
        """Return the full CommitIndex row for the last indexed commit."""
        stmt = (
            select(CommitIndex)
            .where(CommitIndex.project_id == project_id)
        )
        if branch:
            stmt = stmt.where(CommitIndex.branch == branch)
        stmt = stmt.order_by(CommitIndex.created_at.desc()).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_commits_ahead(
        self,
        repo_dir: Path,
        from_sha: str,
    ) -> int:
        """Count how many commits HEAD is ahead of *from_sha*."""
        try:
            repo = Repo(str(repo_dir))
            commits = list(repo.iter_commits(f"{from_sha}..HEAD"))
            return len(commits)
        except Exception:
            return -1

    async def cleanup_old_records(
        self,
        session: AsyncSession,
        project_id: str,
        keep: int = 10,
    ) -> int:
        """Keep only the last *keep* commit_index records per project."""
        subq = (
            select(CommitIndex.id)
            .where(CommitIndex.project_id == project_id)
            .order_by(CommitIndex.created_at.desc())
            .limit(keep)
            .subquery()
        )
        result = await session.execute(
            delete(CommitIndex).where(
                CommitIndex.project_id == project_id,
                CommitIndex.id.not_in(select(subq.c.id)),
            )
        )
        deleted = result.rowcount  # type: ignore[union-attr]
        if deleted:
            await session.commit()
            logger.info(
                "Cleaned up %d old commit_index records for project %s",
                deleted, project_id,
            )
        return deleted
