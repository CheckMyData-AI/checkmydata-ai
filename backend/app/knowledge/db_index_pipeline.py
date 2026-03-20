"""Database indexing pipeline — 6-step orchestrator.

Introspects a live database connection, fetches sample data from each table,
validates against project knowledge via LLM, and persists a rich index.
"""

from __future__ import annotations

import asyncio
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
    "created_at",
    "createdat",
    "create_date",
    "creation_date",
    "updated_at",
    "updatedat",
    "update_date",
    "modified_at",
    "modifiedat",
    "modify_date",
    "timestamp",
    "date_created",
    "inserted_at",
    "insertedat",
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


CANDIDATE_ENUM_PATTERNS = {
    "status",
    "state",
    "type",
    "kind",
    "category",
    "role",
    "level",
    "priority",
    "severity",
    "gender",
    "country",
    "currency",
    "lang",
    "language",
    "plan",
    "tier",
    "phase",
    "mode",
    "source",
    "channel",
    "platform",
    "provider",
    "method",
    "payment_method",
    "billing_type",
}

MAX_DISTINCT_VALUES = 30
MAX_DISTINCT_CARDINALITY = 50


def _is_enum_candidate(col_name: str, data_type: str, row_count: int | None) -> bool:
    """Heuristic: column likely holds a small set of categorical values."""
    name_lower = col_name.lower()
    type_lower = data_type.lower()

    if any(p in name_lower for p in CANDIDATE_ENUM_PATTERNS):
        return True
    if name_lower.endswith(("_flag", "_bool", "_yn")):
        return True
    if "bool" in type_lower:
        return True
    if "enum" in type_lower:
        return True

    return False


def _build_distinct_query(
    table: TableInfo,
    col_name: str,
    db_type: str,
) -> str:
    tbl_q = table.name
    col_q = col_name
    if db_type == "mysql":
        tbl_q = f"`{table.name}`"
        col_q = f"`{col_name}`"
    elif db_type in ("postgres", "postgresql"):
        tbl_q = f'"{table.name}"'
        col_q = f'"{col_name}"'
        if table.schema and table.schema != "public":
            tbl_q = f'"{table.schema}"."{table.name}"'

    return (
        f"SELECT DISTINCT {col_q} FROM {tbl_q} "
        f"WHERE {col_q} IS NOT NULL "
        f"ORDER BY {col_q} "
        f"LIMIT {MAX_DISTINCT_CARDINALITY}"
    )


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
            {
                "connection_id": connection_id,
                "project_id": project_id,
                "db_type": connection_config.db_type,
            },
        )

        connector: BaseConnector | None = None
        try:
            # Step 1: Connect and introspect schema
            async with self._tracker.step(
                wf_id,
                "introspect_schema",
                f"Introspecting {connection_config.db_type} schema",
            ):
                connector = get_connector(
                    connection_config.db_type,
                    ssh_exec_mode=connection_config.ssh_exec_mode,
                )
                await connector.connect(connection_config)
                await self._tracker.emit(
                    wf_id,
                    "introspect_schema",
                    "started",
                    f"Connected to {connection_config.db_type}",
                )
                schema = await connector.introspect_schema()
                await self._tracker.emit(
                    wf_id,
                    "introspect_schema",
                    "started",
                    f"Found {len(schema.tables)} tables",
                )

            if not schema.tables:
                await self._tracker.end(wf_id, "db_index", "completed", "No tables found")
                return {"status": "completed", "tables": 0}

            # Step 2: Fetch sample data and distinct values per table (parallel)
            samples: dict[str, tuple[QueryResult, str | None]] = {}
            distinct_values: dict[str, dict[str, list[str]]] = {}
            total_tables = len(schema.tables)
            _sample_sem = asyncio.Semaphore(5)

            _sampled_count = [0]

            async def _fetch_table_samples(
                table: TableInfo,
            ) -> tuple[str, QueryResult, str | None, dict[str, list[str]]]:
                async with _sample_sem:
                    try:
                        query, ordering_col = _sample_query(table, connection_config.db_type)
                        result = await connector.execute_query(query)
                    except Exception:
                        logger.debug("Sample fetch failed for %s", table.name, exc_info=True)
                        result = QueryResult(columns=[], rows=[], row_count=0)
                        ordering_col = None

                    tbl_distinct: dict[str, list[str]] = {}
                    for col in table.columns:
                        if not _is_enum_candidate(col.name, col.data_type, table.row_count):
                            continue
                        try:
                            dq = _build_distinct_query(table, col.name, connection_config.db_type)
                            dr = await connector.execute_query(dq)
                            if dr.rows and (dr.row_count or 0) <= MAX_DISTINCT_CARDINALITY:
                                vals = [str(r[0]) for r in dr.rows if r[0] is not None]
                                if vals:
                                    tbl_distinct[col.name] = vals[:MAX_DISTINCT_VALUES]
                        except Exception:
                            logger.debug(
                                "Distinct query failed for %s.%s",
                                table.name,
                                col.name,
                                exc_info=True,
                            )

                    _sampled_count[0] += 1
                    row_info = f"{result.row_count or len(result.rows)} rows"
                    enum_info = f"{len(tbl_distinct)} enum cols" if tbl_distinct else ""
                    detail_parts = [row_info] + ([enum_info] if enum_info else [])
                    await self._tracker.emit(
                        wf_id,
                        "fetch_samples",
                        "started",
                        f"Sampled {_sampled_count[0]}/{total_tables}: "
                        f"{table.name} ({', '.join(detail_parts)})",
                    )

                    return table.name, result, ordering_col, tbl_distinct

            async with self._tracker.step(
                wf_id,
                "fetch_samples",
                f"Fetching sample data from {total_tables} tables",
            ):
                results = await asyncio.gather(*[_fetch_table_samples(t) for t in schema.tables])
                for tname, result, ordering_col, tbl_distinct in results:
                    samples[tname] = (result, ordering_col)
                    if tbl_distinct:
                        distinct_values[tname] = tbl_distinct

            # Step 3: Load project knowledge and rules
            code_context = ""
            rules_context = ""
            code_tables: set[str] = set()

            async with self._tracker.step(
                wf_id,
                "load_context",
                "Loading project knowledge and rules",
            ):
                code_context, code_tables = await self._load_code_context(project_id)
                await self._tracker.emit(
                    wf_id,
                    "load_context",
                    "started",
                    f"Loaded {len(code_tables)} code entities",
                )
                rules_context = await self._load_rules_context(project_id)
                await self._tracker.emit(
                    wf_id,
                    "load_context",
                    "started",
                    f"Loaded rules context ({len(rules_context)} chars)"
                    if rules_context
                    else "No custom rules found",
                )

            # Step 4: LLM validation per table
            analyses: list[TableAnalysis] = []

            async with self._tracker.step(
                wf_id,
                "validate_tables",
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

                await self._tracker.emit(
                    wf_id,
                    "validate_tables",
                    "started",
                    f"Classified: {len(large_tables)} large tables (individual), "
                    f"{len(small_tables)} small tables (batched)",
                )

                _llm_sem = asyncio.Semaphore(3)
                _large_done = [0]

                async def _analyze_large_table(table: TableInfo) -> TableAnalysis:
                    async with _llm_sem:
                        sample_result, _ = samples.get(table.name, (QueryResult(), None))
                        table_code_ctx = self._filter_code_context(code_context, table.name)
                        result = await self._validator.analyze_table(
                            table=table,
                            sample_data=sample_result,
                            code_context=table_code_ctx,
                            rules_context=rules_context,
                            preferred_provider=preferred_provider,
                            model=model,
                        )
                        _large_done[0] += 1
                        await self._tracker.emit(
                            wf_id,
                            "validate_tables",
                            "started",
                            f"Analyzed [{_large_done[0]}/{len(large_tables)}]: "
                            f"{table.name} (relevance={result.relevance_score})",
                        )
                        return result

                large_results = await asyncio.gather(
                    *[_analyze_large_table(t) for t in large_tables]
                )
                analyses.extend(large_results)

                total_small_batches = (
                    (len(small_tables) + self._batch_size - 1) // self._batch_size
                    if small_tables
                    else 0
                )
                for batch_start in range(0, len(small_tables), self._batch_size):
                    batch = small_tables[batch_start : batch_start + self._batch_size]
                    batch_items: list[tuple[TableInfo, QueryResult | None]] = []
                    for table in batch:
                        sample_result, _ = samples.get(table.name, (QueryResult(), None))
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
                    batch_num = batch_start // self._batch_size + 1
                    batch_names = ", ".join(t.name for t in batch)
                    await self._tracker.emit(
                        wf_id,
                        "validate_tables",
                        "started",
                        f"Batch {batch_num}/{total_small_batches} done "
                        f"({len(batch)} small tables): {batch_names}",
                    )

            # Step 5: Store results
            async with self._tracker.step(
                wf_id,
                "store_results",
                "Persisting index to database",
            ):
                async with async_session_factory() as session:
                    current_table_names = {t.name for t in schema.tables}
                    deleted = await self._svc.delete_stale_tables(
                        session, connection_id, current_table_names
                    )
                    if deleted:
                        logger.info("Removed %d stale table index entries", deleted)
                        await self._tracker.emit(
                            wf_id,
                            "store_results",
                            "started",
                            f"Removed {deleted} stale table index entries",
                        )

                    for analysis in analyses:
                        sample_result, ordering_col = samples.get(
                            analysis.table_name, (QueryResult(), None)
                        )
                        table_info = next(
                            (t for t in schema.tables if t.name == analysis.table_name),
                            None,
                        )
                        tbl_distinct = distinct_values.get(analysis.table_name, {})

                        table_data = {
                            "table_name": analysis.table_name,
                            "table_schema": table_info.schema if table_info else "public",
                            "column_count": len(table_info.columns) if table_info else 0,
                            "row_count": table_info.row_count if table_info else None,
                            "sample_data_json": _sample_to_json(sample_result),
                            "column_distinct_values_json": json.dumps(tbl_distinct, default=str),
                            "ordering_column": ordering_col,
                            "latest_record_at": _detect_latest_record(sample_result, ordering_col),
                            "is_active": analysis.is_active,
                            "relevance_score": analysis.relevance_score,
                            "business_description": analysis.business_description,
                            "data_patterns": analysis.data_patterns,
                            "column_notes_json": analysis.column_notes_json,
                            "numeric_format_notes": analysis.numeric_format_notes,
                            "query_hints": analysis.query_hints,
                            "code_match_status": analysis.code_match_status,
                            "code_match_details": analysis.code_match_details,
                        }
                        await self._svc.upsert_table(session, connection_id, table_data)

                    await self._tracker.emit(
                        wf_id,
                        "store_results",
                        "started",
                        f"Stored {len(analyses)} table entries",
                    )
                    await session.commit()

            # Step 6: Generate connection summary
            async with self._tracker.step(
                wf_id,
                "generate_summary",
                "Generating database summary",
            ):
                await self._tracker.emit(
                    wf_id,
                    "generate_summary",
                    "started",
                    f"Generating LLM summary for {len(analyses)} tables",
                )
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

                await self._tracker.emit(
                    wf_id,
                    "generate_summary",
                    "started",
                    f"Summary: {active_count} active, {empty_count} empty, "
                    f"{orphan_count} orphan, {phantom_count} phantom tables",
                )

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
                wf_id,
                "db_index",
                "completed",
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
            file_rules = self._rules_engine.load_rules(project_rules_dir=f"./rules/{project_id}")
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
