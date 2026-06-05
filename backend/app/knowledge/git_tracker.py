import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from git import Repo
from git.exc import BadName, BadObject
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commit_index import CommitIndex

logger = logging.getLogger(__name__)


@dataclass
class ChangedFilesResult:
    """Separates changed/added files from deleted files."""

    changed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    # R3-4: set when we fell back to a full re-list because the incremental
    # diff failed (transient error after retries). ``None`` for a clean diff
    # or an intentional missing-base full index.
    diff_error: str | None = None


class GitTracker:
    """Tracks indexed commits and computes changed files for incremental re-indexing."""

    # R3-4: retry transient git/IO diff errors before degrading to a full
    # re-list. Missing-base-commit errors are not retried (see get_changed_files).
    _DIFF_RETRIES = 3
    _DIFF_RETRY_DELAY_S = 0.5

    async def get_last_indexed_sha(
        self,
        session: AsyncSession,
        project_id: str,
        branch: str | None = None,
    ) -> str | None:
        stmt = select(CommitIndex).where(CommitIndex.project_id == project_id)
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
        self,
        repo_dir: Path,
        from_sha: str | None,
        to_sha: str,
    ) -> ChangedFilesResult:
        repo = Repo(str(repo_dir))

        if from_sha is None:
            all_files: list[str] = [
                str(item.path)  # type: ignore[union-attr]
                for item in repo.commit(to_sha).tree.traverse()
                if hasattr(item, "type") and item.type == "blob"  # type: ignore[union-attr]
            ]
            return ChangedFilesResult(changed=all_files)

        # R3-4: distinguish a genuinely missing base commit (the old SHA was
        # GC'd or force-pushed away — a full re-index is the *correct* answer)
        # from a transient git/IO error (which we retry before degrading to a
        # full re-list, so we don't silently pay for a full re-index on a
        # flaky read).
        diff = None
        last_exc: Exception | None = None
        for attempt in range(self._DIFF_RETRIES):
            try:
                # ``M=True`` (or ``--find-renames``) enables rename detection so
                # renamed files surface as change_type "R" with a_path=old /
                # b_path=new — C1 (v1.13.0) depends on this so the orphan-cleanup
                # step drops the old path. (``R=True`` is REVERSE diff in
                # GitPython, not rename detection — easy to confuse.)
                diff = repo.commit(from_sha).diff(repo.commit(to_sha), M=True)
                break
            except (BadName, BadObject, ValueError) as exc:
                # Unresolvable revision — retrying won't help; full re-index is
                # the intended fallback for a missing base commit. Leave
                # ``last_exc`` unset so diff_error stays None (this is expected,
                # not a transient failure).
                logger.info(
                    "Base commit %s unresolvable (%s); doing a full re-index",
                    from_sha,
                    exc,
                )
                break
            except Exception as exc:  # noqa: BLE001 — transient git/IO error
                last_exc = exc
                if attempt < self._DIFF_RETRIES - 1:
                    logger.warning(
                        "Transient diff error %s..%s (attempt %d/%d): %s; retrying",
                        from_sha,
                        to_sha,
                        attempt + 1,
                        self._DIFF_RETRIES,
                        exc,
                    )
                    time.sleep(self._DIFF_RETRY_DELAY_S * (attempt + 1))
                else:
                    logger.warning(
                        "Diff %s..%s still failing after %d attempts (%s); "
                        "falling back to full index",
                        from_sha,
                        to_sha,
                        self._DIFF_RETRIES,
                        exc,
                    )

        if diff is None:
            all_files = [
                str(item.path)  # type: ignore[union-attr]
                for item in repo.commit(to_sha).tree.traverse()
                if hasattr(item, "type") and item.type == "blob"  # type: ignore[union-attr]
            ]
            return ChangedFilesResult(
                changed=all_files,
                diff_error=str(last_exc) if last_exc else None,
            )

        changed: set[str] = set()
        deleted: set[str] = set()
        for d in diff:
            change_type = getattr(d, "change_type", None)

            if change_type == "R":
                # C1 (v1.13.0) — rename: old path is gone, new path is changed
                if d.a_path:
                    deleted.add(d.a_path)
                if d.b_path:
                    changed.add(d.b_path)
            elif d.deleted_file or change_type == "D":
                if d.a_path:
                    deleted.add(d.a_path)
            else:
                # Add, modify, copy: only the post-image path matters; for
                # plain modifications a_path == b_path so the result is the
                # same. (a_path was previously added too, which produced
                # ghost entries for renames before C1 was understood.)
                if d.b_path:
                    changed.add(d.b_path)
                elif d.a_path:
                    changed.add(d.a_path)

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
        stmt = select(CommitIndex).where(CommitIndex.project_id == project_id)
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
        """Count how many commits HEAD is ahead of *from_sha*.

        R3-5: GitPython is synchronous and walking commits is blocking IO, so
        run it off the event loop to avoid stalling the async pipeline.
        """

        def _count() -> int:
            try:
                repo = Repo(str(repo_dir))
                commits = list(repo.iter_commits(f"{from_sha}..HEAD"))
                return len(commits)
            except Exception:
                return -1

        return await asyncio.to_thread(_count)

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
        deleted = result.rowcount  # type: ignore[attr-defined]
        if deleted:
            await session.commit()
            logger.info(
                "Cleaned up %d old commit_index records for project %s",
                deleted,
                project_id,
            )
        return deleted
