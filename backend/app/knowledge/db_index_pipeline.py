"""Database indexing pipeline — 6-step orchestrator.

Introspects a live database connection, fetches sample data from each table,
validates against project knowledge via LLM, and persists a rich index.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from app.connectors.base import BaseConnector, ConnectionConfig, QueryResult, TableInfo
from app.connectors.registry import get_connector
from app.core.workflow_tracker import WorkflowTracker
from app.core.workflow_tracker import tracker as default_tracker
from app.knowledge.custom_rules import CustomRulesEngine
from app.knowledge.db_index_validator import DbIndexValidator, TableAnalysis
from app.llm.router import LLMRouter
from app.models.base import async_session_factory
from app.services.db_index_service import DbIndexService

logger = logging.getLogger(__name__)

PREFERRED_ORDER_COLS = [
    "created_at", "createdat", "create_date", "creation_date",
    "updated_at", "updatedat", "update_date", "modified_at",
    "modifiedat", "modify_date", "timestamp", "date_created",
    "inserted_at", "insertedat",
]


def _find_ordering_column(table: TableInfo) -> str | None:
    col_map = {c.name.lower(): c.name for c in table.columns}

    for preferred in PREFERRED_ORDER_COLS:
        if preferred in col_map:
            return col_map[preferred]

    for col in table.columns:
        if col.is_primary_key:
            return col.name

    return None


def _sample_query(table: TableInfo, db_type: str, limit: int = 3) -> tuple[str, str | None]:
    """Return (query, ordering_column) for fetching recent rows."""
    ordering_col = _find_ordering_column(table)

    tbl_name = table.name
    if table.schema and table.schema not in ("public", ""):
        tbl_name = f"{table.schema}.{table.name}"

    if db_type == "mysql":
        tbl_name_q = f"`{table.name}`"
    elif db_type in ("postgres", "postgresql"):
        tbl_name_q = f'"{table.name}"'
        if table.schema and table.schema != "public":
            tbl_name_q = f'"{table.schema}"."{table.name}"'
    else:
        tbl_name_q = tbl_name

    if ordering_col:
        if db_type == "mysql":
            col_q = f"`{ordering_col}`"
        elif db_type in ("postgres", "postgresql"):
            col_q = f'"{ordering_col}"'
        else:
            col_q = ordering_col
        return f"SELECT * FROM {tbl_name_q} ORDER BY {col_q} DESC LIMIT {limit}", ordering_col

    return f"SELECT * FROM {tbl_name_q} LIMIT {limit}", None


def _sample_to_json(result: QueryResult) -> str:
    if not result.rows:
        return "[]"
    rows = []
    for row in result.rows:
        row_dict = {}
        for i, col in enumerate(result.columns):
            val = row[i] if i < len(row) else None
            try:
                json.dumps(val)
                row_dict[col] = val
            except (TypeError, ValueError):
                row_dict[col] = str(val)
        rows.append(row_dict)
    return json.dumps(rows, default=str)


def _detect_latest_record(result: QueryResult, ordering_col: str | None) -> str | None:
    """Try to extract the timestamp of the newest row."""
    if not result.rows or not ordering_col:
        return None
    try:
        idx = result.columns.index(ordering_col)
        val = result.rows[0][idx]
        if val is not None:
            if isinstance(val, datetime):
                return val.isoformat()
            return str(val)
    except (ValueError, IndexError):
        pass
    return None


class DbIndexPipeline:
    """Orchestrates the 6-step database indexing process."""

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        workflow_tracker: WorkflowTracker | None = None,
        db_index_batch_size: int = 5,
    ) -> None:
        self._llm = llm_router or LLMRouter()
        self._tracker = workflow_tracker or default_tracker
        self._batch_size = db_index_batch_size
        self._validator = DbIndexValidator(self._llm)
        self._svc = DbIndexService()
        self._rules_engine = CustomRulesEngine()

    async def run(
        self,
        connection_id: str,
        connection_config: ConnectionConfig,
        project_id: str,
        *,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> dict:
        """Run the full database indexing pipeline. Returns status dict."""
        wf_id = await self._tracker.begin(
            "db_index",
            {"connection_id": connection_id[:8], "db_type": connection_config.db_type},
        )

        connector: BaseConnector | None = None
        try:
            # Step 1: Connect and introspect schema
            async with self._tracker.step(
                wf_id, "introspect_schema",
                f"Introspecting {connection_config.db_type} schema",
            ):
                connector = get_connector(
                    connection_config.db_type,
                    ssh_exec_mode=connection_config.ssh_exec_mode,
                )
                await connector.connect(connection_config)
                schema = await connector.introspect_schema()

            if not schema.tables:
                await self._tracker.end(wf_id, "db_index", "completed", "No tables found")
                return {"status": "completed", "tables": 0}

            # Step 2: Fetch sample data per table
            samples: dict[str, tuple[QueryResult, str | None]] = {}
            total_tables = len(schema.tables)

            async with self._tracker.step(
                wf_id, "fetch_samples",
                f"Fetching sample data from {total_tables} tables",
            ):
                for table in schema.tables:
                    try:
                        query, ordering_col = _sample_query(
                            table, connection_config.db_type
                        )
                        result = await connector.execute_query(query)
                        samples[table.name] = (result, ordering_col)
                    except Exception:
                        logger.debug(
                            "Sample fetch failed for %s", table.name, exc_info=True
                        )
                        samples[table.name] = (
                            QueryResult(columns=[], rows=[], row_count=0),
                            None,
                        )

            # Step 3: Load project knowledge and rules
            code_context = ""
            rules_context = ""
            code_tables: set[str] = set()

            async with self._tracker.step(
                wf_id, "load_context", "Loading project knowledge and rules",
            ):
                code_context, code_tables = await self._load_code_context(project_id)
                rules_context = await self._load_rules_context(project_id)

            # Step 4: LLM validation per table
            analyses: list[TableAnalysis] = []

            async with self._tracker.step(
                wf_id, "validate_tables",
                f"Analyzing {total_tables} tables via LLM",
            ):
                large_tables = []
                small_tables = []

                for table in schema.tables:
                    row_count = table.row_count or 0
                    sample_result = samples.get(table.name, (QueryResult(), None))[0]
                    has_data = bool(sample_result.rows)

                    if row_count > 100 or has_data:
                        large_tables.append(table)
                    else:
                        small_tables.append(table)

                for table in large_tables:
                    sample_result, _ = samples.get(
                        table.name, (QueryResult(), None)
                    )
                    table_code_ctx = self._filter_code_context(
                        code_context, table.name
                    )
                    analysis = await self._validator.analyze_table(
                        table=table,
                        sample_data=sample_result,
                        code_context=table_code_ctx,
                        rules_context=rules_context,
                        preferred_provider=preferred_provider,
                        model=model,
                    )
                    analyses.append(analysis)

                for batch_start in range(0, len(small_tables), self._batch_size):
                    batch = small_tables[batch_start:batch_start + self._batch_size]
                    batch_items: list[tuple[TableInfo, QueryResult | None]] = []
                    for table in batch:
                        sample_result, _ = samples.get(
                            table.name, (QueryResult(), None)
                        )
                        batch_items.append((table, sample_result))

                    batch_code_ctx = ""
                    for table in batch:
                        ctx = self._filter_code_context(code_context, table.name)
                        if ctx:
                            batch_code_ctx += f"\n{ctx}"

                    batch_results = await self._validator.analyze_table_batch(
                        tables=batch_items,
                        code_context=batch_code_ctx,
                        rules_context=rules_context,
                        preferred_provider=preferred_provider,
                        model=model,
                    )
                    analyses.extend(batch_results)

            # Step 5: Store results
            async with self._tracker.step(
                wf_id, "store_results", "Persisting index to database",
            ):
                async with async_session_factory() as session:
                    current_table_names = {t.name for t in schema.tables}
                    deleted = await self._svc.delete_stale_tables(
                        session, connection_id, current_table_names
                    )
                    if deleted:
                        logger.info("Removed %d stale table index entries", deleted)

                    for analysis in analyses:
                        sample_result, ordering_col = samples.get(
                            analysis.table_name, (QueryResult(), None)
                        )
                        table_info = next(
                            (t for t in schema.tables if t.name == analysis.table_name),
                            None,
                        )

                        table_data = {
                            "table_name": analysis.table_name,
                            "table_schema": table_info.schema if table_info else "public",
                            "column_count": len(table_info.columns) if table_info else 0,
                            "row_count": table_info.row_count if table_info else None,
                            "sample_data_json": _sample_to_json(sample_result),
                            "ordering_column": ordering_col,
                            "latest_record_at": _detect_latest_record(
                                sample_result, ordering_col
                            ),
                            "is_active": analysis.is_active,
                            "relevance_score": analysis.relevance_score,
                            "business_description": analysis.business_description,
                            "data_patterns": analysis.data_patterns,
                            "column_notes_json": analysis.column_notes_json,
                            "query_hints": analysis.query_hints,
                            "code_match_status": analysis.code_match_status,
                            "code_match_details": analysis.code_match_details,
                        }
                        await self._svc.upsert_table(session, connection_id, table_data)

                    await session.commit()

            # Step 6: Generate connection summary
            async with self._tracker.step(
                wf_id, "generate_summary", "Generating database summary",
            ):
                summary_result = await self._validator.generate_summary(
                    analyses=analyses,
                    schema=schema,
                    code_tables=code_tables,
                    preferred_provider=preferred_provider,
                    model=model,
                )

                live_tables = {t.name.lower() for t in schema.tables}
                code_lower = {t.lower() for t in code_tables}
                orphan_count = len(live_tables - code_lower)
                phantom_count = len(code_lower - live_tables)
                active_count = sum(1 for a in analyses if a.is_active)
                empty_count = sum(1 for a in analyses if not a.is_active)

                async with async_session_factory() as session:
                    await self._svc.upsert_summary(
                        session,
                        connection_id,
                        {
                            "total_tables": total_tables,
                            "active_tables": active_count,
                            "empty_tables": empty_count,
                            "orphan_tables": orphan_count,
                            "phantom_tables": phantom_count,
                            "summary_text": summary_result.summary_text,
                            "recommendations": summary_result.recommendations,
                        },
                    )
                    await session.commit()

            try:
                from app.services.code_db_sync_service import CodeDbSyncService

                sync_svc = CodeDbSyncService()
                async with async_session_factory() as session:
                    await sync_svc.mark_stale(session, connection_id)
                    await session.commit()
            except Exception:
                logger.debug("Failed to mark sync as stale after DB index", exc_info=True)

            await self._tracker.end(
                wf_id, "db_index", "completed",
                f"{total_tables} tables indexed ({active_count} active)",
            )

            return {
                "status": "completed",
                "tables": total_tables,
                "active": active_count,
                "empty": empty_count,
                "workflow_id": wf_id,
            }

        except Exception as exc:
            logger.exception("Database indexing pipeline failed")
            await self._tracker.end(wf_id, "db_index", "failed", str(exc))
            return {"status": "failed", "error": str(exc), "workflow_id": wf_id}

        finally:
            if connector:
                try:
                    await connector.disconnect()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    async def _load_code_context(self, project_id: str) -> tuple[str, set[str]]:
        """Load code-level knowledge about tables from ProjectCache."""
        code_tables: set[str] = set()
        context_parts: list[str] = []

        try:
            from app.services.project_cache_service import ProjectCacheService

            cache_svc = ProjectCacheService()
            async with async_session_factory() as session:
                knowledge = await cache_svc.load_knowledge(session, project_id)

            if knowledge:
                for entity_name, entity in knowledge.entities.items():
                    if entity.table_name:
                        code_tables.add(entity.table_name)
                        parts = [f"Entity '{entity_name}' maps to table '{entity.table_name}'"]
                        if entity.file_path:
                            parts.append(f"  Defined in: {entity.file_path}")
                        if entity.columns:
                            col_names = [c.name for c in entity.columns]
                            parts.append(f"  Code columns: {', '.join(col_names)}")
                        if entity.relationships:
                            parts.append(f"  Relationships: {', '.join(entity.relationships)}")
                        context_parts.append("\n".join(parts))

                for tbl_name, usage in knowledge.table_usage.items():
                    code_tables.add(tbl_name)
                    if usage.readers or usage.writers:
                        context_parts.append(
                            f"Table '{tbl_name}': "
                            f"{len(usage.readers)} reader(s), "
                            f"{len(usage.writers)} writer(s)"
                        )

        except Exception:
            logger.debug("Failed to load code context", exc_info=True)

        return "\n\n".join(context_parts), code_tables

    async def _load_rules_context(self, project_id: str) -> str:
        try:
            file_rules = self._rules_engine.load_rules(
                project_rules_dir=f"./rules/{project_id}"
            )
            db_rules = await self._rules_engine.load_db_rules(project_id=project_id)
            return self._rules_engine.rules_to_context(file_rules + db_rules)
        except Exception:
            logger.debug("Failed to load rules context", exc_info=True)
            return ""

    @staticmethod
    def _filter_code_context(full_context: str, table_name: str) -> str:
        """Extract lines from code context that mention the given table."""
        if not full_context:
            return ""
        relevant = []
        for line in full_context.split("\n\n"):
            if table_name.lower() in line.lower():
                relevant.append(line)
        return "\n\n".join(relevant)
