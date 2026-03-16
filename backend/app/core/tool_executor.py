"""Execute agent tool calls by routing to the appropriate handler.

Each handler wraps existing infrastructure (``ValidationLoop``,
``VectorStore``, ``SchemaIndexer``, ``CustomRulesEngine``) so that the
conversational agent re-uses the battle-tested query pipeline without
duplicating logic.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.connectors.base import BaseConnector, ConnectionConfig, QueryResult, SchemaInfo
from app.connectors.registry import get_connector
from app.core.context_enricher import ContextEnricher
from app.core.error_classifier import ErrorClassifier
from app.core.query_cache import QueryCache
from app.core.query_repair import QueryRepairer
from app.core.query_validation import ValidationConfig
from app.core.retry_strategy import RetryStrategy
from app.core.validation_loop import ValidationLoop
from app.core.workflow_tracker import WorkflowTracker
from app.knowledge.custom_rules import CustomRulesEngine
from app.knowledge.schema_indexer import SchemaIndexer
from app.knowledge.vector_store import VectorStore
from app.llm.base import ToolCall
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

SCHEMA_CACHE_TTL_SECONDS = 300


@dataclass
class RAGSource:
    source_path: str
    distance: float | None = None
    doc_type: str = ""
    chunk_index: str = ""


@dataclass
class ToolExecutorContext:
    """Accumulated artefacts from tool executions within a single agent run."""

    last_query: str | None = None
    last_query_explanation: str | None = None
    last_query_result: QueryResult | None = None
    rag_sources: list[RAGSource] = field(default_factory=list)
    total_token_usage: dict[str, int] = field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )


class ToolExecutor:
    """Routes ``ToolCall`` objects to their concrete handlers."""

    def __init__(
        self,
        project_id: str,
        connection_config: ConnectionConfig | None,
        llm_router: LLMRouter,
        vector_store: VectorStore,
        schema_indexer: SchemaIndexer,
        rules_engine: CustomRulesEngine,
        tracker: WorkflowTracker,
    ) -> None:
        self._project_id = project_id
        self._connection_config = connection_config
        self._llm = llm_router
        self._vector_store = vector_store
        self._schema_indexer = schema_indexer
        self._rules_engine = rules_engine
        self._tracker = tracker

        self._connectors: dict[str, BaseConnector] = {}
        self._schema_cache: dict[str, tuple[SchemaInfo, float]] = {}
        self._query_cache = QueryCache()

        self.ctx = ToolExecutorContext()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, tool_call: ToolCall, workflow_id: str) -> str:
        """Dispatch *tool_call* and return the result as a string for the LLM."""
        handler = {
            "execute_query": self._execute_query,
            "search_knowledge": self._search_knowledge,
            "get_schema_info": self._get_schema_info,
            "get_custom_rules": self._get_custom_rules,
        }.get(tool_call.name)

        if handler is None:
            return f"Error: unknown tool '{tool_call.name}'"

        try:
            return await handler(tool_call.arguments, workflow_id)
        except Exception as exc:
            logger.exception("Tool %s execution failed", tool_call.name)
            return f"Error executing {tool_call.name}: {exc}"

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _execute_query(self, args: dict, wf_id: str) -> str:
        query: str = args.get("query", "")
        explanation: str = args.get("explanation", "")

        if not self._connection_config:
            return "Error: no database connection configured for this project."

        connector = await self._get_or_create_connector(self._connection_config)
        schema = await self._get_cached_schema(self._connection_config)
        val_config = self._build_validation_config()

        enricher = ContextEnricher(schema, self._vector_store)
        repairer = QueryRepairer(self._llm)

        validation_loop = ValidationLoop(
            config=val_config,
            error_classifier=ErrorClassifier(),
            context_enricher=enricher,
            query_repairer=repairer,
            retry_strategy=RetryStrategy(),
            tracker=self._tracker,
        )

        loop_result = await validation_loop.execute(
            initial_query=query,
            initial_explanation=explanation,
            connector=connector,
            schema=schema,
            question=query,
            project_id=self._project_id,
            workflow_id=wf_id,
            connection_config=self._connection_config,
        )

        if not loop_result.success:
            err = loop_result.final_error
            msg = err.message if err else "Query validation failed"
            return f"Query failed after {loop_result.total_attempts} attempt(s): {msg}"

        results = loop_result.results
        assert results is not None

        self.ctx.last_query = loop_result.query
        self.ctx.last_query_explanation = loop_result.explanation
        self.ctx.last_query_result = results

        conn_key = self._connector_key(self._connection_config)
        self._query_cache.put(conn_key, loop_result.query, results)

        return self._format_query_results(results)

    async def _search_knowledge(self, args: dict, wf_id: str) -> str:
        query: str = args.get("query", "")
        max_results: int = int(args.get("max_results", 5))

        async with self._tracker.step(wf_id, "search_knowledge", f"Searching knowledge base: {query[:60]}"):
            results = await asyncio.to_thread(
                self._vector_store.query,
                project_id=self._project_id,
                query_text=query,
                n_results=max_results,
            )

        if not results:
            return "No relevant documents found in the knowledge base."

        parts: list[str] = []
        for r in results:
            meta = r.get("metadata", {})
            source = meta.get("source_path", "unknown")
            doc = r.get("document", "")
            distance = r.get("distance")
            sim = f" (similarity: {1 - distance:.2f})" if distance is not None else ""
            parts.append(f"### {source}{sim}\n{doc}")
            self.ctx.rag_sources.append(
                RAGSource(
                    source_path=source,
                    distance=distance,
                    doc_type=meta.get("doc_type", ""),
                    chunk_index=meta.get("chunk_index", ""),
                )
            )

        return f"Found {len(results)} relevant document(s):\n\n" + "\n\n".join(parts)

    async def _get_schema_info(self, args: dict, wf_id: str) -> str:
        scope: str = args.get("scope", "overview")
        table_name: str | None = args.get("table_name")

        if not self._connection_config:
            return "Error: no database connection configured for this project."

        async with self._tracker.step(wf_id, "get_schema_info", f"Fetching schema ({scope})"):
            schema = await self._get_cached_schema(self._connection_config)

        if scope == "overview":
            return self._format_schema_overview(schema)

        if scope == "table_detail":
            if not table_name:
                return "Error: table_name is required when scope is 'table_detail'."
            return self._format_table_detail(schema, table_name)

        return f"Error: unknown scope '{scope}'. Use 'overview' or 'table_detail'."

    async def _get_custom_rules(self, _args: dict, wf_id: str) -> str:
        async with self._tracker.step(wf_id, "load_rules", "Loading custom rules"):
            file_rules = self._rules_engine.load_rules(
                project_rules_dir=f"./rules/{self._project_id}",
            )
            db_rules = await self._rules_engine.load_db_rules(
                project_id=self._project_id,
            )

        context = self._rules_engine.rules_to_context(file_rules + db_rules)
        return context or "No custom rules defined for this project."

    # ------------------------------------------------------------------
    # Helpers – connector / schema cache (mirrors Orchestrator)
    # ------------------------------------------------------------------

    def _connector_key(self, cfg: ConnectionConfig) -> str:
        parts = [cfg.db_type, cfg.db_host, str(cfg.db_port), cfg.db_name]
        if cfg.ssh_host:
            parts.extend([cfg.ssh_host, str(cfg.ssh_port), cfg.ssh_user or ""])
        return ":".join(parts)

    async def _get_or_create_connector(self, cfg: ConnectionConfig) -> BaseConnector:
        key = self._connector_key(cfg)
        if key not in self._connectors:
            connector = get_connector(cfg.db_type)
            await connector.connect(cfg)
            self._connectors[key] = connector
        return self._connectors[key]

    async def _get_cached_schema(self, cfg: ConnectionConfig) -> SchemaInfo:
        key = self._connector_key(cfg)
        cached = self._schema_cache.get(key)
        if cached:
            schema, ts = cached
            if time.monotonic() - ts < SCHEMA_CACHE_TTL_SECONDS:
                return schema
        connector = await self._get_or_create_connector(cfg)
        schema = await connector.introspect_schema()
        self._schema_cache[key] = (schema, time.monotonic())
        return schema

    @staticmethod
    def _build_validation_config() -> ValidationConfig:
        from app.config import settings as app_settings

        return ValidationConfig(
            max_retries=app_settings.query_max_retries,
            enable_explain=app_settings.query_enable_explain,
            enable_schema_validation=app_settings.query_enable_schema_validation,
            empty_result_retry=app_settings.query_empty_result_retry,
            explain_row_warning_threshold=app_settings.query_explain_row_warning_threshold,
            query_timeout_seconds=app_settings.query_timeout_seconds,
        )

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_query_results(results: QueryResult, max_rows: int = 20) -> str:
        if not results.rows:
            return "Query executed successfully but returned no rows."

        lines = [
            f"Columns: {', '.join(results.columns)}",
            f"Total rows: {results.row_count}",
            f"Execution time: {results.execution_time_ms:.1f}ms",
            "",
        ]
        for row in results.rows[:max_rows]:
            lines.append(" | ".join(str(v) for v in row))
        if results.row_count > max_rows:
            lines.append(f"... and {results.row_count - max_rows} more rows")
        return "\n".join(lines)

    @staticmethod
    def _format_schema_overview(schema: SchemaInfo) -> str:
        if not schema.tables:
            return "No tables found in the database."

        lines = [
            f"Database: {schema.db_name} ({schema.db_type})",
            f"Tables: {len(schema.tables)}",
            "",
            "| Table | Columns | Rows (est.) |",
            "|-------|---------|-------------|",
        ]
        for t in schema.tables:
            row_hint = f"~{t.row_count:,}" if t.row_count is not None else "?"
            lines.append(f"| {t.name} | {len(t.columns)} | {row_hint} |")
        return "\n".join(lines)

    @staticmethod
    def _format_table_detail(schema: SchemaInfo, table_name: str) -> str:
        table = next((t for t in schema.tables if t.name.lower() == table_name.lower()), None)
        if not table:
            available = ", ".join(t.name for t in schema.tables[:20])
            return f"Table '{table_name}' not found. Available tables: {available}"

        lines = [f"## {table.name}"]
        if table.comment:
            lines.append(table.comment)
        if table.row_count is not None:
            lines.append(f"Rows: ~{table.row_count:,}")
        lines.append("")
        lines.append("| Column | Type | PK | Nullable | Default | Comment |")
        lines.append("|--------|------|----|----------|---------|---------|")
        for col in table.columns:
            pk = "PK" if col.is_primary_key else ""
            nullable = "YES" if col.is_nullable else "NO"
            default = str(col.default) if col.default else ""
            comment = col.comment or ""
            lines.append(f"| {col.name} | {col.data_type} | {pk} | {nullable} | {default} | {comment} |")

        if table.foreign_keys:
            lines.append("")
            lines.append("Foreign Keys:")
            for fk in table.foreign_keys:
                lines.append(f"  {fk.column} -> {fk.references_table}.{fk.references_column}")

        if table.indexes:
            lines.append("")
            lines.append("Indexes:")
            for idx in table.indexes:
                u = "UNIQUE " if idx.is_unique else ""
                lines.append(f"  {u}{idx.name}({', '.join(idx.columns)})")

        return "\n".join(lines)
