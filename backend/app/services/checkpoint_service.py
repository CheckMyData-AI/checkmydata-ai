"""Service for managing indexing checkpoint state (resumable pipelines)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indexing_checkpoint import IndexingCheckpoint

logger = logging.getLogger(__name__)

_SENTINEL = object()


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
        last_sha: str | None = _SENTINEL,
        changed_files: list[str] | None = None,
        deleted_files: list[str] | None = None,
        profile_json: str | None = None,
        knowledge_json: str | None = None,
        total_docs: int | None = None,
    ) -> None:
        cp = await session.get(IndexingCheckpoint, checkpoint_id)
        if not cp:
            return

        steps: list[str] = _safe_json_loads_list(cp.completed_steps)
        if step_name not in steps:
            steps.append(step_name)
        cp.completed_steps = json.dumps(steps)

        if head_sha is not None:
            cp.head_sha = head_sha
        if last_sha is not _SENTINEL:
            cp.last_sha = last_sha
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

    async def mark_doc_processed(
        self,
        session: AsyncSession,
        checkpoint_id: str,
        source_path: str,
    ) -> None:
        cp = await session.get(IndexingCheckpoint, checkpoint_id)
        if not cp:
            return
        paths: list[str] = _safe_json_loads_list(cp.processed_doc_paths)
        if source_path not in paths:
            paths.append(source_path)
        cp.processed_doc_paths = json.dumps(paths)
        await session.commit()

    async def mark_docs_batch_processed(
        self,
        session: AsyncSession,
        checkpoint_id: str,
        source_paths: list[str],
    ) -> None:
        if not source_paths:
            return
        cp = await session.get(IndexingCheckpoint, checkpoint_id)
        if not cp:
            return
        existing: list[str] = _safe_json_loads_list(cp.processed_doc_paths)
        existing_set = set(existing)
        for path in source_paths:
            if path not in existing_set:
                existing.append(path)
                existing_set.add(path)
        cp.processed_doc_paths = json.dumps(existing)
        await session.commit()

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
        count = result.rowcount  # type: ignore[union-attr]
        if count:
            await session.commit()
            logger.info("Cleaned up %d stale indexing checkpoints", count)
        return count

    @staticmethod
    def get_completed_steps(cp: IndexingCheckpoint) -> set[str]:
        return _safe_json_loads_set(cp.completed_steps)

    @staticmethod
    def get_processed_doc_paths(cp: IndexingCheckpoint) -> set[str]:
        return _safe_json_loads_set(cp.processed_doc_paths)

    @staticmethod
    def get_changed_files(cp: IndexingCheckpoint) -> list[str]:
        return _safe_json_loads_list(cp.changed_files_json)

    @staticmethod
    def get_deleted_files(cp: IndexingCheckpoint) -> list[str]:
        return _safe_json_loads_list(cp.deleted_files_json)
