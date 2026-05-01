"""Service for managing indexing checkpoint state (resumable pipelines).

T22: per-step and per-doc progress is now stored in dedicated append-only
tables (``indexing_checkpoint_step`` + ``indexing_checkpoint_doc``). The
old JSON rewrite pattern — read text column, json.loads, append, json.dumps,
commit — was O(n) per call and degraded into O(n²) across a full indexing
run. The new pattern uses one SELECT + one bulk INSERT per batch and keeps
the writes bounded regardless of history size.

The legacy ``completed_steps`` and ``processed_doc_paths`` Text columns on
``IndexingCheckpoint`` are retained for backwards compatibility with
in-flight rows on already-running production instances but are no longer
written by new code. ``get_completed_steps`` /
``get_processed_doc_paths`` transparently fall back to them when the
append-only rows are absent.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indexing_checkpoint import (
    IndexingCheckpoint,
    IndexingCheckpointDoc,
    IndexingCheckpointStep,
)

logger = logging.getLogger(__name__)

_SENTINEL: object = object()


def _safe_json_loads_list(raw: str) -> list:
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _safe_json_loads_set(raw: str) -> set[str]:
    return set(_safe_json_loads_list(raw))


class CheckpointService:
    async def get_active(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> IndexingCheckpoint | None:
        result = await session.execute(
            select(IndexingCheckpoint).where(
                IndexingCheckpoint.project_id == project_id,
            ),
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        session: AsyncSession,
        project_id: str,
        workflow_id: str,
        head_sha: str,
        last_sha: str | None = None,
    ) -> IndexingCheckpoint:
        old = await self.get_active(session, project_id)
        if old:
            await session.delete(old)
            await session.flush()

        cp = IndexingCheckpoint(
            project_id=project_id,
            workflow_id=workflow_id,
            head_sha=head_sha,
            last_sha=last_sha,
            status="running",
        )
        session.add(cp)
        await session.commit()
        await session.refresh(cp)
        return cp

    async def complete_step(
        self,
        session: AsyncSession,
        checkpoint_id: str,
        step_name: str,
        *,
        head_sha: str | None = None,
        last_sha: object = _SENTINEL,
        changed_files: list[str] | None = None,
        deleted_files: list[str] | None = None,
        profile_json: str | None = None,
        knowledge_json: str | None = None,
        total_docs: int | None = None,
    ) -> None:
        cp = await session.get(IndexingCheckpoint, checkpoint_id)
        if not cp:
            return

        await self._insert_step(session, checkpoint_id, step_name)

        if head_sha is not None:
            cp.head_sha = head_sha
        if last_sha is not _SENTINEL:
            cp.last_sha = last_sha  # type: ignore[assignment]
        if changed_files is not None:
            cp.changed_files_json = json.dumps(changed_files)
        if deleted_files is not None:
            cp.deleted_files_json = json.dumps(deleted_files)
        if profile_json is not None:
            cp.profile_json = profile_json
        if knowledge_json is not None:
            cp.knowledge_json = knowledge_json
        if total_docs is not None:
            cp.total_docs = total_docs

        await session.commit()

    @staticmethod
    async def _insert_step(
        session: AsyncSession,
        checkpoint_id: str,
        step_name: str,
    ) -> None:
        """Insert a step row, swallowing the unique-constraint violation.

        Implemented as a savepoint (nested transaction) so the outer commit
        is still usable if we bounce off the unique constraint.
        """
        savepoint = await session.begin_nested()
        try:
            session.add(
                IndexingCheckpointStep(
                    checkpoint_id=checkpoint_id, step_name=step_name
                )
            )
            await session.flush()
        except IntegrityError:
            await savepoint.rollback()
            return
        await savepoint.commit()

    async def mark_doc_processed(
        self,
        session: AsyncSession,
        checkpoint_id: str,
        source_path: str,
    ) -> None:
        if not await self._checkpoint_exists(session, checkpoint_id):
            return
        savepoint = await session.begin_nested()
        try:
            session.add(
                IndexingCheckpointDoc(
                    checkpoint_id=checkpoint_id, source_path=source_path
                )
            )
            await session.flush()
        except IntegrityError:
            await savepoint.rollback()
        else:
            await savepoint.commit()
        await session.commit()

    async def mark_docs_batch_processed(
        self,
        session: AsyncSession,
        checkpoint_id: str,
        source_paths: list[str],
    ) -> None:
        if not source_paths:
            return
        if not await self._checkpoint_exists(session, checkpoint_id):
            return

        deduped = list(dict.fromkeys(source_paths))
        existing_stmt = select(IndexingCheckpointDoc.source_path).where(
            IndexingCheckpointDoc.checkpoint_id == checkpoint_id,
            IndexingCheckpointDoc.source_path.in_(deduped),
        )
        existing = await session.execute(existing_stmt)
        existing_set = set(existing.scalars().all())

        new_rows = [
            IndexingCheckpointDoc(checkpoint_id=checkpoint_id, source_path=p)
            for p in deduped
            if p not in existing_set
        ]
        if not new_rows:
            return
        session.add_all(new_rows)
        await session.commit()

    @staticmethod
    async def _checkpoint_exists(
        session: AsyncSession, checkpoint_id: str
    ) -> bool:
        cp = await session.get(IndexingCheckpoint, checkpoint_id)
        return cp is not None

    async def mark_failed(
        self,
        session: AsyncSession,
        checkpoint_id: str,
        step: str,
        error: str,
    ) -> None:
        cp = await session.get(IndexingCheckpoint, checkpoint_id)
        if not cp:
            return
        cp.status = "failed"
        cp.failed_step = step
        cp.error_detail = error[:4000]
        await session.commit()

    async def delete(
        self,
        session: AsyncSession,
        checkpoint_id: str,
    ) -> None:
        cp = await session.get(IndexingCheckpoint, checkpoint_id)
        if cp:
            await session.delete(cp)
            await session.commit()

    async def cleanup_stale(
        self,
        session: AsyncSession,
        max_age_hours: int = 24,
    ) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        result = await session.execute(
            delete(IndexingCheckpoint).where(
                IndexingCheckpoint.updated_at < cutoff,
            ),
        )
        count = result.rowcount  # type: ignore[attr-defined]
        if count:
            await session.commit()
            logger.info("Cleaned up %d stale indexing checkpoints", count)
        return count

    # ------------------------------------------------------------------
    # Readers — used by pipelines to resume from where they left off.
    # ------------------------------------------------------------------

    @staticmethod
    def get_changed_files(cp: IndexingCheckpoint) -> list[str]:
        return _safe_json_loads_list(cp.changed_files_json)

    @staticmethod
    def get_deleted_files(cp: IndexingCheckpoint) -> list[str]:
        return _safe_json_loads_list(cp.deleted_files_json)

    @staticmethod
    def get_completed_steps_legacy(cp: IndexingCheckpoint) -> set[str]:
        """Legacy JSON reader — kept only as a fallback for old rows."""
        return _safe_json_loads_set(cp.completed_steps)

    @staticmethod
    def get_processed_doc_paths_legacy(cp: IndexingCheckpoint) -> set[str]:
        """Legacy JSON reader — kept only as a fallback for old rows."""
        return _safe_json_loads_set(cp.processed_doc_paths)

    async def get_completed_steps(
        self,
        session: AsyncSession,
        checkpoint_id: str,
    ) -> set[str]:
        """Return the set of completed step names for a checkpoint (T22)."""
        result = await session.execute(
            select(IndexingCheckpointStep.step_name).where(
                IndexingCheckpointStep.checkpoint_id == checkpoint_id,
            )
        )
        steps = set(result.scalars().all())
        if steps:
            return steps
        cp = await session.get(IndexingCheckpoint, checkpoint_id)
        if cp is None:
            return set()
        return self.get_completed_steps_legacy(cp)

    async def get_processed_doc_paths(
        self,
        session: AsyncSession,
        checkpoint_id: str,
    ) -> set[str]:
        """Return the set of processed doc paths for a checkpoint (T22)."""
        result = await session.execute(
            select(IndexingCheckpointDoc.source_path).where(
                IndexingCheckpointDoc.checkpoint_id == checkpoint_id,
            )
        )
        paths = set(result.scalars().all())
        if paths:
            return paths
        cp = await session.get(IndexingCheckpoint, checkpoint_id)
        if cp is None:
            return set()
        return self.get_processed_doc_paths_legacy(cp)
