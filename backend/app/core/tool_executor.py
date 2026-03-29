"""Execute agent tool calls by routing to the appropriate handler.

DEPRECATED: This module is preserved for backward compatibility with
existing tests.  Production code now lives in the multi-agent system —
``app.agents.sql_agent.SQLAgent`` absorbed all tool handlers, learning
extraction, and query-context building that previously lived here.
New code should use ``SQLAgent`` instead.

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
        schema_indexer: SchemaIndexer | None,
        rules_engine: CustomRulesEngine,
        tracker: WorkflowTracker,
        *,
        user_question: str = "",
        chat_history: list | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
        sql_provider: str | None = None,
        sql_model: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self._project_id = project_id
        self._connection_config = connection_config
        self._user_id = user_id
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
            "get_sync_context": self._get_sync_context,
            "get_query_context": self._get_query_context,
            "manage_custom_rules": self._manage_custom_rules,
            "get_agent_learnings": self._get_agent_learnings,
            "record_learning": self._record_learning,
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
        sync_warnings, sync_tips = await self._load_sync_for_repair()
        rules_ctx = await self._load_rules_for_repair()
        dv = await self._load_distinct_values()
        learn_ctx = await self._load_learnings_for_repair()
        enricher = ContextEnricher(
            schema,
            self._vector_store,
            db_index_context=db_idx_ctx,
            sync_context=sync_warnings,
            rules_context=rules_ctx,
            distinct_values=dv,
            learnings_context=learn_ctx,
            sync_query_tips=sync_tips,
        )
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

        await self._extract_learnings(
            loop_result.attempts,
            loop_result.success,
            self._user_question or query,
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

    RAG_RELEVANCE_THRESHOLD = 0.7

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

        filtered = [
            r
            for r in results
            if r.get("distance") is None or r["distance"] <= self.RAG_RELEVANCE_THRESHOLD
        ]

        if not filtered:
            return "No sufficiently relevant documents found in the knowledge base."

        parts: list[str] = []
        for r in filtered:
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

        return f"Found {len(filtered)} relevant document(s):\n\n" + "\n\n".join(parts)

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

    async def _manage_custom_rules(self, args: dict, wf_id: str) -> str:
        action: str = args.get("action", "")
        name: str = args.get("name", "").strip()
        content: str = args.get("content", "").strip()
        rule_id: str = args.get("rule_id", "").strip()

        if action not in ("create", "update", "delete"):
            return f"Error: invalid action '{action}'. Use 'create', 'update', or 'delete'."

        if action == "create" and not name:
            return "Error: 'name' is required when action is 'create'."
        if action == "create" and not content:
            return "Error: 'content' is required when action is 'create'."
        if action == "update" and not rule_id:
            return "Error: 'rule_id' is required when action is 'update'."
        if action == "update" and not content and not name:
            return "Error: at least 'name' or 'content' must be provided for update."
        if action == "delete" and not rule_id:
            return "Error: 'rule_id' is required when action is 'delete'."

        from app.models.base import async_session_factory
        from app.services.membership_service import MembershipService
        from app.services.rule_service import RuleService

        membership_svc = MembershipService()
        rule_svc = RuleService()

        async with self._tracker.step(wf_id, "manage_rules", f"Managing custom rule ({action})"):
            async with async_session_factory() as session:
                if self._user_id:
                    from app.services.membership_service import ROLE_HIERARCHY

                    role = await membership_svc.get_role(session, self._project_id, self._user_id)
                    if role is None or ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY.get("editor", 0):
                        return (
                            "Permission denied: requires at least 'editor' role to manage rules. "
                            "Ask the project owner to update your role, or use the sidebar."
                        )
                else:
                    return "Error: user identity not available for permission check."

                if action == "create":
                    rule = await rule_svc.create(
                        session,
                        project_id=self._project_id,
                        name=name,
                        content=content,
                        format="markdown",
                    )
                    return (
                        f"Rule created successfully.\n"
                        f"- **Name:** {rule.name}\n"
                        f"- **ID:** {rule.id}\n"
                        f"- **Content:** {rule.content[:200]}"
                    )

                if action == "update":
                    update_kwargs: dict = {}
                    if name:
                        update_kwargs["name"] = name
                    if content:
                        update_kwargs["content"] = content
                    updated_rule = await rule_svc.update(session, rule_id, **update_kwargs)
                    if not updated_rule:
                        return f"Error: rule with id '{rule_id}' not found."
                    return (
                        f"Rule updated successfully.\n"
                        f"- **Name:** {updated_rule.name}\n"
                        f"- **ID:** {updated_rule.id}\n"
                        f"- **Content:** {updated_rule.content[:200]}"
                    )

                deleted = await rule_svc.delete(session, rule_id)
                if not deleted:
                    return f"Error: rule with id '{rule_id}' not found."
                return f"Rule deleted successfully (id: {rule_id})."

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

        async with self._tracker.step(wf_id, "get_db_index", f"Loading database index ({scope})"):
            connection_id = self._connection_config.connection_id
            if not connection_id:
                return "Database index not available. Run 'Index DB' first."

            if scope == "project_overview":
                return await self._get_project_overview()

            async with async_session_factory() as session:
                if scope == "table_detail":
                    if not table_name:
                        return "Error: table_name is required when scope is 'table_detail'."
                    entry = await db_index_svc.get_table_index(session, connection_id, table_name)
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

    async def _get_project_overview(self) -> str:
        """Return the pre-generated project knowledge overview."""
        from sqlalchemy import select

        from app.models.base import async_session_factory
        from app.models.project_cache import ProjectCache

        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(ProjectCache.overview_text).where(
                        ProjectCache.project_id == self._project_id
                    )
                )
                text = result.scalar_one_or_none()
                if text:
                    return text
                return "Project overview not yet generated. Run DB indexing or repo indexing first."
        except Exception:
            logger.debug("Failed to load project overview", exc_info=True)
            return "Project overview not available."

    async def _get_sync_context(self, args: dict, wf_id: str) -> str:
        scope: str = args.get("scope", "overview")
        table_name: str | None = args.get("table_name")

        if not self._connection_config:
            return "Error: no database connection configured for this project."

        from app.models.base import async_session_factory
        from app.services.code_db_sync_service import CodeDbSyncService

        sync_svc = CodeDbSyncService()

        async with self._tracker.step(wf_id, "get_sync_context", f"Loading sync context ({scope})"):
            connection_id = self._connection_config.connection_id
            if not connection_id:
                return "Code-DB sync not available. Run 'Sync' first."

            async with async_session_factory() as session:
                if scope == "table_detail":
                    if not table_name:
                        return "Error: table_name is required when scope is 'table_detail'."
                    entry = await sync_svc.get_table_sync(session, connection_id, table_name)
                    if not entry:
                        return (
                            f"No sync data for table '{table_name}'. "
                            "The table may not have been synced yet."
                        )
                    return sync_svc.table_sync_to_detail(entry)

                entries = await sync_svc.get_sync(session, connection_id)
                summary = await sync_svc.get_summary(session, connection_id)

                if not entries:
                    return "Code-DB sync not available. Run 'Sync' first."

                return sync_svc.sync_to_prompt_context(entries, summary)

    async def _get_query_context(self, args: dict, wf_id: str) -> str:
        question: str = args.get("question", "")
        table_names_raw: str | None = args.get("table_names")

        if not self._connection_config:
            return "Error: no database connection configured for this project."

        connection_id = self._connection_config.connection_id
        if not connection_id:
            return "Query context not available. Run 'Index DB' first."

        async with self._tracker.step(wf_id, "get_query_context", "Building unified query context"):
            return await self._build_query_context(question, table_names_raw, connection_id)

    async def _get_agent_learnings(self, args: dict, wf_id: str) -> str:
        scope: str = args.get("scope", "all")
        table_name: str | None = args.get("table_name")

        if not self._connection_config:
            return "Error: no database connection configured for this project."

        connection_id = self._connection_config.connection_id
        if not connection_id:
            return "No learnings available — connection ID not resolved."

        from app.models.base import async_session_factory
        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()

        async with self._tracker.step(
            wf_id, "get_agent_learnings", f"Loading agent learnings ({scope})"
        ):
            async with async_session_factory() as session:
                if scope == "table" and table_name:
                    learnings = await svc.get_learnings_for_table(
                        session, connection_id, table_name
                    )
                else:
                    learnings = await svc.get_learnings(session, connection_id)

        if not learnings:
            return "No learnings recorded yet for this database."

        from app.services.agent_learning_service import CATEGORY_LABELS

        by_cat: dict[str, list] = {}
        for lrn in learnings:
            by_cat.setdefault(lrn.category, []).append(lrn)

        parts: list[str] = [f"Agent learnings ({len(learnings)} total):\n"]
        for cat, items in by_cat.items():
            label = CATEGORY_LABELS.get(cat, cat)
            parts.append(f"### {label}")
            for lrn in items:
                conf = int(lrn.confidence * 100)
                parts.append(f"- {lrn.lesson} [{conf}% confidence]")
            parts.append("")

        return "\n".join(parts)

    async def _record_learning(self, args: dict, wf_id: str) -> str:
        category: str = args.get("category", "")
        subject: str = args.get("subject", "").strip()
        lesson: str = args.get("lesson", "").strip()

        if not category or not subject or not lesson:
            return "Error: category, subject, and lesson are all required."

        if not self._connection_config:
            return "Error: no database connection configured for this project."

        connection_id = self._connection_config.connection_id
        if not connection_id:
            return "Error: connection ID not resolved."

        from app.models.base import async_session_factory
        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()

        async with self._tracker.step(
            wf_id, "record_learning", f"Recording learning: {lesson[:60]}"
        ):
            async with async_session_factory() as session:
                entry = await svc.create_learning(
                    session,
                    connection_id=connection_id,
                    category=category,
                    subject=subject,
                    lesson=lesson,
                    confidence=0.8,
                    source_query=self.ctx.last_query,
                )
                await session.commit()

        return (
            f"Learning recorded successfully.\n"
            f"- **Category:** {category}\n"
            f"- **Subject:** {subject}\n"
            f"- **Lesson:** {lesson}\n"
            f"- **Confidence:** {int(entry.confidence * 100)}%"
        )

    async def _build_query_context(
        self,
        question: str,
        table_names_raw: str | None,
        connection_id: str,
    ) -> str:
        from app.models.base import async_session_factory
        from app.services.agent_learning_service import AgentLearningService
        from app.services.code_db_sync_service import CodeDbSyncService
        from app.services.db_index_service import DbIndexService

        db_index_svc = DbIndexService()
        sync_svc = CodeDbSyncService()
        learning_svc = AgentLearningService()

        async with async_session_factory() as session:
            all_entries = await db_index_svc.get_index(session, connection_id)
            sync_entries_list = await sync_svc.get_sync(session, connection_id)
            sync_summary = await sync_svc.get_summary(session, connection_id)
            learnings = await learning_svc.get_learnings(session, connection_id)

        if not all_entries:
            return "Database index not available. Run 'Index DB' first."

        sync_map = {e.table_name.lower(): e for e in sync_entries_list}

        if table_names_raw:
            requested = {t.strip().lower() for t in table_names_raw.split(",")}
            relevant = [e for e in all_entries if e.table_name.lower() in requested]
            if not relevant:
                relevant = all_entries[:10]
        else:
            relevant = self._auto_detect_tables(question, all_entries)

        if not self._connection_config:
            return "No database connection configured."
        schema = await self._get_cached_schema(self._connection_config)
        schema_map = {t.name.lower(): t for t in schema.tables}

        knowledge = await self._load_knowledge()

        file_rules = self._rules_engine.load_rules(
            project_rules_dir=f"./rules/{self._project_id}",
        )
        db_rules = await self._rules_engine.load_db_rules(
            project_id=self._project_id,
        )
        all_rules = file_rules + db_rules
        rules_text = self._filter_rules(all_rules, question, relevant)

        parts: list[str] = ["## Query Context\n"]

        if sync_summary and sync_summary.global_notes:
            parts.append(f"**Data overview:** {sync_summary.global_notes}\n")

        if sync_summary and sync_summary.data_conventions:
            parts.append(f"**Data conventions:** {sync_summary.data_conventions}\n")

        relevant_table_names = {e.table_name.lower() for e in relevant}
        relevant_learnings = [
            lrn
            for lrn in learnings
            if lrn.subject.lower() in relevant_table_names
            or any(t in lrn.lesson.lower() for t in relevant_table_names)
        ]
        if relevant_learnings:
            parts.append("### Agent Learnings (from past experience)")
            for lrn in relevant_learnings[:8]:
                conf = int(lrn.confidence * 100)
                parts.append(f"- **{lrn.subject}**: {lrn.lesson} [{conf}%]")
            parts.append("")

        for entry in relevant:
            tbl = schema_map.get(entry.table_name.lower())
            sync_entry = sync_map.get(entry.table_name.lower())
            parts.append(self._format_table_context(entry, tbl, sync_entry, knowledge))

        if sync_summary and sync_summary.query_guidelines:
            parts.append(f"### Query Guidelines\n{sync_summary.query_guidelines}\n")

        join_recs = getattr(sync_summary, "join_recommendations", "") if sync_summary else ""
        if join_recs:
            parts.append(f"### Recommended JOIN Paths\n{join_recs}\n")

        if rules_text:
            parts.append(f"### Applicable Rules\n{rules_text}\n")

        return "\n".join(parts)

    def _auto_detect_tables(
        self,
        question: str,
        entries: list,
    ) -> list:
        q_lower = question.lower()
        scored: list[tuple[int, object]] = []

        for entry in entries:
            if not entry.is_active and entry.relevance_score <= 1:
                continue
            score = 0
            tbl_lower = entry.table_name.lower()
            if tbl_lower in q_lower:
                score += 10
            desc = (entry.business_description or "").lower()
            for word in q_lower.split():
                if len(word) > 3 and word in desc:
                    score += 2
                if len(word) > 3 and word in tbl_lower:
                    score += 3
            if entry.relevance_score >= 4:
                score += 2
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        if scored:
            return [e for _, e in scored[:8]]

        return [e for e in entries if e.is_active and e.relevance_score >= 3][:8]

    @staticmethod
    def _format_table_context(
        db_entry,
        schema_table,
        sync_entry,
        knowledge,
    ) -> str:
        import json as _json

        parts: list[str] = [f"### {db_entry.table_name}"]

        if db_entry.business_description:
            parts.append(f"{db_entry.business_description}")
        if db_entry.row_count is not None:
            parts.append(f"Rows: ~{db_entry.row_count:,}")

        if schema_table:
            cols_lines: list[str] = []
            for col in schema_table.columns:
                pk = " PK" if col.is_primary_key else ""
                null = " NULL" if col.is_nullable else ""
                cols_lines.append(f"  {col.name}: {col.data_type}{pk}{null}")
            parts.append("Columns:\n" + "\n".join(cols_lines))

            if schema_table.foreign_keys:
                fk_lines = [
                    f"  {fk.column} -> {fk.references_table}.{fk.references_column}"
                    for fk in schema_table.foreign_keys
                ]
                parts.append("FKs:\n" + "\n".join(fk_lines))

        dv_json = getattr(db_entry, "column_distinct_values_json", "{}")
        try:
            distinct = _json.loads(dv_json) if dv_json else {}
        except (_json.JSONDecodeError, TypeError):
            distinct = {}
        if distinct:
            dv_lines = []
            for col, vals in distinct.items():
                vals_str = " | ".join(str(v) for v in vals[:20])
                dv_lines.append(f"  {col}: [{vals_str}]")
            parts.append("Distinct values:\n" + "\n".join(dv_lines))

        if sync_entry and sync_entry.conversion_warnings:
            parts.append(f"WARNINGS: {sync_entry.conversion_warnings}")

        col_notes_merged: dict[str, str] = {}
        try:
            db_notes = _json.loads(db_entry.column_notes_json) if db_entry.column_notes_json else {}
        except (_json.JSONDecodeError, TypeError):
            db_notes = {}
        if db_notes and isinstance(db_notes, dict):
            col_notes_merged.update(db_notes)

        if sync_entry:
            try:
                sync_notes = (
                    _json.loads(sync_entry.column_sync_notes_json)
                    if sync_entry.column_sync_notes_json
                    else {}
                )
            except (_json.JSONDecodeError, TypeError):
                sync_notes = {}
            if sync_notes and isinstance(sync_notes, dict):
                for col, note in sync_notes.items():
                    existing = col_notes_merged.get(col, "")
                    if existing and note not in existing:
                        col_notes_merged[col] = f"{existing}; {note}"
                    else:
                        col_notes_merged[col] = note

        if col_notes_merged:
            notes_lines = [f"  {c}: {n}" for c, n in col_notes_merged.items()]
            parts.append("Column notes:\n" + "\n".join(notes_lines))

        numeric_notes_raw = getattr(db_entry, "numeric_format_notes", "{}")
        try:
            numeric_notes = _json.loads(numeric_notes_raw) if numeric_notes_raw else {}
        except (_json.JSONDecodeError, TypeError):
            numeric_notes = {}
        if numeric_notes and isinstance(numeric_notes, dict):
            nf_lines = [f"  {c}: {n}" for c, n in numeric_notes.items()]
            parts.append("Numeric formats:\n" + "\n".join(nf_lines))

        if sync_entry and sync_entry.business_logic_notes:
            parts.append(f"Business logic: {sync_entry.business_logic_notes[:200]}")

        if sync_entry and sync_entry.query_recommendations:
            parts.append(f"Query tips: {sync_entry.query_recommendations}")

        if db_entry.query_hints:
            parts.append(f"Query hints: {db_entry.query_hints}")

        if knowledge:
            tbl_lower = db_entry.table_name.lower()
            for _name, entity in knowledge.entities.items():
                if entity.table_name and entity.table_name.lower() == tbl_lower:
                    if entity.read_queries or entity.write_queries:
                        parts.append(
                            f"Code usage: {entity.read_queries} reads, "
                            f"{entity.write_queries} writes"
                        )
                    break

        parts.append("")
        return "\n".join(parts)

    @staticmethod
    def _filter_rules(all_rules, question: str, relevant_entries: list) -> str:
        if not all_rules:
            return ""
        q_lower = question.lower()
        table_names = {e.table_name.lower() for e in relevant_entries}

        matched: list[str] = []
        for rule in all_rules:
            content_lower = rule.content.lower()
            relevant = False
            for tbl in table_names:
                if tbl in content_lower:
                    relevant = True
                    break
            if not relevant:
                for word in q_lower.split():
                    if len(word) > 4 and word in content_lower:
                        relevant = True
                        break
            if relevant:
                matched.append(f"**{rule.name}:** {rule.content[:500]}")

        if not matched and all_rules:
            for rule in all_rules[:2]:
                matched.append(f"**{rule.name}:** {rule.content[:300]}")

        return "\n".join(matched)

    async def _extract_learnings(
        self,
        attempts: list,
        success: bool,
        question: str,
    ) -> None:
        """Fire-and-forget learning extraction after validation loop."""
        if not self._connection_config or not self._connection_config.connection_id:
            return
        if not attempts or len(attempts) < 2:
            return

        try:
            from app.knowledge.learning_analyzer import LearningAnalyzer
            from app.models.base import async_session_factory

            analyzer = LearningAnalyzer()
            async with async_session_factory() as session:
                await analyzer.analyze(
                    session=session,
                    connection_id=self._connection_config.connection_id,
                    question=question,
                    attempts=attempts,
                    success=success,
                )
        except Exception:
            logger.debug("Learning extraction failed (non-critical)", exc_info=True)

    async def _load_learnings_for_repair(self) -> str:
        """Load compact learnings for query repair context."""
        if not self._connection_config or not self._connection_config.connection_id:
            return ""
        try:
            from app.models.base import async_session_factory
            from app.services.agent_learning_service import AgentLearningService

            svc = AgentLearningService()
            async with async_session_factory() as session:
                learnings = await svc.get_learnings(
                    session,
                    self._connection_config.connection_id,
                    min_confidence=0.5,
                    active_only=True,
                )
            if not learnings:
                return ""
            lines = []
            for lrn in learnings[:15]:
                lines.append(f"- [{lrn.category}] {lrn.subject}: {lrn.lesson}")
            return "\n".join(lines)
        except Exception:
            logger.debug("Failed to load learnings for repair context", exc_info=True)
            return ""

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

    async def _load_sync_for_repair(self) -> tuple[str, str]:
        """Return (warnings_text, query_tips_text) from sync entries."""
        if not self._connection_config or not self._connection_config.connection_id:
            return "", ""
        try:
            from app.models.base import async_session_factory
            from app.services.code_db_sync_service import CodeDbSyncService

            svc = CodeDbSyncService()
            async with async_session_factory() as session:
                entries = await svc.get_sync(session, self._connection_config.connection_id)
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
            logger.debug("Failed to load sync for repair context", exc_info=True)
            return "", ""

    async def _load_rules_for_repair(self) -> str:
        """Load custom rules text for repair context."""
        try:
            file_rules = self._rules_engine.load_rules(
                project_rules_dir=f"./rules/{self._project_id}",
            )
            db_rules = await self._rules_engine.load_db_rules(
                project_id=self._project_id,
            )
            return self._rules_engine.rules_to_context(file_rules + db_rules)
        except Exception:
            logger.debug("Failed to load rules for repair context", exc_info=True)
            return ""

    async def _load_distinct_values(self) -> dict[str, dict[str, list[str]]]:
        """Load column distinct values from DB index for repair context."""
        if not self._connection_config or not self._connection_config.connection_id:
            return {}
        try:
            import json as _json

            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                entries = await svc.get_index(session, self._connection_config.connection_id)
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
            logger.debug("Failed to load distinct values for repair context", exc_info=True)
            return {}

    async def _load_knowledge(self) -> ProjectKnowledge | None:
        if self._knowledge_cache is not None:
            return self._knowledge_cache
        from app.models.base import async_session_factory

        async with async_session_factory() as session:
            self._knowledge_cache = await self._cache_svc.load_knowledge(session, self._project_id)
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
                tables = ", ".join(sf.get("tables") or [])
                lines.append(f"- `{sf['name']}` in `{sf['file_path']}` -> tables: {tables}")
        return "\n".join(lines)
