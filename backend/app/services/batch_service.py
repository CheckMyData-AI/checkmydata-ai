import asyncio
import json
import logging
import time
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.registry import get_connector
from app.core.safety import SafetyGuard, SafetyLevel
from app.core.workflow_tracker import tracker
from app.models.base import async_session_factory
from app.models.batch_query import BatchQuery
from app.models.connection import Connection
from app.models.saved_note import SavedNote
from app.services.connection_service import ConnectionService
from app.viz.utils import serialize_value

logger = logging.getLogger(__name__)

_conn_svc = ConnectionService()

# ---------------------------------------------------------------------------
# Database-only guards (T12)
#
# Since the analytics spine, ``Connection.db_type`` / ``db_port`` / ``db_name``
# are nullable: a GA4 (or other vendor) source has no engine, port or database.
# Everything that reaches ``get_connector(db_type)`` or
# ``SafetyGuard.validate(sql, db_type)`` therefore has to prove the connection
# really is a database first — otherwise ``get_connector(None)`` falls through
# to the source key and dies with ``ValueError: Unsupported adapter: database``,
# which tells the user nothing.
#
# These live here (rather than in a new module) so that the four database-only
# routes and this service share one definition; the service layer already
# raises ``HTTPException`` elsewhere (see ``membership_service.require_role``).
# ---------------------------------------------------------------------------

DATABASE_SOURCE_TYPE = "database"

_SOURCE_TYPE_LABELS = {
    "ga4": "Google Analytics 4",
    "appstore": "App Store Connect",
    "googleplay": "Google Play",
    "mcp": "MCP",
}


def describe_source_type(source_type: str) -> str:
    """Human-readable vendor name for a ``Connection.source_type``."""
    return _SOURCE_TYPE_LABELS.get(source_type, source_type or "non-database")


def not_a_database_detail(conn: Connection, *, subject: str = "This endpoint") -> str:
    """Explain why *conn* cannot serve SQL. Only meaningful for a non-database source."""
    if conn.source_type != DATABASE_SOURCE_TYPE:
        return (
            f"{subject} requires a database connection; "
            f"'{conn.name}' is a {describe_source_type(conn.source_type)} source."
        )
    return (
        f"{subject} requires a database connection; "
        f"'{conn.name}' has no database engine configured."
    )


def require_database_connection(conn: Connection, *, subject: str = "This endpoint") -> str:
    """Return ``conn.db_type``, or raise HTTP 400 when *conn* is not a database source.

    Fails early and explicitly so an analytics connection never reaches a
    connector factory or the SQL SafetyGuard.
    """
    db_type = conn.db_type
    if conn.source_type != DATABASE_SOURCE_TYPE or db_type is None:
        raise HTTPException(status_code=400, detail=not_a_database_detail(conn, subject=subject))
    return db_type


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
            result = await db.execute(select(SavedNote).where(SavedNote.id.in_(note_ids)))
            notes_by_id = {n.id: n for n in result.scalars().all()}
            for nid in note_ids:
                note = notes_by_id.get(nid)
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

    async def _execute_single_query(
        self,
        idx: int,
        query_item: dict,
        connector,
        batch_id: str,
        total: int,
        wf_id: str,
        guard: SafetyGuard,
        db_type: str,
    ) -> dict:
        """Execute a single query against an already-connected *connector* (T19).

        The connector's lifetime is owned by the outer ``execute_batch``
        call, so we no longer open / close a connection per query. This
        eliminates the single biggest source of latency in large batches.

        Before running, the SQL is validated through the shared
        :class:`SafetyGuard` (F-SCHED-02): on a read-only connection any
        write/DDL is rejected and the item is marked ``failed`` with the
        safety reason instead of being executed.
        """
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

        start = time.monotonic()
        row_cap = settings.batch_result_row_cap

        safety_result = guard.validate(sql, db_type)
        if not safety_result.is_safe:
            logger.warning(
                "Batch %s query %d blocked by safety guard: %s",
                batch_id[:8],
                idx,
                safety_result.reason,
            )
            entry = {
                "title": q_title,
                "sql": sql,
                "status": "failed",
                "error": f"Query blocked: {safety_result.reason}",
                "duration_ms": int((time.monotonic() - start) * 1000),
            }
            await tracker.emit(
                wf_id,
                "batch_progress",
                "failed",
                detail=f"Query {idx + 1}/{total}: blocked",
                batch_id=batch_id,
                query_index=idx,
                total=total,
            )
            return entry

        try:
            result = await connector.execute_query(sql)

            duration_ms = int((time.monotonic() - start) * 1000)
            cols = list(getattr(result, "columns", []))
            rows = getattr(result, "rows", []) or []
            serialized = [[serialize_value(v) for v in row] for row in rows[:row_cap]]

            entry = {
                "title": q_title,
                "sql": sql,
                "status": "success",
                "columns": cols,
                "rows": serialized,
                "total_rows": getattr(result, "row_count", len(rows)),
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning("Batch %s query %d failed: %s", batch_id[:8], idx, e)
            entry = {
                "title": q_title,
                "sql": sql,
                "status": "failed",
                "error": str(e),
                "duration_ms": duration_ms,
            }

        await tracker.emit(
            wf_id,
            "batch_progress",
            "completed" if entry["status"] == "success" else "failed",
            detail=f"Query {idx + 1}/{total}: {entry['status']}",
            batch_id=batch_id,
            query_index=idx,
            total=total,
        )
        return entry

    async def execute_batch(
        self,
        batch_id: str,
        connection_id: str,
        user_id: str | None = None,
        parallel: bool = True,
    ) -> None:
        """Run all queries in a batch, storing results and emitting SSE events.

        When *parallel* is True (the default), queries run concurrently with a
        concurrency cap of ``_MAX_BATCH_CONCURRENCY``.
        """
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

            # T12: batch execution is SQL, so it is database-only. An analytics
            # source has no engine to run against — fail the batch through the
            # normal failure path with an honest error rather than crashing in
            # ``get_connector(None)`` and leaving the row stuck in "running".
            db_type = conn_model.db_type
            if conn_model.source_type != DATABASE_SOURCE_TYPE or db_type is None:
                detail = not_a_database_detail(conn_model, subject="Batch execution")
                logger.warning("Batch %s rejected: %s", batch_id[:8], detail)
                batch.status = "failed"
                batch.results_json = json.dumps([{"error": detail}])
                batch.completed_at = datetime.now(UTC)
                await db.commit()
                return

            config = await _conn_svc.to_config(db, conn_model, user_id=user_id)
            queries = json.loads(batch.queries_json)
            total = len(queries)

            # F-SCHED-02: route every stored query through the shared SafetyGuard
            # before execution, mirroring the agent path (core/validation_loop.py).
            safety_level = (
                SafetyLevel.READ_ONLY if conn_model.is_read_only else SafetyLevel.ALLOW_DML
            )
            guard = SafetyGuard(level=safety_level)

            batch.status = "running"
            await db.commit()

            wf_id = await tracker.begin(
                "batch_execute",
                context={
                    "batch_id": batch_id,
                    "project_id": batch.project_id,
                    "user_id": user_id or "",
                },
            )

            # T19: one shared connector for the whole batch. We rely on the
            # connector + its driver to multiplex queries safely; the
            # semaphore caps true concurrency so we don't DOS the
            # database with parallel queries.
            connector = get_connector(db_type, ssh_exec_mode=config.ssh_exec_mode)
            await connector.connect(config)
            try:
                if parallel and total > 1:
                    sem = asyncio.Semaphore(settings.batch_max_concurrency)

                    async def _throttled(idx: int, qi: dict) -> dict:
                        async with sem:
                            return await self._execute_single_query(
                                idx,
                                qi,
                                connector,
                                batch_id,
                                total,
                                wf_id,
                                guard=guard,
                                db_type=db_type,
                            )

                    tasks = [_throttled(i, q) for i, q in enumerate(queries)]
                    ordered_results = await asyncio.gather(*tasks, return_exceptions=True)
                    results: list[dict] = []
                    for i, r in enumerate(ordered_results):
                        if isinstance(r, BaseException):
                            results.append(
                                {
                                    "title": queries[i].get("title", f"Query {i + 1}"),
                                    "sql": queries[i].get("sql", ""),
                                    "status": "failed",
                                    "error": str(r),
                                    "duration_ms": 0,
                                }
                            )
                        else:
                            results.append(r)
                else:
                    results = []
                    for idx, query_item in enumerate(queries):
                        entry = await self._execute_single_query(
                            idx,
                            query_item,
                            connector,
                            batch_id,
                            total,
                            wf_id,
                            guard=guard,
                            db_type=db_type,
                        )
                        results.append(entry)
            finally:
                try:
                    await connector.disconnect()
                except Exception:
                    logger.warning("Batch %s: connector disconnect failed", batch_id[:8])

            succeeded = sum(1 for r in results if r["status"] == "success")
            failed = total - succeeded

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
