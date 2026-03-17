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

from app.connectors.base import (
    BaseConnector,
    ConnectionConfig,
    QueryResult,
    SchemaInfo,
    connector_key,
)
from app.connectors.registry import get_connector
from app.core.context_enricher import ContextEnricher
from app.core.error_classifier import ErrorClassifier
from app.core.query_cache import QueryCache
from app.core.query_repair import QueryRepairer
from app.core.query_validation import ValidationConfig
from app.core.retry_strategy import RetryStrategy
from app.core.types import RAGSource
from app.core.validation_loop import ValidationLoop
from app.core.workflow_tracker import WorkflowTracker
from app.knowledge.custom_rules import CustomRulesEngine
from app.knowledge.entity_extractor import ProjectKnowledge
from app.knowledge.schema_indexer import SchemaIndexer
from app.knowledge.vector_store import VectorStore
from app.llm.base import ToolCall
from app.llm.router import LLMRouter
from app.services.project_cache_service import ProjectCacheService

logger = logging.getLogger(__name__)

SCHEMA_CACHE_TTL_SECONDS = 300


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
        *,
        user_question: str = "",
        chat_history: list | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
        sql_provider: str | None = None,
        sql_model: str | None = None,
    ) -> None:
        self._project_id = project_id
        self._connection_config = connection_config
        self._llm = llm_router
        self._vector_store = vector_store
        self._schema_indexer = schema_indexer
        self._rules_engine = rules_engine
        self._tracker = tracker
        self._user_question = user_question
        self._chat_history = chat_history
        self._preferred_provider = preferred_provider
        self._model = model
        self._sql_provider = sql_provider or preferred_provider
        self._sql_model = sql_model or model

        self._connectors: dict[str, BaseConnector] = {}
        self._connector_lock = asyncio.Lock()
        self._schema_cache: dict[str, tuple[SchemaInfo, float]] = {}
        self._query_cache = QueryCache()
        self._knowledge_cache: ProjectKnowledge | None = None
        self._cache_svc = ProjectCacheService()

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
            "get_entity_info": self._get_entity_info,
            "get_db_index": self._get_db_index,
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

        db_idx_ctx = await self._load_db_index_hints()
        enricher = ContextEnricher(schema, self._vector_store, db_index_context=db_idx_ctx)
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
            question=self._user_question or query,
            project_id=self._project_id,
            workflow_id=wf_id,
            connection_config=self._connection_config,
            chat_history=self._chat_history,
            preferred_provider=self._sql_provider,
            model=self._sql_model,
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

        async with self._tracker.step(
            wf_id, "search_knowledge", f"Searching knowledge base: {query[:60]}"
        ):
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

    async def _get_entity_info(self, args: dict, wf_id: str) -> str:
        scope: str = args.get("scope", "list")
        entity_name: str | None = args.get("entity_name")

        async with self._tracker.step(
            wf_id, "get_entity_info", f"Looking up entity info ({scope})"
        ):
            knowledge = await self._load_knowledge()

        if knowledge is None:
            return "No entity information available. The repository may not be indexed yet."

        if scope == "list":
            return self._format_entity_list(knowledge)
        if scope == "detail":
            if not entity_name:
                return "Error: entity_name is required when scope is 'detail'."
            return self._format_entity_detail(knowledge, entity_name)
        if scope == "table_map":
            return self._format_table_map(knowledge)
        if scope == "enums":
            return self._format_enums(knowledge)
        return f"Error: unknown scope '{scope}'. Use 'list', 'detail', 'table_map', or 'enums'."

    async def _get_db_index(self, args: dict, wf_id: str) -> str:
        scope: str = args.get("scope", "overview")
        table_name: str | None = args.get("table_name")

        if not self._connection_config:
            return "Error: no database connection configured for this project."

        from app.models.base import async_session_factory
        from app.services.db_index_service import DbIndexService

        db_index_svc = DbIndexService()

        async with self._tracker.step(
            wf_id, "get_db_index", f"Loading database index ({scope})"
        ):
            connection_id = self._connection_config.connection_id
            if not connection_id:
                return "Database index not available. Run 'Index DB' first."

            async with async_session_factory() as session:
                if scope == "table_detail":
                    if not table_name:
                        return "Error: table_name is required when scope is 'table_detail'."
                    entry = await db_index_svc.get_table_index(
                        session, connection_id, table_name
                    )
                    if not entry:
                        return (
                            f"No index entry for table '{table_name}'. "
                            "The table may not have been indexed yet."
                        )
                    return db_index_svc.table_index_to_detail(entry)

                entries = await db_index_svc.get_index(session, connection_id)
                summary = await db_index_svc.get_summary(session, connection_id)

                if not entries:
                    return "Database index not available. Run 'Index DB' first."

                return db_index_svc.index_to_prompt_context(entries, summary)

    async def _load_db_index_hints(self) -> str:
        """Load compact DB index hints for query repair context."""
        if not self._connection_config or not self._connection_config.connection_id:
            return ""
        try:
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                entries = await svc.get_index(session, self._connection_config.connection_id)
                summary = await svc.get_summary(session, self._connection_config.connection_id)
            if not entries:
                return ""
            return svc.index_to_prompt_context(entries, summary)
        except Exception:
            logger.debug("Failed to load DB index hints for repair context", exc_info=True)
            return ""

    async def _load_knowledge(self) -> ProjectKnowledge | None:
        if self._knowledge_cache is not None:
            return self._knowledge_cache
        from app.models.base import async_session_factory

        async with async_session_factory() as session:
            self._knowledge_cache = await self._cache_svc.load_knowledge(
                session, self._project_id
            )
        return self._knowledge_cache

    # ------------------------------------------------------------------
    # Helpers – connector / schema cache (mirrors Orchestrator)
    # ------------------------------------------------------------------

    @staticmethod
    def _connector_key(cfg: ConnectionConfig) -> str:
        return connector_key(cfg)

    async def _get_or_create_connector(self, cfg: ConnectionConfig) -> BaseConnector:
        key = self._connector_key(cfg)
        async with self._connector_lock:
            if key not in self._connectors:
                connector = get_connector(cfg.db_type, ssh_exec_mode=cfg.ssh_exec_mode)
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
            lines.append(
                f"| {col.name} | {col.data_type} | {pk} | {nullable} | {default} | {comment} |"
            )

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

    # ------------------------------------------------------------------
    # Entity info formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_entity_list(knowledge: ProjectKnowledge) -> str:
        if not knowledge.entities:
            return "No entities found in the indexed codebase."
        lines = [
            f"Found {len(knowledge.entities)} entities:\n",
            "| Entity | Table | File | Columns | Relationships |",
            "|--------|-------|------|---------|---------------|",
        ]
        for name, entity in sorted(knowledge.entities.items()):
            tbl = entity.table_name or "-"
            fp = entity.file_path or "-"
            cols = len(entity.columns)
            rels = len(entity.relationships)
            lines.append(f"| {name} | {tbl} | {fp} | {cols} | {rels} |")
        return "\n".join(lines)

    @staticmethod
    def _format_entity_detail(knowledge: ProjectKnowledge, entity_name: str) -> str:
        entity = knowledge.entities.get(entity_name)
        if not entity:
            low = entity_name.lower()
            for k, v in knowledge.entities.items():
                if k.lower() == low or (v.table_name and v.table_name.lower() == low):
                    entity = v
                    break
        if not entity:
            available = ", ".join(sorted(knowledge.entities.keys())[:30])
            return f"Entity '{entity_name}' not found. Available: {available}"

        lines = [f"## {entity.name}"]
        if entity.table_name:
            lines.append(f"Table: `{entity.table_name}`")
        if entity.file_path:
            lines.append(f"File: `{entity.file_path}`")
        lines.append("")

        if entity.columns:
            lines.append("| Column | Type | FK | FK Target | Enum Values |")
            lines.append("|--------|------|----|-----------|-------------|")
            for col in entity.columns:
                fk = "YES" if col.is_fk else ""
                fk_tgt = col.fk_target or ""
                enums = ", ".join(col.enum_values[:8]) if col.enum_values else ""
                lines.append(f"| {col.name} | {col.col_type} | {fk} | {fk_tgt} | {enums} |")
        else:
            lines.append("No column information extracted.")

        if entity.relationships:
            lines.append(f"\nRelationships: {', '.join(entity.relationships)}")
        if entity.used_in_files:
            lines.append(
                f"\nUsed in {len(entity.used_in_files)} file(s): "
                + ", ".join(f"`{f}`" for f in entity.used_in_files[:10])
            )
        return "\n".join(lines)

    @staticmethod
    def _format_table_map(knowledge: ProjectKnowledge) -> str:
        if not knowledge.table_usage:
            return "No table usage data available."
        lines = [
            f"Table usage map ({len(knowledge.table_usage)} tables):\n",
            "| Table | Readers | Writers | ORM Refs | Status |",
            "|-------|---------|---------|----------|--------|",
        ]
        for tbl_name, usage in sorted(knowledge.table_usage.items()):
            status = "active" if usage.is_active else "UNUSED"
            lines.append(
                f"| {tbl_name} | {len(usage.readers)} | {len(usage.writers)} "
                f"| {len(usage.orm_refs)} | {status} |"
            )
        dead = knowledge.dead_tables
        if dead:
            lines.append(f"\nPotentially unused tables: {', '.join(dead)}")
        return "\n".join(lines)

    @staticmethod
    def _format_enums(knowledge: ProjectKnowledge) -> str:
        if not knowledge.enums:
            return "No enum or constant definitions found."
        lines = [f"Found {len(knowledge.enums)} enum/constant definitions:\n"]
        for enum_def in knowledge.enums:
            vals = ", ".join(enum_def.values[:12])
            if len(enum_def.values) > 12:
                vals += f" ... (+{len(enum_def.values) - 12} more)"
            lines.append(f"- **{enum_def.name}** (`{enum_def.file_path}`): {vals}")
        if knowledge.service_functions:
            lines.append(f"\nAlso found {len(knowledge.service_functions)} service functions:")
            for sf in knowledge.service_functions[:30]:
                tables = ", ".join(sf["tables"])
                lines.append(f"- `{sf['name']}` in `{sf['file_path']}` -> tables: {tables}")
        return "\n".join(lines)
