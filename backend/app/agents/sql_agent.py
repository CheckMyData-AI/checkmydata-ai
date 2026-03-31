"""SQLAgent — database query specialist.

Owns the full query lifecycle: context gathering, SQL generation via an
internal LLM tool loop, validation, execution, repair, and learning
extraction.  Called by the orchestrator via the ``query_database``
meta-tool.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.errors import AgentFatalError
from app.agents.prompts import get_current_datetime_str
from app.agents.prompts.sql_prompt import build_sql_system_prompt
from app.agents.tools.sql_tools import get_sql_agent_tools
from app.config import settings
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
from app.core.history_trimmer import trim_loop_messages
from app.core.query_cache import QueryCache
from app.core.query_repair import QueryRepairer
from app.core.query_validation import ValidationConfig
from app.core.retry_strategy import RetryStrategy
from app.core.ttl_cache import TTLCache
from app.core.types import RAGSource
from app.core.validation_loop import ValidationLoop
from app.knowledge.custom_rules import CustomRulesEngine
from app.knowledge.entity_extractor import ProjectKnowledge
from app.knowledge.vector_store import VectorStore
from app.llm.base import LLMResponse, Message, ToolCall
from app.llm.router import LLMRouter
from app.services.project_cache_service import ProjectCacheService

logger = logging.getLogger(__name__)

_SQL_TOOL_CAPS: dict[str, int] = {
    "get_query_context": 4000,
    "get_db_index": 4000,
    "get_sync_context": 2000,
}
_SQL_TOOL_DEFAULT_CAP = 6000


def _cap_tool_result(tool_name: str, text: str) -> str:
    cap = _SQL_TOOL_CAPS.get(tool_name, _SQL_TOOL_DEFAULT_CAP)
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n... (truncated, {len(text)} chars total)"


def _extract_warning_tag(warnings_text: str) -> str:
    """Derive a short tag from conversion_warnings for the table map."""
    text = warnings_text.lower()
    if "cent" in text or "/ 100" in text:
        return "!cents"
    if "soft" in text and "delet" in text:
        return "!soft-del"
    if "utc" in text or "timezone" in text:
        return "!tz"
    if "enum" in text:
        return "!enum"
    if "json" in text:
        return "!json"
    return "!warn"


def _build_enriched_table_map(entries: list, sync_warnings_map: dict[str, str]) -> str:
    """One-liner-per-table map, annotated with sync warning tags."""
    items: list[str] = []
    for e in entries:
        if not e.is_active or e.relevance_score < 2:
            continue
        rows = f"~{e.row_count:,}" if e.row_count else "?"
        desc = (e.business_description or "")[:50].rstrip(".")
        tag = sync_warnings_map.get(e.table_name.lower(), "")
        tag_str = f" [{tag}]" if tag else ""
        items.append(f"{e.table_name}({rows}, {desc}){tag_str}")
    return ", ".join(items) if items else ""


@dataclass
class SQLAgentResult(AgentResult):
    """Typed result returned by the SQL agent."""

    query: str | None = None
    query_explanation: str | None = None
    results: QueryResult | None = None
    attempts: list[Any] = field(default_factory=list)
    rag_sources: list[RAGSource] = field(default_factory=list)
    tool_call_log: list[dict[str, Any]] = field(default_factory=list)
    insights: list[dict[str, Any]] = field(default_factory=list)


class SQLAgent(BaseAgent):
    """Database query specialist agent."""

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        vector_store: VectorStore | None = None,
        rules_engine: CustomRulesEngine | None = None,
    ) -> None:
        self._llm = llm_router or LLMRouter()
        self._vector_store = vector_store or VectorStore()
        self._rules_engine = rules_engine or CustomRulesEngine()
        self._cache_svc = ProjectCacheService()

        self._connectors: dict[str, BaseConnector] = {}
        self._connector_lock = asyncio.Lock()
        self._schema_cache: TTLCache[SchemaInfo] = TTLCache(
            ttl=settings.schema_cache_ttl_seconds,
            max_size=128,
        )
        self._query_cache = QueryCache()
        self._knowledge_cache: TTLCache[ProjectKnowledge] = TTLCache(ttl=300.0, max_size=128)

    @property
    def name(self) -> str:
        return "sql"

    @staticmethod
    def _messages_preview(msgs: list[Message], max_len: int = 500) -> str:
        parts: list[str] = []
        for m in reversed(msgs):
            if m.role in ("user", "assistant"):
                parts.append(f"[{m.role}] {(m.content or '')[:200]}")
                if len("\n".join(parts)) > max_len:
                    break
        return "\n".join(reversed(parts))[:max_len]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(  # type: ignore[override]
        self,
        context: AgentContext,
        *,
        question: str = "",
    ) -> SQLAgentResult:
        question = question or context.user_question
        cfg = context.connection_config

        if cfg is None:
            raise AgentFatalError("No database connection configured")

        tracker = context.tracker
        wf_id = context.workflow_id

        has_db_idx = await self._has_db_index(context.project_id, cfg)
        db_idx_stale = await self._is_db_index_stale(cfg) if has_db_idx else False
        has_sync = await self._has_code_db_sync(cfg) if has_db_idx else False
        has_learnings = await self._has_learnings(cfg)

        table_map = ""
        if has_db_idx and cfg.connection_id:
            table_map = await self._build_table_map(cfg.connection_id, has_sync)

        learnings_prompt = ""
        if has_learnings and cfg.connection_id:
            learnings_prompt = await self._load_learnings_prompt(cfg.connection_id)

        sync_conventions = ""
        sync_critical_warnings = ""
        required_filters_text = ""
        column_value_mappings_text = ""
        if has_sync and cfg.connection_id:
            sync_conventions, sync_critical_warnings = await self._load_sync_for_prompt(
                cfg.connection_id
            )
            (
                required_filters_text,
                column_value_mappings_text,
            ) = await self._load_sync_filters_and_mappings(cfg.connection_id)

        notes_prompt = ""
        if cfg.connection_id:
            notes_prompt = await self._load_notes_prompt(cfg.connection_id)

        system_prompt = build_sql_system_prompt(
            db_type=cfg.db_type,
            has_db_index=has_db_idx,
            db_index_stale=db_idx_stale,
            has_code_db_sync=has_sync,
            has_learnings=has_learnings,
            table_map=table_map,
            learnings_prompt=learnings_prompt,
            sync_conventions=sync_conventions,
            sync_critical_warnings=sync_critical_warnings,
            current_datetime=get_current_datetime_str(),
            notes_prompt=notes_prompt,
            required_filters=required_filters_text,
            column_value_mappings=column_value_mappings_text,
        )

        tools = get_sql_agent_tools(
            has_db_index=has_db_idx,
            has_code_db_sync=has_sync,
            has_learnings=has_learnings,
        )

        messages: list[Message] = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=question),
        ]

        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        result = SQLAgentResult()
        tool_call_log: list[dict[str, Any]] = []
        run_state: dict[str, Any] = {}

        provider = context.sql_provider or context.preferred_provider
        model = context.sql_model or context.model

        sql_loop_budget = self._llm.get_context_window(model)

        max_sql_iter = settings.max_sql_iterations
        for iteration in range(max_sql_iter):
            messages, _ = trim_loop_messages(messages, sql_loop_budget)

            await tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                f"SQL Agent thinking (step {iteration + 1}/{max_sql_iter})…",
            )
            _sd_llm: dict[str, Any] = {}
            async with tracker.step(
                wf_id,
                "sql:llm_call",
                f"SQL LLM call ({iteration + 1}/{max_sql_iter})",
                step_data=_sd_llm,
            ):
                llm_resp: LLMResponse = await self._llm.complete(
                    messages=messages,
                    tools=tools if tools else None,
                    preferred_provider=provider,
                    model=model,
                )
                _sd_llm["input_preview"] = self._messages_preview(messages)
                _sd_llm["output_preview"] = (llm_resp.content or "")[:500]
                if llm_resp.model:
                    _sd_llm["model"] = llm_resp.model
                for _uk in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if _uk in (llm_resp.usage or {}):
                        _sd_llm[_uk] = llm_resp.usage[_uk]

            self.accum_usage(total_usage, llm_resp.usage)

            if not llm_resp.tool_calls:
                break

            messages.append(
                Message(
                    role="assistant",
                    content=llm_resp.content or "",
                    tool_calls=llm_resp.tool_calls,
                )
            )

            for tc in llm_resp.tool_calls:
                tool_desc = tc.name
                if tc.name == "execute_query":
                    q = (tc.arguments or {}).get("query", "")
                    if len(q) > 60:
                        tool_desc = f"execute_query: {q[:60]}…"
                    else:
                        tool_desc = f"execute_query: {q}"
                elif tc.name == "get_schema_info":
                    tool_desc = "Checking database schema"
                await tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    f"SQL Agent → {tool_desc}",
                )
                _sd_tool: dict[str, Any] = {}
                _tc_args = tc.arguments or {}
                if tc.name == "execute_query":
                    _sd_tool["input_preview"] = (_tc_args.get("query", ""))[:1000]
                else:
                    _sd_tool["input_preview"] = str(_tc_args)[:500]
                async with tracker.step(
                    wf_id,
                    f"sql:tool:{tc.name}",
                    f"SQL tool: {tc.name}",
                    step_data=_sd_tool,
                ):
                    result_text = await self._dispatch_tool(
                        tc,
                        context,
                        wf_id,
                        run_state,
                    )
                    _sd_tool["output_preview"] = (result_text or "")[:500]

                result_text = _cap_tool_result(tc.name, result_text)

                tool_call_log.append(
                    {
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "result_preview": result_text[:200],
                    }
                )

                messages.append(
                    Message(
                        role="tool",
                        content=result_text,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )

        result.token_usage = total_usage
        result.tool_call_log = tool_call_log

        last_query = run_state.get("last_query")
        last_explanation = run_state.get("last_explanation")
        last_result: QueryResult | None = run_state.get("last_result")

        if last_query:
            result.query = last_query
            result.query_explanation = last_explanation
            result.results = last_result
            has_result = last_result and not last_result.error
            result.status = "success" if has_result else "error"
            if result.status == "error" and last_result:
                result.error = last_result.error

            if has_result and last_result and last_result.rows:
                try:
                    from app.core.insight_generator import InsightGenerator

                    result.insights = InsightGenerator.analyze(
                        rows=last_result.rows,
                        columns=last_result.columns,
                        query=last_query,
                        question=question,
                    )
                except Exception:
                    logger.debug("Insight generation failed (non-critical)", exc_info=True)
        else:
            result.status = "no_result"

        return result

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def _dispatch_tool(
        self,
        tool_call: ToolCall,
        context: AgentContext,
        wf_id: str,
        run_state: dict[str, Any] | None = None,
    ) -> str:
        handlers: dict[str, Any] = {
            "execute_query": self._handle_execute_query,
            "get_schema_info": self._handle_get_schema_info,
            "get_custom_rules": self._handle_get_custom_rules,
            "get_db_index": self._handle_get_db_index,
            "get_sync_context": self._handle_get_sync_context,
            "get_query_context": self._handle_get_query_context,
            "get_agent_learnings": self._handle_get_agent_learnings,
            "record_learning": self._handle_record_learning,
            "read_notes": self._handle_read_notes,
            "write_note": self._handle_write_note,
        }
        handler = handlers.get(tool_call.name)

        if handler is None:
            return f"Error: unknown tool '{tool_call.name}'"

        try:
            effective_state = run_state if run_state is not None else {}
            return await handler(tool_call.arguments, context, wf_id, run_state=effective_state)
        except Exception as exc:
            logger.exception("SQL tool %s failed", tool_call.name)
            return f"Error executing {tool_call.name}: {exc}"

    # ------------------------------------------------------------------
    # Tool handlers
    # ------------------------------------------------------------------

    async def _handle_execute_query(
        self, args: dict, ctx: AgentContext, wf_id: str, **kwargs: Any
    ) -> str:
        query: str = args.get("query", "")
        explanation: str = args.get("explanation", "")
        cfg = ctx.connection_config
        if cfg is None:
            raise RuntimeError("Expected 'connection_config' but got None")

        connector = await self._get_or_create_connector(cfg)
        schema = await self._get_cached_schema(cfg)
        val_config = self._build_validation_config()

        db_idx_ctx = await self._load_db_index_hints(cfg)
        sync_warnings, sync_tips = await self._load_sync_for_repair(cfg)
        rules_ctx = await self._load_rules_for_repair(ctx.project_id)
        dv = await self._load_distinct_values(cfg)
        learn_ctx = await self._load_learnings_for_repair(cfg)
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
            tracker=ctx.tracker,
        )

        loop_result = await validation_loop.execute(
            initial_query=query,
            initial_explanation=explanation,
            connector=connector,
            schema=schema,
            question=ctx.user_question or query,
            project_id=ctx.project_id,
            workflow_id=wf_id,
            connection_config=cfg,
            chat_history=ctx.chat_history,
            preferred_provider=ctx.sql_provider or ctx.preferred_provider,
            model=ctx.sql_model or ctx.model,
        )

        await self._extract_learnings(
            loop_result.attempts,
            loop_result.success,
            ctx.user_question or query,
            cfg,
        )

        if not loop_result.success:
            err = loop_result.final_error
            msg = err.message if err else "Query validation failed"
            attempts = loop_result.total_attempts
            await ctx.tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                f"Query failed after {attempts} attempt(s): {msg[:80]}",
            )
            return f"Query failed after {attempts} attempt(s): {msg}"

        results = loop_result.results
        if results is None:
            raise RuntimeError("Expected 'results' after successful validation but got None")

        await ctx.tracker.emit(
            wf_id,
            "thinking",
            "in_progress",
            f"Query executed: {results.row_count} rows, {len(results.columns)} columns returned",
        )

        run_state = kwargs.get("run_state", {})
        run_state["last_query"] = loop_result.query
        run_state["last_explanation"] = loop_result.explanation
        run_state["last_result"] = results

        conn_key = connector_key(cfg)
        self._query_cache.put(conn_key, loop_result.query, results)

        formatted = self._format_query_results(results)

        try:
            sanity_text = await self._run_sanity_checks(results, loop_result.query, ctx)
            if sanity_text:
                formatted += sanity_text
        except Exception:
            logger.debug("Sanity check failed (non-critical)", exc_info=True)

        return formatted

    async def _handle_get_schema_info(
        self, args: dict, ctx: AgentContext, wf_id: str, **kwargs: Any
    ) -> str:
        scope: str = args.get("scope", "overview")
        table_name: str | None = args.get("table_name")
        cfg = ctx.connection_config
        if cfg is None:
            raise RuntimeError("Expected 'connection_config' but got None")

        async with ctx.tracker.step(wf_id, "sql:get_schema", f"Fetching schema ({scope})"):
            schema = await self._get_cached_schema(cfg)

        n_tables = len(schema.tables) if schema and schema.tables else 0
        await ctx.tracker.emit(
            wf_id,
            "thinking",
            "in_progress",
            f"Loaded schema: {n_tables} tables",
        )

        if scope == "overview":
            return self._format_schema_overview(schema)
        if scope == "table_detail":
            if not table_name:
                return "Error: table_name is required when scope is 'table_detail'."
            return self._format_table_detail(schema, table_name)
        return f"Error: unknown scope '{scope}'."

    async def _handle_get_custom_rules(
        self, _args: dict, ctx: AgentContext, wf_id: str, **kwargs: Any
    ) -> str:
        async with ctx.tracker.step(wf_id, "sql:load_rules", "Loading custom rules"):
            file_rules = self._rules_engine.load_rules(
                project_rules_dir=f"{settings.custom_rules_dir}/{ctx.project_id}",
            )
            db_rules = await self._rules_engine.load_db_rules(
                project_id=ctx.project_id,
            )
        context = self._rules_engine.rules_to_context(file_rules + db_rules)
        return context or "No custom rules defined for this project."

    async def _handle_get_db_index(
        self, args: dict, ctx: AgentContext, wf_id: str, **kwargs: Any
    ) -> str:
        scope: str = args.get("scope", "overview")
        table_name: str | None = args.get("table_name")
        cfg = ctx.connection_config
        if cfg is None:
            raise RuntimeError("Expected 'connection_config' but got None")

        from app.models.base import async_session_factory
        from app.services.db_index_service import DbIndexService

        svc = DbIndexService()
        async with ctx.tracker.step(wf_id, "sql:get_db_index", f"Loading DB index ({scope})"):
            cid = cfg.connection_id
            if not cid:
                return "Database index not available. Run 'Index DB' first."

            if scope == "project_overview":
                from sqlalchemy import select

                from app.models.project_cache import ProjectCache

                async with async_session_factory() as session:
                    result = await session.execute(
                        select(ProjectCache.overview_text).where(
                            ProjectCache.project_id == ctx.project_id
                        )
                    )
                    text = result.scalar_one_or_none()
                    return text or "Project overview not yet generated."

            async with async_session_factory() as session:
                if scope == "table_detail":
                    if not table_name:
                        return "Error: table_name required for table_detail."
                    entry = await svc.get_table_index(session, cid, table_name)
                    if not entry:
                        return f"No index entry for table '{table_name}'."
                    return svc.table_index_to_detail(entry)
                entries = await svc.get_index(session, cid)
                summary = await svc.get_summary(session, cid)
                if not entries:
                    return "Database index not available. Run 'Index DB' first."
                return svc.index_to_prompt_context(entries, summary)

    async def _handle_get_sync_context(
        self, args: dict, ctx: AgentContext, wf_id: str, **kwargs: Any
    ) -> str:
        scope: str = args.get("scope", "overview")
        table_name: str | None = args.get("table_name")
        cfg = ctx.connection_config
        if cfg is None:
            raise RuntimeError("Expected 'connection_config' but got None")

        from app.models.base import async_session_factory
        from app.services.code_db_sync_service import CodeDbSyncService

        svc = CodeDbSyncService()
        async with ctx.tracker.step(wf_id, "sql:get_sync", f"Loading sync context ({scope})"):
            cid = cfg.connection_id
            if not cid:
                return "Code-DB sync not available."
            async with async_session_factory() as session:
                if scope == "table_detail":
                    if not table_name:
                        return "Error: table_name required for table_detail."
                    entry = await svc.get_table_sync(session, cid, table_name)
                    if not entry:
                        return f"No sync data for table '{table_name}'."
                    return svc.table_sync_to_detail(entry)
                entries = await svc.get_sync(session, cid)
                summary = await svc.get_summary(session, cid)
                if not entries:
                    return "Code-DB sync not available."
                return svc.sync_to_prompt_context(entries, summary)

    async def _handle_get_query_context(
        self, args: dict, ctx: AgentContext, wf_id: str, **kwargs: Any
    ) -> str:
        question: str = args.get("question", "")
        table_names_raw: str | None = args.get("table_names")
        cfg = ctx.connection_config
        if cfg is None:
            raise RuntimeError("Expected 'connection_config' but got None")
        cid = cfg.connection_id
        if not cid:
            return "Query context not available. Run 'Index DB' first."
        async with ctx.tracker.step(wf_id, "sql:get_query_ctx", "Building unified query context"):
            return await self._build_query_context(question, table_names_raw, cid, ctx)

    async def _handle_get_agent_learnings(
        self, args: dict, ctx: AgentContext, wf_id: str, **kwargs: Any
    ) -> str:
        scope: str = args.get("scope", "all")
        table_name: str | None = args.get("table_name")
        cfg = ctx.connection_config
        if cfg is None:
            raise RuntimeError("Expected 'connection_config' but got None")
        cid = cfg.connection_id
        if not cid:
            return "No learnings available."

        from app.models.base import async_session_factory
        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()
        async with ctx.tracker.step(wf_id, "sql:learnings", f"Loading learnings ({scope})"):
            async with async_session_factory() as session:
                if scope == "table" and table_name:
                    learnings = await svc.get_learnings_for_table(session, cid, table_name)
                else:
                    learnings = await svc.get_learnings(session, cid)

        if not learnings:
            return "No learnings recorded yet for this database."

        await self._track_applied_learnings(learnings)

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

    async def _handle_record_learning(
        self, args: dict, ctx: AgentContext, wf_id: str, **kwargs: Any
    ) -> str:
        category: str = args.get("category", "")
        subject: str = args.get("subject", "").strip()
        lesson: str = args.get("lesson", "").strip()

        if not category or not subject or not lesson:
            return "Error: category, subject, and lesson are all required."

        cfg = ctx.connection_config
        if cfg is None:
            raise RuntimeError("Expected 'connection_config' but got None")
        cid = cfg.connection_id
        if not cid:
            return "Error: connection ID not resolved."

        from app.models.base import async_session_factory
        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()
        async with ctx.tracker.step(wf_id, "sql:record_learn", f"Recording: {lesson[:60]}"):
            async with async_session_factory() as session:
                entry = await svc.create_learning(
                    session,
                    connection_id=cid,
                    category=category,
                    subject=subject,
                    lesson=lesson,
                    confidence=0.8,
                    source_query=kwargs.get("run_state", {}).get("last_query"),
                )
                await session.commit()

        return (
            f"Learning recorded successfully.\n"
            f"- **Category:** {category}\n"
            f"- **Subject:** {subject}\n"
            f"- **Lesson:** {lesson}\n"
            f"- **Confidence:** {int(entry.confidence * 100)}%"
        )

    # ------------------------------------------------------------------
    # Session notes handlers
    # ------------------------------------------------------------------

    async def _handle_read_notes(
        self, args: dict, ctx: AgentContext, wf_id: str, **kwargs: Any
    ) -> str:
        cfg = ctx.connection_config
        if cfg is None or not cfg.connection_id:
            return "No session notes available (no connection)."

        table_names_raw: str | None = args.get("table_names")
        category: str | None = args.get("category")

        table_list: list[str] | None = None
        if table_names_raw:
            table_list = [t.strip() for t in table_names_raw.split(",") if t.strip()]

        from app.models.base import async_session_factory
        from app.services.session_notes_service import SessionNotesService

        svc = SessionNotesService()
        async with ctx.tracker.step(wf_id, "sql:read_notes", "Reading session notes"):
            async with async_session_factory() as session:
                notes = await svc.get_notes_for_context(
                    session,
                    cfg.connection_id,
                    table_names=table_list,
                    category=category,
                )

        if not notes:
            return "No session notes recorded yet for this database."

        lines: list[str] = [f"Session notes ({len(notes)} found):\n"]
        for n in notes[:20]:
            verified = " [VERIFIED]" if n.is_verified else ""
            conf = int(n.confidence * 100)
            lines.append(f"- [{n.category}] {n.subject}: {n.note} ({conf}%{verified})")
        return "\n".join(lines)

    async def _handle_write_note(
        self, args: dict, ctx: AgentContext, wf_id: str, **kwargs: Any
    ) -> str:
        category: str = args.get("category", "")
        subject: str = args.get("subject", "").strip()
        note_text: str = args.get("note", "").strip()

        if not category or not subject or not note_text:
            return "Error: category, subject, and note are all required."

        cfg = ctx.connection_config
        if cfg is None or not cfg.connection_id:
            return "Error: connection ID not resolved."

        from app.models.base import async_session_factory
        from app.services.session_notes_service import SessionNotesService

        svc = SessionNotesService()
        async with ctx.tracker.step(wf_id, "sql:write_note", f"Recording note: {note_text[:60]}"):
            async with async_session_factory() as session:
                entry = await svc.create_note(
                    session,
                    connection_id=cfg.connection_id,
                    project_id=ctx.project_id,
                    category=category,
                    subject=subject,
                    note=note_text,
                    confidence=0.7,
                    source_session_id=ctx.session_id if hasattr(ctx, "session_id") else None,
                )
                await session.commit()

        return (
            f"Note recorded successfully.\n"
            f"- **Category:** {category}\n"
            f"- **Subject:** {subject}\n"
            f"- **Note:** {note_text}\n"
            f"- **Confidence:** {int(entry.confidence * 100)}%"
        )

    # ------------------------------------------------------------------
    # Sanity checker integration
    # ------------------------------------------------------------------

    async def _run_sanity_checks(
        self,
        results: QueryResult,
        query: str,
        ctx: AgentContext,
    ) -> str:
        """Run enriched anomaly intelligence on query results."""
        if not results.rows or not results.columns:
            return ""

        from app.core.anomaly_intelligence import AnomalyIntelligenceEngine
        from app.core.data_sanity_checker import DataSanityChecker

        engine = AnomalyIntelligenceEngine()
        checker = DataSanityChecker()

        rows_as_dicts = [dict(zip(results.columns, row)) for row in results.rows]

        reports = engine.analyze(
            rows=rows_as_dicts,
            columns=results.columns,
            query=query,
            question=ctx.user_question or "",
        )

        benchmark_text = await self._check_benchmarks(
            checker,
            rows_as_dicts,
            results.columns,
            ctx,
        )

        text = engine.format_report(reports)

        await self._store_anomaly_insights(reports, ctx)

        if benchmark_text:
            text += benchmark_text
        return text

    async def _store_anomaly_insights(
        self,
        reports: list,
        ctx: AgentContext,
    ) -> None:
        """Persist critical/warning anomalies as insight records."""
        significant = [r for r in reports if r.severity in ("critical", "warning")]
        if not significant or not ctx.project_id:
            return
        try:
            from app.core.insight_memory import InsightMemoryService
            from app.models.base import async_session_factory

            svc = InsightMemoryService()
            conn_id = ctx.connection_config.connection_id if ctx.connection_config else None
            async with async_session_factory() as session:
                for report in significant[:5]:
                    await svc.store_insight(
                        session,
                        project_id=ctx.project_id,
                        connection_id=conn_id,
                        insight_type="anomaly",
                        severity=report.severity,
                        title=report.title,
                        description=report.description,
                        recommended_action=report.recommended_action,
                        expected_impact=report.expected_impact,
                        confidence=report.confidence,
                    )
                await session.commit()
        except Exception:
            logger.debug(
                "Failed to store anomaly insights (non-critical)",
                exc_info=True,
            )

    async def _check_benchmarks(
        self,
        checker: Any,
        rows: list[dict[str, Any]],
        columns: list[str],
        ctx: AgentContext,
    ) -> str:
        """Compare query results against stored benchmarks."""
        cfg = ctx.connection_config
        if not cfg or not cfg.connection_id:
            return ""
        try:
            from app.models.base import async_session_factory
            from app.services.benchmark_service import BenchmarkService

            svc = BenchmarkService()
            async with async_session_factory() as session:
                benchmarks = await svc.get_all_for_connection(
                    session,
                    cfg.connection_id,
                )

            if not benchmarks:
                return ""

            lines: list[str] = []
            for bm in benchmarks:
                if bm.value_numeric is None:
                    continue
                comp = checker.check_against_benchmark(
                    rows,
                    columns,
                    bm.value_numeric,
                    bm.metric_key,
                )
                if comp and comp.level != "ok":
                    icon = "🔴" if comp.level == "critical" else "🟡"
                    lines.append(
                        f"  {icon} [benchmark] Metric '{comp.metric_key}' "
                        f"expected ~{comp.benchmark_value:,.2f} "
                        f"but got {comp.actual_value:,.2f} "
                        f"({comp.deviation_pct}% deviation)"
                    )

            if not lines:
                return ""
            return "\n\n⚠️ BENCHMARK DEVIATIONS:\n" + "\n".join(lines)

        except Exception:
            logger.debug(
                "Benchmark comparison failed (non-critical)",
                exc_info=True,
            )
            return ""

    # ------------------------------------------------------------------
    # Query context builder (mirrors ToolExecutor._build_query_context)
    # ------------------------------------------------------------------

    async def _build_query_context(
        self,
        question: str,
        table_names_raw: str | None,
        connection_id: str,
        ctx: AgentContext,
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

        if ctx.connection_config is None:
            raise RuntimeError("Expected 'connection_config' but got None")
        schema = await self._get_cached_schema(ctx.connection_config)
        schema_map = {t.name.lower(): t for t in schema.tables}

        knowledge = await self._load_knowledge(ctx.project_id)

        rules_dir = f"{settings.custom_rules_dir}/{ctx.project_id}"
        file_rules = self._rules_engine.load_rules(project_rules_dir=rules_dir)
        db_rules = await self._rules_engine.load_db_rules(project_id=ctx.project_id)
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

    # ------------------------------------------------------------------
    # Helpers — connector / schema cache
    # ------------------------------------------------------------------

    _MAX_CONNECTORS = 32

    async def _get_or_create_connector(self, cfg: ConnectionConfig) -> BaseConnector:
        key = connector_key(cfg)
        async with self._connector_lock:
            existing = self._connectors.get(key)
            if existing is not None:
                if not getattr(existing, "_closed", False):
                    return existing
                self._connectors.pop(key, None)

            if len(self._connectors) >= self._MAX_CONNECTORS:
                oldest_key = next(iter(self._connectors))
                old_conn = self._connectors.pop(oldest_key)
                try:
                    await old_conn.disconnect()
                except Exception:
                    logger.debug("Failed to close evicted connector", exc_info=True)

            conn = get_connector(cfg.db_type, ssh_exec_mode=cfg.ssh_exec_mode)
            await conn.connect(cfg)
            self._connectors[key] = conn
            return conn

    async def _get_cached_schema(self, cfg: ConnectionConfig) -> SchemaInfo:
        key = connector_key(cfg)
        cached = self._schema_cache.get(key)
        if cached is not None:
            return cached
        conn = await self._get_or_create_connector(cfg)
        schema = await conn.introspect_schema()
        self._schema_cache.put(key, schema)
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
    # Helpers — context loaders (mirrors ToolExecutor)
    # ------------------------------------------------------------------

    async def _has_db_index(self, project_id: str, cfg: ConnectionConfig) -> bool:
        try:
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            cid = cfg.connection_id
            if not cid:
                cid = await self._resolve_connection_id(project_id, cfg)
                if cid:
                    cfg.connection_id = cid
            if not cid:
                return False
            svc = DbIndexService()
            async with async_session_factory() as session:
                return await svc.is_indexed(session, cid)
        except Exception:
            logger.debug("DB index check failed", exc_info=True)
            return False

    async def _is_db_index_stale(self, cfg: ConnectionConfig) -> bool:
        if not cfg.connection_id:
            return False
        try:
            from app.config import settings as app_settings
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                return await svc.is_stale(
                    session,
                    cfg.connection_id,
                    ttl_hours=app_settings.db_index_ttl_hours,
                )
        except Exception:
            logger.debug("_is_db_index_stale failed", exc_info=True)
            return False

    async def _has_code_db_sync(self, cfg: ConnectionConfig) -> bool:
        if not cfg.connection_id:
            return False
        try:
            from app.models.base import async_session_factory
            from app.services.code_db_sync_service import CodeDbSyncService

            svc = CodeDbSyncService()
            async with async_session_factory() as session:
                return await svc.is_synced(session, cfg.connection_id)
        except Exception:
            logger.debug("_has_code_db_sync failed", exc_info=True)
            return False

    async def _has_learnings(self, cfg: ConnectionConfig) -> bool:
        if not cfg.connection_id:
            return False
        try:
            from app.models.base import async_session_factory
            from app.services.agent_learning_service import AgentLearningService

            svc = AgentLearningService()
            async with async_session_factory() as session:
                return await svc.has_learnings(session, cfg.connection_id)
        except Exception:
            logger.debug("_has_learnings failed", exc_info=True)
            return False

    async def _build_table_map(self, connection_id: str, has_sync: bool = False) -> str:
        try:
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                entries = await svc.get_index(session, connection_id)

            sync_warnings_map: dict[str, str] = {}
            if has_sync:
                try:
                    from app.services.code_db_sync_service import CodeDbSyncService

                    sync_svc = CodeDbSyncService()
                    async with async_session_factory() as session:
                        sync_entries = await sync_svc.get_sync(session, connection_id)
                    for se in sync_entries:
                        if se.conversion_warnings and se.confidence_score >= 3:
                            tag = _extract_warning_tag(se.conversion_warnings)
                            if tag:
                                sync_warnings_map[se.table_name.lower()] = tag
                except Exception:
                    logger.debug("Code-DB sync enrichment parse failed", exc_info=True)

            return _build_enriched_table_map(entries, sync_warnings_map)
        except Exception:
            logger.debug("_build_table_map failed", exc_info=True)
            return ""

    async def _load_learnings_prompt(self, connection_id: str) -> str:
        try:
            from app.models.base import async_session_factory
            from app.services.agent_learning_service import AgentLearningService

            svc = AgentLearningService()
            async with async_session_factory() as session:
                return await svc.get_or_compile_summary(session, connection_id)
        except Exception:
            logger.debug("_load_learnings_prompt failed", exc_info=True)
            return ""

    async def _load_sync_for_prompt(self, connection_id: str) -> tuple[str, str]:
        """Return (data_conventions, critical_warnings) for the system prompt."""
        try:
            from app.models.base import async_session_factory
            from app.services.code_db_sync_service import CodeDbSyncService

            svc = CodeDbSyncService()
            async with async_session_factory() as session:
                entries = await svc.get_sync(session, connection_id)
                summary = await svc.get_summary(session, connection_id)

            conventions = ""
            if summary and summary.data_conventions:
                conventions = summary.data_conventions[:500]

            critical: list[str] = []
            for e in entries:
                if e.conversion_warnings and e.confidence_score >= 4:
                    critical.append(f"- {e.table_name}: {e.conversion_warnings}")
            warnings_text = "\n".join(critical)[:500] if critical else ""

            return conventions, warnings_text
        except Exception:
            logger.debug("_load_sync_for_prompt failed", exc_info=True)
            return "", ""

    async def _load_notes_prompt(self, connection_id: str) -> str:
        try:
            from app.models.base import async_session_factory
            from app.services.session_notes_service import SessionNotesService

            svc = SessionNotesService()
            async with async_session_factory() as session:
                return await svc.compile_notes_prompt(session, connection_id)
        except Exception:
            logger.debug("_load_notes_prompt failed", exc_info=True)
            return ""

    async def _load_sync_filters_and_mappings(self, connection_id: str) -> tuple[str, str]:
        """Return (required_filters_text, column_value_mappings_text) from sync."""
        try:
            import json as json_mod

            from app.models.base import async_session_factory
            from app.services.code_db_sync_service import CodeDbSyncService

            svc = CodeDbSyncService()
            async with async_session_factory() as session:
                entries = await svc.get_sync(session, connection_id)

            filters_lines: list[str] = []
            mappings_lines: list[str] = []

            for e in entries:
                rf = getattr(e, "required_filters_json", "{}") or "{}"
                try:
                    filters = json_mod.loads(rf)
                except (json_mod.JSONDecodeError, TypeError):
                    filters = {}
                if filters and isinstance(filters, dict):
                    for col, cond in filters.items():
                        filters_lines.append(f"- {e.table_name}: ALWAYS add WHERE {col} {cond}")

                cvm = getattr(e, "column_value_mappings_json", "{}") or "{}"
                try:
                    mappings = json_mod.loads(cvm)
                except (json_mod.JSONDecodeError, TypeError):
                    mappings = {}
                if mappings and isinstance(mappings, dict):
                    for col, vals in mappings.items():
                        if isinstance(vals, dict):
                            parts = ", ".join(f"{k}={v}" for k, v in vals.items())
                            mappings_lines.append(f"- {e.table_name}.{col}: {parts}")

            return "\n".join(filters_lines), "\n".join(mappings_lines)
        except Exception:
            logger.debug("_load_sync_filters_and_mappings failed", exc_info=True)
            return "", ""

    async def _resolve_connection_id(self, project_id: str, cfg: ConnectionConfig) -> str | None:
        from app.models.base import async_session_factory
        from app.services.connection_service import ConnectionService

        target_key = connector_key(cfg)
        conn_svc = ConnectionService()
        async with async_session_factory() as session:
            connections = await conn_svc.list_by_project(session, project_id)
            for c in connections:
                c_cfg = await conn_svc.to_config(session, c)
                if connector_key(c_cfg) == target_key:
                    return c.id
        return None

    async def _load_db_index_hints(self, cfg: ConnectionConfig) -> str:
        if not cfg.connection_id:
            return ""
        try:
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                entries = await svc.get_index(session, cfg.connection_id)
                summary = await svc.get_summary(session, cfg.connection_id)
            if not entries:
                return ""
            return svc.index_to_prompt_context(entries, summary)
        except Exception:
            logger.debug("_load_db_index_hints failed", exc_info=True)
            return ""

    async def _load_sync_for_repair(self, cfg: ConnectionConfig) -> tuple[str, str]:
        """Return (warnings_text, query_tips_text) from sync entries."""
        if not cfg.connection_id:
            return "", ""
        try:
            from app.models.base import async_session_factory
            from app.services.code_db_sync_service import CodeDbSyncService

            svc = CodeDbSyncService()
            async with async_session_factory() as session:
                entries = await svc.get_sync(session, cfg.connection_id)
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
            logger.debug("_load_sync_for_repair failed", exc_info=True)
            return "", ""

    async def _load_rules_for_repair(self, project_id: str) -> str:
        try:
            rules_dir = f"{settings.custom_rules_dir}/{project_id}"
            file_rules = self._rules_engine.load_rules(project_rules_dir=rules_dir)
            db_rules = await self._rules_engine.load_db_rules(project_id=project_id)
            return self._rules_engine.rules_to_context(file_rules + db_rules)
        except Exception:
            logger.debug("_load_rules_for_repair failed", exc_info=True)
            return ""

    async def _load_distinct_values(self, cfg: ConnectionConfig) -> dict[str, dict[str, list[str]]]:
        if not cfg.connection_id:
            return {}
        try:
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                entries = await svc.get_index(session, cfg.connection_id)
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
            logger.debug("_load_distinct_values failed", exc_info=True)
            return {}

    async def _load_learnings_for_repair(self, cfg: ConnectionConfig) -> str:
        if not cfg.connection_id:
            return ""
        try:
            from app.models.base import async_session_factory
            from app.services.agent_learning_service import AgentLearningService

            svc = AgentLearningService()
            async with async_session_factory() as session:
                learnings = await svc.get_learnings(
                    session,
                    cfg.connection_id,
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
            logger.debug("_load_learnings_for_repair failed", exc_info=True)
            return ""

    async def _load_knowledge(self, project_id: str) -> ProjectKnowledge | None:
        cached = self._knowledge_cache.get(project_id)
        if cached is not None:
            return cached

        from app.models.base import async_session_factory

        async with async_session_factory() as session:
            knowledge = await self._cache_svc.load_knowledge(session, project_id)
        if knowledge is not None:
            self._knowledge_cache.put(project_id, knowledge)
        return knowledge

    async def _track_applied_learnings(self, learnings: list) -> None:
        """Fire-and-forget: bump times_applied for each learning the LLM consumed."""
        try:
            from app.models.base import async_session_factory
            from app.services.agent_learning_service import AgentLearningService

            svc = AgentLearningService()
            async with async_session_factory() as session:
                for lrn in learnings:
                    await svc.apply_learning(session, lrn.id)
                await session.commit()
        except Exception:
            logger.debug("apply_learning tracking failed (non-critical)", exc_info=True)

    async def _extract_learnings(
        self,
        attempts: list,
        success: bool,
        question: str,
        cfg: ConnectionConfig,
    ) -> None:
        if not cfg.connection_id or not attempts or len(attempts) < 2:
            return
        try:
            from app.knowledge.learning_analyzer import LearningAnalyzer
            from app.models.base import async_session_factory

            analyzer = LearningAnalyzer()
            async with async_session_factory() as session:
                await analyzer.analyze(
                    session=session,
                    connection_id=cfg.connection_id,
                    question=question,
                    attempts=attempts,
                    success=success,
                )

            if len(attempts) >= 3:
                try:
                    from app.knowledge.learning_analyzer import LLMAnalyzer

                    llm_analyzer = LLMAnalyzer()
                    async with async_session_factory() as session:
                        await llm_analyzer.analyze(
                            session=session,
                            connection_id=cfg.connection_id,
                            attempts=attempts,
                        )
                except Exception:
                    logger.debug("LLM learning analysis failed (non-critical)", exc_info=True)

        except Exception:
            logger.debug("Learning extraction failed (non-critical)", exc_info=True)

    # ------------------------------------------------------------------
    # Formatting helpers (mirrors ToolExecutor)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_query_results(results: QueryResult, max_rows: int = 20) -> str:
        if not results.rows:
            return "Query executed successfully but returned no rows."
        header = "| " + " | ".join(results.columns) + " |"
        sep = "| " + " | ".join("---" for _ in results.columns) + " |"
        lines = [
            f"Total rows: {results.row_count}, Execution time: {results.execution_time_ms:.1f}ms",
            "",
            header,
            sep,
        ]
        for row in results.rows[:max_rows]:
            lines.append("| " + " | ".join(str(v) for v in row) + " |")
        if results.row_count > max_rows:
            lines.append(f"\n... and {results.row_count - max_rows} more rows")
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
            return f"Table '{table_name}' not found. Available: {available}"
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

    @staticmethod
    def _format_table_context(
        db_entry: Any,
        schema_table: Any,
        sync_entry: Any,
        knowledge: Any,
    ) -> str:
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
                raw = sync_entry.column_sync_notes_json
                sync_notes = _json.loads(raw) if raw else {}
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
    def _auto_detect_tables(question: str, entries: list) -> list:
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
    def _filter_rules(all_rules: list, question: str, relevant_entries: list) -> str:
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
