"""ConversationalAgent — multi-tool agent loop.

Replaces the rigid ``Orchestrator.process_question()`` pipeline with a
flexible loop where the LLM decides which tools (if any) to call on
each turn.  The LLM can chat naturally, search the knowledge base,
query databases, discuss results, or combine several tools in one turn.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.connectors.base import ConnectionConfig, QueryResult, connector_key
from app.core.history_trimmer import trim_history
from app.core.prompt_builder import build_agent_system_prompt
from app.core.query_builder import QueryBuilder
from app.core.tool_executor import ToolExecutor
from app.core.tools import get_available_tools
from app.core.types import RAGSource
from app.core.workflow_tracker import WorkflowTracker
from app.core.workflow_tracker import tracker as default_tracker
from app.knowledge.custom_rules import CustomRulesEngine
from app.knowledge.schema_indexer import SchemaIndexer
from app.knowledge.vector_store import VectorStore
from app.llm.base import LLMResponse, Message
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5


@dataclass
class AgentResponse:
    answer: str = ""
    query: str | None = None
    query_explanation: str | None = None
    results: QueryResult | None = None
    viz_type: str = "text"
    viz_config: dict = field(default_factory=dict)
    knowledge_sources: list[RAGSource] = field(default_factory=list)
    error: str | None = None
    workflow_id: str | None = None
    token_usage: dict = field(default_factory=dict)
    staleness_warning: str | None = None
    response_type: str = "text"  # text | sql_result | knowledge | error
    tool_call_log: list[dict] = field(default_factory=list)


class ConversationalAgent:
    """Multi-tool conversational agent for data exploration & knowledge Q&A."""

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        vector_store: VectorStore | None = None,
        custom_rules: CustomRulesEngine | None = None,
        workflow_tracker: WorkflowTracker | None = None,
    ) -> None:
        self._llm = llm_router or LLMRouter()
        self._vector_store = vector_store or VectorStore()
        self._custom_rules = custom_rules or CustomRulesEngine()
        self._schema_indexer = SchemaIndexer()
        self._tracker = workflow_tracker or default_tracker
        self._query_builder = QueryBuilder(self._llm)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        question: str,
        project_id: str,
        connection_config: ConnectionConfig | None = None,
        chat_history: list[Message] | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
        sql_provider: str | None = None,
        sql_model: str | None = None,
        project_name: str | None = None,
    ) -> AgentResponse:
        wf_id = await self._tracker.begin(
            "agent",
            {"question": question[:100], "has_connection": connection_config is not None},
        )

        try:
            staleness_warning = await self._check_staleness(project_id)

            if chat_history:
                from app.config import settings as app_settings

                chat_history = await trim_history(
                    chat_history,
                    max_tokens=app_settings.max_history_tokens,
                    llm_router=self._llm,
                    preferred_provider=preferred_provider,
                    model=model,
                )

            has_connection = connection_config is not None
            has_kb = self._has_knowledge_base(project_id)
            has_db_idx = await self._has_db_index(project_id, connection_config)
            db_idx_stale = await self._is_db_index_stale(connection_config) if has_db_idx else False
            db_type = connection_config.db_type if connection_config else None

            system_prompt = build_agent_system_prompt(
                project_name=project_name,
                db_type=db_type,
                has_connection=has_connection,
                has_knowledge_base=has_kb,
                has_db_index=has_db_idx,
                db_index_stale=db_idx_stale,
            )

            tools = get_available_tools(
                has_connection=has_connection,
                has_knowledge_base=has_kb,
                has_db_index=has_db_idx,
            )

            executor = ToolExecutor(
                project_id=project_id,
                connection_config=connection_config,
                llm_router=self._llm,
                vector_store=self._vector_store,
                schema_indexer=self._schema_indexer,
                rules_engine=self._custom_rules,
                tracker=self._tracker,
                user_question=question,
                chat_history=chat_history,
                preferred_provider=preferred_provider,
                model=model,
                sql_provider=sql_provider,
                sql_model=sql_model,
            )

            messages: list[Message] = [Message(role="system", content=system_prompt)]
            if chat_history:
                messages.extend(chat_history)
            messages.append(Message(role="user", content=question))

            total_usage: dict[str, int] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

            final_text = ""
            tool_call_log: list[dict] = []

            for iteration in range(MAX_TOOL_ITERATIONS):
                async with self._tracker.step(
                    wf_id,
                    "llm_call",
                    f"LLM call (iteration {iteration + 1}/{MAX_TOOL_ITERATIONS})",
                ):
                    llm_resp: LLMResponse = await self._llm.complete(
                        messages=messages,
                        tools=tools if tools else None,
                        preferred_provider=preferred_provider,
                        model=model,
                    )

                self._accum_usage(total_usage, llm_resp.usage)

                if not llm_resp.tool_calls:
                    final_text = llm_resp.content or ""
                    break

                assistant_content = llm_resp.content or ""
                messages.append(
                    Message(
                        role="assistant",
                        content=assistant_content,
                        tool_calls=llm_resp.tool_calls,
                    )
                )

                for tc in llm_resp.tool_calls:
                    async with self._tracker.step(
                        wf_id, f"tool:{tc.name}", f"Executing tool: {tc.name}"
                    ):
                        result_text = await executor.execute(tc, wf_id)

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
            else:
                final_text = (
                    "I reached the maximum number of tool calls. "
                    "Here is what I found so far based on the tools I used."
                )

            response_type = self._determine_response_type(executor)

            viz_type = "text"
            viz_config: dict = {}
            if executor.ctx.last_query_result and response_type == "sql_result":
                try:
                    results_summary = self._summarize_results(executor.ctx.last_query_result)
                    interpretation = await self._query_builder.interpret_results(
                        question=question,
                        query=executor.ctx.last_query or "",
                        results_summary=results_summary,
                        db_type=db_type or "",
                        preferred_provider=preferred_provider,
                        model=model,
                    )
                    viz_type = interpretation.get("viz_type", "table")
                    viz_config = interpretation.get("config", {})
                    self._accum_usage(total_usage, interpretation.get("usage", {}))
                except Exception:
                    logger.debug("Visualization interpretation failed", exc_info=True)
                    viz_type = "table"

            await self._tracker.end(wf_id, "agent", "completed", f"type={response_type}")

            return AgentResponse(
                answer=final_text,
                query=executor.ctx.last_query,
                query_explanation=executor.ctx.last_query_explanation,
                results=executor.ctx.last_query_result,
                viz_type=viz_type,
                viz_config=viz_config,
                knowledge_sources=executor.ctx.rag_sources,
                workflow_id=wf_id,
                token_usage=total_usage,
                staleness_warning=staleness_warning,
                response_type=response_type,
                tool_call_log=tool_call_log,
            )

        except Exception as exc:
            logger.exception("Agent error processing question")
            await self._tracker.end(wf_id, "agent", "failed", str(exc))
            return AgentResponse(
                answer=f"An error occurred: {exc}",
                error=str(exc),
                workflow_id=wf_id,
                response_type="error",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_connection_id(
        self,
        project_id: str,
        connection_config: ConnectionConfig,
    ) -> str | None:
        """Map a runtime ConnectionConfig back to its stored Connection.id."""
        from app.models.base import async_session_factory
        from app.services.connection_service import ConnectionService

        target_key = connector_key(connection_config)
        conn_svc = ConnectionService()
        async with async_session_factory() as session:
            connections = await conn_svc.list_by_project(session, project_id)
            for c in connections:
                cfg = await conn_svc.to_config(session, c)
                if connector_key(cfg) == target_key:
                    return c.id
        return None

    async def _has_db_index(
        self,
        project_id: str,
        connection_config: ConnectionConfig | None,
    ) -> bool:
        """Check whether a database index exists for the active connection."""
        if not connection_config:
            return False
        try:
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            cid = connection_config.connection_id
            if not cid:
                cid = await self._resolve_connection_id(project_id, connection_config)
                if cid:
                    connection_config.connection_id = cid

            if not cid:
                return False

            db_index_svc = DbIndexService()
            async with async_session_factory() as session:
                return await db_index_svc.is_indexed(session, cid)
        except Exception:
            logger.debug("DB index check failed", exc_info=True)
            return False

    async def _is_db_index_stale(
        self,
        connection_config: ConnectionConfig | None,
    ) -> bool:
        """Return True if the DB index exists but is older than the configured TTL."""
        if not connection_config or not connection_config.connection_id:
            return False
        try:
            from app.config import settings as app_settings
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                return await svc.is_stale(
                    session,
                    connection_config.connection_id,
                    ttl_hours=app_settings.db_index_ttl_hours,
                )
        except Exception:
            logger.debug("DB index staleness check failed", exc_info=True)
            return False

    def _has_knowledge_base(self, project_id: str) -> bool:
        """Check whether the project's ChromaDB collection has documents."""
        try:
            collection = self._vector_store.get_or_create_collection(project_id)
            return collection.count() > 0
        except Exception:
            return False

    @staticmethod
    def _determine_response_type(executor: ToolExecutor) -> str:
        if executor.ctx.last_query_result is not None:
            return "sql_result"
        if executor.ctx.rag_sources:
            return "knowledge"
        return "text"

    @staticmethod
    def _accum_usage(total: dict[str, int], usage: dict) -> None:
        for k in total:
            total[k] += usage.get(k, 0)

    @staticmethod
    def _summarize_results(results: QueryResult, max_rows: int = 20) -> str:
        if not results.rows:
            return "No results returned."
        lines = [f"Columns: {', '.join(results.columns)}"]
        lines.append(f"Total rows: {results.row_count}")
        lines.append(f"Execution time: {results.execution_time_ms:.1f}ms")
        lines.append("")
        for row in results.rows[:max_rows]:
            lines.append(" | ".join(str(v) for v in row))
        if results.row_count > max_rows:
            lines.append(f"... and {results.row_count - max_rows} more rows")
        return "\n".join(lines)

    async def _check_staleness(self, project_id: str) -> str | None:
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
                last_sha = await git_tracker.get_last_indexed_sha(session, project_id)
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
