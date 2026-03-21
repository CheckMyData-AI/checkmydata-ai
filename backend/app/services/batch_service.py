import json
import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.registry import get_connector
from app.core.workflow_tracker import tracker
from app.models.base import async_session_factory
from app.models.batch_query import BatchQuery
from app.models.saved_note import SavedNote
from app.services.connection_service import ConnectionService
from app.viz.utils import serialize_value

logger = logging.getLogger(__name__)

_conn_svc = ConnectionService()

_RAW_RESULT_ROW_CAP = 500


class BatchService:
    async def create_batch(
        self,
        db: AsyncSession,
        user_id: str,
        project_id: str,
        connection_id: str,
        title: str,
        queries: list[dict],
        note_ids: list[str] | None = None,
    ) -> BatchQuery:
        if note_ids:
            for nid in note_ids:
                result = await db.execute(select(SavedNote).where(SavedNote.id == nid))
                note = result.scalar_one_or_none()
                if note:
                    queries.append({"sql": note.sql_query, "title": note.title})

        batch = BatchQuery(
            user_id=user_id,
            project_id=project_id,
            connection_id=connection_id,
            title=title,
            queries_json=json.dumps(queries),
            note_ids_json=json.dumps(note_ids) if note_ids else None,
            status="pending",
        )
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
        return batch

    async def get_batch(self, db: AsyncSession, batch_id: str) -> BatchQuery | None:
        result = await db.execute(select(BatchQuery).where(BatchQuery.id == batch_id))
        return result.scalar_one_or_none()

    async def list_batches(
        self,
        db: AsyncSession,
        project_id: str,
        user_id: str,
        limit: int = 20,
    ) -> list[BatchQuery]:
        stmt = (
            select(BatchQuery)
            .where(BatchQuery.project_id == project_id, BatchQuery.user_id == user_id)
            .order_by(BatchQuery.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def delete_batch(self, db: AsyncSession, batch_id: str) -> bool:
        batch = await self.get_batch(db, batch_id)
        if not batch:
            return False
        await db.delete(batch)
        await db.commit()
        return True

    async def execute_batch(
        self,
        batch_id: str,
        connection_id: str,
        user_id: str | None = None,
    ) -> None:
        """Run all queries in a batch sequentially, storing results and emitting SSE events."""
        async with async_session_factory() as db:
            batch = await self.get_batch(db, batch_id)
            if not batch:
                logger.error("Batch %s not found", batch_id)
                return

            conn_model = await _conn_svc.get(db, connection_id)
            if not conn_model:
                batch.status = "failed"
                batch.results_json = json.dumps([{"error": "Connection not found"}])
                batch.completed_at = datetime.now(UTC)
                await db.commit()
                return

            config = await _conn_svc.to_config(db, conn_model, user_id=user_id)
            queries = json.loads(batch.queries_json)
            total = len(queries)

            batch.status = "running"
            await db.commit()

            wf_id = await tracker.begin("batch_execute", context={"batch_id": batch_id})
            results: list[dict] = []
            succeeded = 0
            failed = 0

            for idx, query_item in enumerate(queries):
                sql = query_item.get("sql", "")
                q_title = query_item.get("title", f"Query {idx + 1}")

                await tracker.emit(
                    wf_id,
                    "batch_progress",
                    "running",
                    detail=f"Executing {idx + 1}/{total}: {q_title}",
                    batch_id=batch_id,
                    query_index=idx,
                    total=total,
                )

                connector = get_connector(conn_model.db_type, ssh_exec_mode=config.ssh_exec_mode)
                start = time.monotonic()
                try:
                    await connector.connect(config)
                    try:
                        result = await connector.execute_query(sql)
                    finally:
                        await connector.disconnect()

                    duration_ms = int((time.monotonic() - start) * 1000)
                    cols = list(getattr(result, "columns", []))
                    rows = getattr(result, "rows", []) or []
                    serialized = [
                        [serialize_value(v) for v in row] for row in rows[:_RAW_RESULT_ROW_CAP]
                    ]

                    results.append(
                        {
                            "title": q_title,
                            "sql": sql,
                            "status": "success",
                            "columns": cols,
                            "rows": serialized,
                            "total_rows": getattr(result, "row_count", len(rows)),
                            "duration_ms": duration_ms,
                        }
                    )
                    succeeded += 1

                except Exception as e:
                    duration_ms = int((time.monotonic() - start) * 1000)
                    logger.warning(
                        "Batch %s query %d failed: %s",
                        batch_id[:8],
                        idx,
                        e,
                    )
                    results.append(
                        {
                            "title": q_title,
                            "sql": sql,
                            "status": "failed",
                            "error": str(e),
                            "duration_ms": duration_ms,
                        }
                    )
                    failed += 1

                await tracker.emit(
                    wf_id,
                    "batch_progress",
                    "completed" if results[-1]["status"] == "success" else "failed",
                    detail=f"Query {idx + 1}/{total}: {results[-1]['status']}",
                    batch_id=batch_id,
                    query_index=idx,
                    total=total,
                )

            if failed == total:
                batch.status = "failed"
            elif failed > 0:
                batch.status = "partially_failed"
            else:
                batch.status = "completed"

            batch.results_json = json.dumps(results, default=str)
            batch.completed_at = datetime.now(UTC)
            await db.commit()

            await tracker.end(
                wf_id,
                "batch_execute",
                status=batch.status,
                detail=f"{succeeded}/{total} succeeded",
            )
