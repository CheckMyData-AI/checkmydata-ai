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
from app.core.history_trimmer import trim_history
from app.core.query_builder import QueryBuilder
from app.core.query_cache import QueryCache
from app.core.query_repair import QueryRepairer
from app.core.query_validation import ValidationConfig
from app.core.retry_strategy import RetryStrategy
from app.core.types import RAGSource
from app.core.validation_loop import ValidationLoop
from app.core.workflow_tracker import WorkflowTracker
from app.core.workflow_tracker import tracker as default_tracker
from app.knowledge.custom_rules import CustomRulesEngine
from app.knowledge.schema_indexer import SchemaIndexer
from app.knowledge.vector_store import VectorStore
from app.llm.base import Message
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

SCHEMA_CACHE_TTL_SECONDS = 300


@dataclass
class OrchestratorResponse:
    answer: str = ""
    query: str = ""
    query_explanation: str = ""
    results: QueryResult | None = None
    viz_type: str = "text"
    viz_config: dict = field(default_factory=dict)
    error: str | None = None
    workflow_id: str | None = None
    attempts: list[dict] = field(default_factory=list)
    total_attempts: int = 0
    rag_sources: list[RAGSource] = field(default_factory=list)
    staleness_warning: str | None = None
    token_usage: dict = field(default_factory=dict)


class Orchestrator:
    """Main agent loop: context retrieval -> query building -> execution -> interpretation."""

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        vector_store: VectorStore | None = None,
        custom_rules: CustomRulesEngine | None = None,
        workflow_tracker: WorkflowTracker | None = None,
    ):
        self._llm_router = llm_router or LLMRouter()
        self._vector_store = vector_store or VectorStore()
        self._custom_rules = custom_rules or CustomRulesEngine()
        self._query_builder = QueryBuilder(self._llm_router)
        self._schema_indexer = SchemaIndexer()
        self._connectors: dict[str, BaseConnector] = {}
        self._connector_lock = asyncio.Lock()
        self._schema_cache: dict[str, tuple[SchemaInfo, float]] = {}
        self._query_result_cache = QueryCache()
        self._tracker = workflow_tracker or default_tracker

    @staticmethod
    def _connector_key(cfg: ConnectionConfig) -> str:
        return connector_key(cfg)

    async def get_or_create_connector(self, connection_config: ConnectionConfig) -> BaseConnector:
        key = self._connector_key(connection_config)
        async with self._connector_lock:
            if key not in self._connectors:
                connector = get_connector(
                    connection_config.db_type,
                    ssh_exec_mode=connection_config.ssh_exec_mode,
                )
                await connector.connect(connection_config)
                self._connectors[key] = connector
            return self._connectors[key]

    async def _get_cached_schema(self, connection_config: ConnectionConfig) -> SchemaInfo:
        key = self._connector_key(connection_config)
        cached = self._schema_cache.get(key)
        if cached:
            schema, ts = cached
            if time.monotonic() - ts < SCHEMA_CACHE_TTL_SECONDS:
                return schema

        connector = await self.get_or_create_connector(connection_config)
        schema = await connector.introspect_schema()
        self._schema_cache[key] = (schema, time.monotonic())
        return schema

    def _build_validation_config(self) -> ValidationConfig:
        from app.config import settings as app_settings

        return ValidationConfig(
            max_retries=app_settings.query_max_retries,
            enable_explain=app_settings.query_enable_explain,
            enable_schema_validation=app_settings.query_enable_schema_validation,
            empty_result_retry=app_settings.query_empty_result_retry,
            explain_row_warning_threshold=app_settings.query_explain_row_warning_threshold,
            query_timeout_seconds=app_settings.query_timeout_seconds,
        )

    async def process_question(
        self,
        question: str,
        project_id: str,
        connection_config: ConnectionConfig,
        chat_history: list[Message] | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> OrchestratorResponse:
        wf_id = await self._tracker.begin(
            "query",
            {"question": question[:100], "db_type": connection_config.db_type},
        )

        try:
            staleness_warning = await self._check_staleness(project_id)

            if chat_history:
                from app.config import settings as app_settings

                chat_history = await trim_history(
                    chat_history,
                    max_tokens=app_settings.max_history_tokens,
                    llm_router=self._llm_router,
                )

            async with self._tracker.step(
                wf_id, "introspect_schema", f"Fetching schema from {connection_config.db_type}"
            ):
                schema = await self._get_cached_schema(connection_config)
                schema_context, rag_sources = await self._get_schema_context(
                    project_id,
                    connection_config,
                    question,
                    staleness_warning=staleness_warning,
                )

            async with self._tracker.step(wf_id, "load_rules", "Loading custom rules"):
                rules_context = await self._get_rules_context(project_id, question)

            total_usage: dict[str, int] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

            def _accum(usage: dict) -> None:
                for k in total_usage:
                    total_usage[k] += usage.get(k, 0)

            async with self._tracker.step(wf_id, "build_query", "Generating SQL via LLM"):
                build_result = await self._query_builder.build_query(
                    question=question,
                    schema_context=schema_context,
                    rules_context=rules_context,
                    db_type=connection_config.db_type,
                    chat_history=chat_history,
                    preferred_provider=preferred_provider,
                    model=model,
                )
            _accum(build_result.get("usage", {}))

            if build_result.get("error") and not build_result.get("query"):
                await self._tracker.end(wf_id, "query", "completed", "No query generated")
                return OrchestratorResponse(
                    answer=build_result.get("explanation", ""),
                    error=build_result.get("error"),
                    workflow_id=wf_id,
                    staleness_warning=staleness_warning,
                )

            initial_query = build_result["query"]
            initial_explanation = build_result.get("explanation", "")

            conn_key = self._connector_key(connection_config)
            cached = self._query_result_cache.get(conn_key, initial_query)
            if cached is not None:
                async with self._tracker.step(
                    wf_id,
                    "execute_query",
                    "Using cached result",
                ):
                    results = cached
                await self._tracker.end(
                    wf_id,
                    "query",
                    "completed",
                    f"{results.row_count} rows (cached)",
                )
                cache_usage: dict[str, int] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                }
                results_summary = self._summarize_results(results)
                interpretation = await self._query_builder.interpret_results(
                    question=question,
                    query=initial_query,
                    results_summary=results_summary,
                    db_type=connection_config.db_type,
                    preferred_provider=preferred_provider,
                    model=model,
                )
                for k in cache_usage:
                    cache_usage[k] += build_result.get("usage", {}).get(k, 0)
                    cache_usage[k] += interpretation.get("usage", {}).get(k, 0)
                return OrchestratorResponse(
                    answer=interpretation.get("summary", ""),
                    query=initial_query,
                    query_explanation=initial_explanation,
                    results=results,
                    viz_type=interpretation.get("viz_type", "table"),
                    viz_config=interpretation.get("config", {}),
                    workflow_id=wf_id,
                    rag_sources=rag_sources,
                    staleness_warning=staleness_warning,
                    token_usage=cache_usage,
                )

            connector = await self.get_or_create_connector(connection_config)
            val_config = self._build_validation_config()
            db_idx_ctx = await self._get_db_index_context(project_id, connection_config)
            sync_warnings, sync_tips = await self._get_sync_for_repair(connection_config)
            rules_ctx = await self._get_repair_rules_context(project_id)
            dv = await self._get_distinct_values(connection_config)
            enricher = ContextEnricher(
                schema,
                self._vector_store,
                db_index_context=db_idx_ctx,
                sync_context=sync_warnings,
                rules_context=rules_ctx,
                distinct_values=dv,
                sync_query_tips=sync_tips,
            )
            repairer = QueryRepairer(self._llm_router)

            validation_loop = ValidationLoop(
                config=val_config,
                error_classifier=ErrorClassifier(),
                context_enricher=enricher,
                query_repairer=repairer,
                retry_strategy=RetryStrategy(),
                tracker=self._tracker,
            )

            loop_result = await validation_loop.execute(
                initial_query=initial_query,
                initial_explanation=initial_explanation,
                connector=connector,
                schema=schema,
                question=question,
                project_id=project_id,
                workflow_id=wf_id,
                connection_config=connection_config,
                chat_history=chat_history,
                preferred_provider=preferred_provider,
                model=model,
            )

            attempt_dicts = [a.to_dict() for a in loop_result.attempts]

            if not loop_result.success:
                error_msg = (
                    loop_result.final_error.message
                    if loop_result.final_error
                    else "Query validation failed"
                )
                await self._tracker.end(wf_id, "query", "failed", error_msg)
                return OrchestratorResponse(
                    answer=(
                        f"Query failed after {loop_result.total_attempts} attempt(s): {error_msg}"
                    ),
                    query=loop_result.query,
                    query_explanation=loop_result.explanation,
                    results=loop_result.results,
                    error=error_msg,
                    workflow_id=wf_id,
                    attempts=attempt_dicts,
                    total_attempts=loop_result.total_attempts,
                    rag_sources=rag_sources,
                    staleness_warning=staleness_warning,
                )

            results_opt = loop_result.results
            assert results_opt is not None
            results = results_opt

            self._query_result_cache.put(conn_key, loop_result.query, results)

            async with self._tracker.step(
                wf_id, "interpret_results", "Interpreting results via LLM"
            ):
                results_summary = self._summarize_results(results)
                interpretation = await self._query_builder.interpret_results(
                    question=question,
                    query=loop_result.query,
                    results_summary=results_summary,
                    db_type=connection_config.db_type,
                    preferred_provider=preferred_provider,
                    model=model,
                )
            _accum(interpretation.get("usage", {}))

            status_detail = f"{results.row_count} rows returned"
            if loop_result.total_attempts > 1:
                status_detail += f" (resolved after {loop_result.total_attempts} attempts)"
            await self._tracker.end(wf_id, "query", "completed", status_detail)

            return OrchestratorResponse(
                answer=interpretation.get("summary", ""),
                query=loop_result.query,
                query_explanation=loop_result.explanation,
                results=results,
                viz_type=interpretation.get("viz_type", "table"),
                viz_config=interpretation.get("config", {}),
                workflow_id=wf_id,
                attempts=attempt_dicts,
                total_attempts=loop_result.total_attempts,
                rag_sources=rag_sources,
                staleness_warning=staleness_warning,
                token_usage=total_usage,
            )

        except Exception as e:
            logger.exception("Orchestrator error processing question")
            await self._tracker.end(wf_id, "query", "failed", str(e))
            return OrchestratorResponse(
                answer=f"An error occurred: {str(e)}",
                error=str(e),
                workflow_id=wf_id,
            )

    async def _check_staleness(self, project_id: str) -> str | None:
        """Compare last indexed SHA with current repo HEAD; return warning if stale."""
        try:
            from pathlib import Path

            from app.config import settings as app_settings
            from app.knowledge.git_tracker import GitTracker
            from app.models.base import async_session_factory

            repo_dir = Path(app_settings.repo_clone_base_dir) / project_id
            if not repo_dir.exists():
                return None

            git_tracker = GitTracker()
            async with async_session_factory() as session:
                last_sha = await git_tracker.get_last_indexed_sha(
                    session,
                    project_id,
                )
            if not last_sha:
                return "Knowledge base has not been indexed yet."

            head_sha = git_tracker.get_head_sha(repo_dir)
            if head_sha == last_sha:
                return None

            behind = await git_tracker.count_commits_ahead(repo_dir, last_sha)
            if behind > 0:
                return (
                    f"Knowledge base is {behind} commit(s) behind the current HEAD. "
                    "Answers may be based on outdated code. Consider re-indexing."
                )
            return "Knowledge base may be out of date."
        except Exception:
            logger.debug("Staleness check failed", exc_info=True)
            return None

    async def _get_schema_context(
        self,
        project_id: str,
        connection_config: ConnectionConfig,
        question: str,
        staleness_warning: str | None = None,
    ) -> tuple[str, list[RAGSource]]:
        """Return (context_string, rag_sources_used)."""
        from app.config import settings as app_settings

        schema = await self._get_cached_schema(connection_config)
        live_context = self._schema_indexer.schema_to_prompt_context(schema)

        if app_settings.include_sample_data:
            try:
                connector = await self.get_or_create_connector(
                    connection_config,
                )
                samples = await self._schema_indexer.fetch_sample_data(
                    connector,
                    schema,
                )
                live_context = self._schema_indexer.append_sample_data_context(
                    live_context,
                    samples,
                )
            except Exception:
                logger.debug("Sample data fetch failed", exc_info=True)

        rag_results = await asyncio.to_thread(
            self._vector_store.query,
            project_id=project_id,
            query_text=question,
            n_results=5,
        )
        rag_sources: list[RAGSource] = []
        if rag_results:
            live_context += "\n\n## Code Context\n"
            for r in rag_results:
                meta = r.get("metadata", {})
                source = meta.get("source_path", "unknown")
                live_context += f"\n### {source}\n{r['document']}\n"
                rag_sources.append(
                    RAGSource(
                        source_path=source,
                        distance=r.get("distance"),
                        doc_type=meta.get("doc_type", ""),
                        chunk_index=meta.get("chunk_index", ""),
                    )
                )

        live_context += await self._build_cross_reference(project_id, schema)

        db_index_ctx = await self._get_db_index_context(project_id, connection_config)
        if db_index_ctx:
            live_context += f"\n\n{db_index_ctx}"

        if staleness_warning:
            live_context += f"\n\n## ⚠️ Staleness Warning\n{staleness_warning}\n"

        return live_context, rag_sources

    async def _build_cross_reference(
        self,
        project_id: str,
        schema: SchemaInfo,
    ) -> str:
        """Append schema cross-reference when code knowledge is available."""
        try:
            from app.knowledge.project_summarizer import build_schema_cross_reference
            from app.models.base import async_session_factory
            from app.services.project_cache_service import ProjectCacheService

            live_tables = [t.name for t in schema.tables]
            if not live_tables:
                return ""

            cache_svc = ProjectCacheService()
            async with async_session_factory() as session:
                knowledge = await cache_svc.load_knowledge(session, project_id)

            if not knowledge:
                return ""

            xref = build_schema_cross_reference(knowledge, live_tables)
            if "All tables in the database match" in xref:
                return ""
            return f"\n\n{xref}"
        except Exception:
            logger.debug("Schema cross-reference failed", exc_info=True)
            return ""

    async def _get_db_index_context(
        self,
        project_id: str,
        connection_config: ConnectionConfig,
    ) -> str:
        """Load DB index summary if available for this connection."""
        try:
            connection_id = connection_config.connection_id
            if not connection_id:
                return ""

            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            db_index_svc = DbIndexService()

            async with async_session_factory() as session:
                entries = await db_index_svc.get_index(session, connection_id)
                summary = await db_index_svc.get_summary(session, connection_id)

            if not entries:
                return ""

            return db_index_svc.index_to_prompt_context(entries, summary)
        except Exception:
            logger.debug("DB index context load failed", exc_info=True)
            return ""

    async def _get_sync_for_repair(
        self,
        connection_config: ConnectionConfig,
    ) -> tuple[str, str]:
        """Return (warnings_text, query_tips_text) from sync entries."""
        try:
            connection_id = connection_config.connection_id
            if not connection_id:
                return "", ""

            from app.models.base import async_session_factory
            from app.services.code_db_sync_service import CodeDbSyncService

            svc = CodeDbSyncService()
            async with async_session_factory() as session:
                entries = await svc.get_sync(session, connection_id)
            if not entries:
                return "", ""
            warnings: list[str] = []
            tips: list[str] = []
            for e in entries:
                if e.conversion_warnings:
                    warnings.append(f"- {e.table_name}: {e.conversion_warnings}")
                if e.query_recommendations:
                    tips.append(f"- {e.table_name}: {e.query_recommendations}")
                if e.business_logic_notes:
                    tips.append(f"- {e.table_name} (logic): {e.business_logic_notes[:150]}")
            return "\n".join(warnings), "\n".join(tips)
        except Exception:
            logger.debug("Sync load failed", exc_info=True)
            return "", ""

    async def _get_distinct_values(
        self,
        connection_config: ConnectionConfig,
    ) -> dict[str, dict[str, list[str]]]:
        """Load column distinct values from DB index for repair context."""
        try:
            import json as _json

            connection_id = connection_config.connection_id
            if not connection_id:
                return {}

            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                entries = await svc.get_index(session, connection_id)

            result: dict[str, dict[str, list[str]]] = {}
            for e in entries:
                dv_json = getattr(e, "column_distinct_values_json", None) or "{}"
                if dv_json and dv_json != "{}":
                    try:
                        parsed = _json.loads(dv_json)
                        if parsed:
                            result[e.table_name] = parsed
                    except (_json.JSONDecodeError, TypeError):
                        pass
            return result
        except Exception:
            logger.debug("Distinct values load failed", exc_info=True)
            return {}

    async def _get_repair_rules_context(
        self,
        project_id: str,
    ) -> str:
        """Load rules text for the repair context (no question filtering)."""
        try:
            return self._custom_rules.rules_to_context(
                self._custom_rules.load_rules(
                    project_rules_dir=f"./rules/{project_id}",
                )
                + await self._custom_rules.load_db_rules(project_id=project_id)
            )
        except Exception:
            logger.debug("Rules context load failed for repair", exc_info=True)
            return ""

    async def _get_rules_context(
        self,
        project_id: str,
        question: str,
    ) -> str:
        file_rules = self._custom_rules.load_rules(
            project_rules_dir=f"./rules/{project_id}",
        )
        db_rules = await self._custom_rules.load_db_rules(
            project_id=project_id,
        )
        return self._custom_rules.rules_to_context(file_rules + db_rules)

    def _summarize_results(self, results: QueryResult, max_rows: int = 20) -> str:
        if not results.rows:
            return "No results returned."

        lines = [f"Columns: {', '.join(results.columns)}"]
        lines.append(f"Total rows: {results.row_count}")
        lines.append(f"Execution time: {results.execution_time_ms:.1f}ms")
        lines.append("")

        display_rows = results.rows[:max_rows]
        for row in display_rows:
            line = " | ".join(str(v) for v in row)
            lines.append(line)

        if results.row_count > max_rows:
            lines.append(f"... and {results.row_count - max_rows} more rows")

        return "\n".join(lines)

    async def refresh_schema(self, connection_config: ConnectionConfig) -> SchemaInfo:
        """Force re-introspect schema and clear caches for this connection."""
        key = self._connector_key(connection_config)
        self._schema_cache.pop(key, None)
        self._query_result_cache.invalidate(key)
        old_connector = self._connectors.pop(key, None)
        if old_connector:
            try:
                await old_connector.disconnect()
            except Exception:
                pass
        connector = await self.get_or_create_connector(connection_config)
        schema = await connector.introspect_schema()
        self._schema_cache[key] = (schema, time.monotonic())
        return schema

    async def disconnect_all(self):
        for connector in self._connectors.values():
            try:
                await connector.disconnect()
            except Exception:
                pass
        self._connectors.clear()
        self._schema_cache.clear()
