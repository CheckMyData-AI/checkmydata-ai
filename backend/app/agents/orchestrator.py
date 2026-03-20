"""OrchestratorAgent — the main conversation coordinator.

Replaces the monolithic ``ConversationalAgent``.  The orchestrator:
1. Analyses the user's question.
2. Delegates to the right sub-agent (SQL, Knowledge, or Viz).
3. Validates sub-agent results.
4. Composes the final response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentContext, BaseAgent
from app.agents.errors import (
    AgentError,
    AgentFatalError,
    AgentRetryableError,
)
from app.agents.knowledge_agent import KnowledgeAgent, KnowledgeResult
from app.agents.mcp_source_agent import MCPSourceAgent, MCPSourceResult
from app.agents.prompts import get_current_datetime_str
from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt
from app.agents.sql_agent import SQLAgent, SQLAgentResult
from app.agents.tools.orchestrator_tools import get_orchestrator_tools
from app.agents.validation import AgentResultValidator
from app.agents.viz_agent import VizAgent, VizResult
from app.config import settings
from app.connectors.base import ConnectionConfig, QueryResult, connector_key
from app.core.history_trimmer import trim_history
from app.core.types import RAGSource
from app.core.workflow_tracker import WorkflowTracker
from app.core.workflow_tracker import tracker as default_tracker
from app.knowledge.custom_rules import CustomRulesEngine
from app.knowledge.vector_store import VectorStore
from app.llm.base import LLMResponse, Message, ToolCall
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

MAX_SUB_AGENT_RETRIES = 2


class _ClarificationRequestError(Exception):
    """Internal signal: the orchestrator wants to ask the user a question."""

    def __init__(self, payload_json: str) -> None:
        self.payload_json = payload_json
        super().__init__(payload_json)


@dataclass
class AgentResponse:
    """Final response returned to the caller (chat route)."""

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


class OrchestratorAgent(BaseAgent):
    """Main conversation coordinator that delegates to specialist agents."""

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        vector_store: VectorStore | None = None,
        custom_rules: CustomRulesEngine | None = None,
        workflow_tracker: WorkflowTracker | None = None,
        sql_agent: SQLAgent | None = None,
        viz_agent: VizAgent | None = None,
        knowledge_agent: KnowledgeAgent | None = None,
        mcp_source_agent: MCPSourceAgent | None = None,
    ) -> None:
        self._llm = llm_router or LLMRouter()
        self._vector_store = vector_store or VectorStore()
        self._custom_rules = custom_rules or CustomRulesEngine()
        self._tracker = workflow_tracker or default_tracker
        self._validator = AgentResultValidator()

        self._sql = sql_agent or SQLAgent(
            llm_router=self._llm,
            vector_store=self._vector_store,
            rules_engine=self._custom_rules,
        )
        self._viz = viz_agent or VizAgent()
        self._knowledge = knowledge_agent or KnowledgeAgent(
            vector_store=self._vector_store,
        )
        self._mcp_source = mcp_source_agent or MCPSourceAgent(llm_router=self._llm)

    @property
    def name(self) -> str:
        return "orchestrator"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(  # type: ignore[override]
        self,
        context: AgentContext,
        **_kwargs: Any,
    ) -> AgentResponse:
        wf_id = context.workflow_id
        question = context.user_question

        try:
            staleness_warning = await self._check_staleness(context.project_id)

            if context.chat_history:
                from app.config import settings as app_settings

                context.chat_history = await trim_history(
                    context.chat_history,
                    max_tokens=app_settings.max_history_tokens,
                    llm_router=self._llm,
                    preferred_provider=context.preferred_provider,
                    model=context.model,
                )

            has_connection = context.connection_config is not None
            has_kb = self._has_knowledge_base(context.project_id)
            has_mcp = await self._has_mcp_sources(context.project_id)
            db_type = context.connection_config.db_type if context.connection_config else None

            table_map = ""
            if has_connection and context.connection_config:
                cid = context.connection_config.connection_id
                if not cid:
                    cid = await self._resolve_connection_id(
                        context.project_id,
                        context.connection_config,
                    )
                    if cid and context.connection_config:
                        context.connection_config.connection_id = cid
                if cid:
                    table_map = await self._build_table_map(cid)

            system_prompt = build_orchestrator_system_prompt(
                project_name=context.project_name,
                db_type=db_type,
                has_connection=has_connection,
                has_knowledge_base=has_kb,
                table_map=table_map,
                current_datetime=get_current_datetime_str(),
            )

            tools = get_orchestrator_tools(
                has_connection=has_connection,
                has_knowledge_base=has_kb,
                has_mcp_sources=has_mcp,
            )

            messages: list[Message] = [Message(role="system", content=system_prompt)]
            if context.chat_history:
                messages.extend(context.chat_history)
            messages.append(Message(role="user", content=question))

            total_usage: dict[str, int] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

            final_text = ""
            tool_call_log: list[dict] = []
            last_sql_result: SQLAgentResult | None = None
            last_viz_result: VizResult | None = None
            knowledge_sources: list[RAGSource] = []

            for iteration in range(settings.max_orchestrator_iterations):
                async with self._tracker.step(
                    wf_id,
                    "orchestrator:llm_call",
                    f"Orchestrator LLM ({iteration + 1}/{settings.max_orchestrator_iterations})",
                ):
                    llm_resp: LLMResponse = await self._llm.complete(
                        messages=messages,
                        tools=tools if tools else None,
                        preferred_provider=context.preferred_provider,
                        model=context.model,
                    )

                self.accum_usage(total_usage, llm_resp.usage)

                if not llm_resp.tool_calls:
                    final_text = llm_resp.content or ""
                    break

                messages.append(
                    Message(
                        role="assistant",
                        content=llm_resp.content or "",
                        tool_calls=llm_resp.tool_calls,
                    )
                )

                for tc in llm_resp.tool_calls:
                    result_text, sub_result = await self._handle_meta_tool(
                        tc,
                        context,
                        wf_id,
                        total_usage,
                    )

                    tool_call_log.append(
                        {
                            "tool": tc.name,
                            "arguments": tc.arguments,
                            "result_preview": result_text[:200],
                        }
                    )

                    if isinstance(sub_result, SQLAgentResult):
                        last_sql_result = sub_result
                    elif isinstance(sub_result, KnowledgeResult):
                        knowledge_sources.extend(sub_result.sources)

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

            response_type = self._determine_response_type(last_sql_result, knowledge_sources)

            viz_type = "text"
            viz_config: dict = {}
            if last_sql_result and last_sql_result.results and response_type == "sql_result":
                try:
                    async with self._tracker.step(
                        wf_id,
                        "orchestrator:viz",
                        "Choosing visualization",
                    ):
                        last_viz_result = await self._viz.run(
                            context,
                            results=last_sql_result.results,
                            question=question,
                            query=last_sql_result.query or "",
                        )
                    self.accum_usage(total_usage, last_viz_result.token_usage)
                    viz_type = last_viz_result.viz_type
                    viz_config = last_viz_result.viz_config

                    vv = self._validator.validate_viz_result(
                        last_viz_result,
                        row_count=last_sql_result.results.row_count,
                        column_count=len(last_sql_result.results.columns),
                    )
                    if vv.warnings:
                        for w in vv.warnings:
                            if "falling back to bar_chart" in w:
                                viz_type = "bar_chart"
                            elif "falling back to table" in w:
                                viz_type = "table"
                except Exception:
                    logger.debug("Visualization failed, falling back to table", exc_info=True)
                    viz_type = "table"

            await self._tracker.end(wf_id, "orchestrator", "completed", f"type={response_type}")

            return AgentResponse(
                answer=final_text,
                query=last_sql_result.query if last_sql_result else None,
                query_explanation=last_sql_result.query_explanation if last_sql_result else None,
                results=last_sql_result.results if last_sql_result else None,
                viz_type=viz_type,
                viz_config=viz_config,
                knowledge_sources=knowledge_sources,
                workflow_id=wf_id,
                token_usage=total_usage,
                staleness_warning=staleness_warning,
                response_type=response_type,
                tool_call_log=tool_call_log,
            )

        except _ClarificationRequestError as cr:
            import json as _json

            payload = _json.loads(cr.payload_json)
            await self._tracker.end(wf_id, "orchestrator", "clarification", "ask_user")
            return AgentResponse(
                answer=payload.get("question", ""),
                workflow_id=wf_id,
                response_type="clarification_request",
                viz_config=payload,
            )

        except Exception as exc:
            logger.exception("Orchestrator error processing question")
            await self._tracker.end(wf_id, "orchestrator", "failed", str(exc))
            return AgentResponse(
                answer=f"An error occurred: {exc}",
                error=str(exc),
                workflow_id=wf_id,
                response_type="error",
            )

    # ------------------------------------------------------------------
    # Meta-tool dispatch
    # ------------------------------------------------------------------

    async def _handle_meta_tool(
        self,
        tc: ToolCall,
        context: AgentContext,
        wf_id: str,
        total_usage: dict[str, int],
    ) -> tuple[str, Any]:
        """Dispatch a meta-tool call to the appropriate sub-agent.

        Returns ``(result_text_for_llm, typed_sub_result_or_None)``.
        """
        if tc.name == "query_database":
            return await self._handle_query_database(tc, context, wf_id, total_usage)
        if tc.name == "search_codebase":
            return await self._handle_search_codebase(tc, context, wf_id, total_usage)
        if tc.name == "manage_rules":
            text = await self._handle_manage_rules(tc.arguments or {}, context, wf_id)
            return text, None
        if tc.name == "query_mcp_source":
            return await self._handle_query_mcp_source(tc, context, wf_id, total_usage)
        if tc.name == "ask_user":
            return await self._handle_ask_user(tc, context, wf_id)
        logger.warning("Unknown meta-tool called: %s", tc.name)
        return (
            f"Error: unknown tool '{tc.name}'. Available tools: "
            "query_database, search_codebase, manage_rules, "
            "query_mcp_source, ask_user."
        ), None

    async def _handle_query_database(
        self,
        tc: ToolCall,
        context: AgentContext,
        wf_id: str,
        total_usage: dict[str, int],
    ) -> tuple[str, SQLAgentResult | None]:
        args = tc.arguments or {}
        sub_question: str = args.get("question", context.user_question)

        for attempt in range(MAX_SUB_AGENT_RETRIES + 1):
            try:
                async with self._tracker.step(
                    wf_id,
                    "orchestrator:sql_agent",
                    f"SQL Agent (attempt {attempt + 1})",
                ):
                    sql_result = await self._sql.run(context, question=sub_question)

                self.accum_usage(total_usage, sql_result.token_usage)

                vr = self._validator.validate_sql_result(sql_result)
                if not vr.passed and attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info(
                        "SQL agent validation failed (attempt %d): %s",
                        attempt + 1,
                        vr.errors,
                    )
                    continue

                return self._format_sql_result_for_llm(sql_result, vr.warnings), sql_result

            except AgentRetryableError as e:
                if attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info("SQL agent retryable error (attempt %d): %s", attempt + 1, e)
                    continue
                return f"SQL query failed after retries: {e}", None
            except AgentFatalError as e:
                return f"SQL query failed: {e}", None
            except AgentError as e:
                return f"SQL agent error: {e}", None

        return "SQL query failed after maximum retries.", None

    async def _handle_search_codebase(
        self,
        tc: ToolCall,
        context: AgentContext,
        wf_id: str,
        total_usage: dict[str, int],
    ) -> tuple[str, KnowledgeResult | None]:
        args = tc.arguments or {}
        sub_question: str = args.get("question", context.user_question)

        try:
            async with self._tracker.step(
                wf_id,
                "orchestrator:knowledge_agent",
                "Knowledge Agent",
            ):
                knowledge_result = await self._knowledge.run(context, question=sub_question)

            self.accum_usage(total_usage, knowledge_result.token_usage)

            vr = self._validator.validate_knowledge_result(knowledge_result)
            if not vr.passed:
                return f"Knowledge search issue: {'; '.join(vr.errors)}", knowledge_result

            text = knowledge_result.answer
            if vr.warnings:
                text += "\n\nNote: " + "; ".join(vr.warnings)
            return text, knowledge_result

        except AgentFatalError as e:
            return f"Knowledge search failed: {e}", None
        except AgentError as e:
            return f"Knowledge agent error: {e}", None

    async def _handle_manage_rules(self, args: dict, ctx: AgentContext, wf_id: str) -> str:
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

        async with self._tracker.step(
            wf_id,
            "orchestrator:manage_rules",
            f"Managing rule ({action})",
        ):
            async with async_session_factory() as session:
                if ctx.user_id:
                    role = await membership_svc.get_role(session, ctx.project_id, ctx.user_id)
                    if role != "owner":
                        return (
                            "Permission denied: only project owners can manage rules. "
                            "Ask the project owner to create this rule, or use the sidebar."
                        )
                else:
                    return "Error: user identity not available for permission check."

                if action == "create":
                    rule = await rule_svc.create(
                        session,
                        project_id=ctx.project_id,
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

    async def _handle_ask_user(
        self,
        tc: ToolCall,
        context: AgentContext,
        wf_id: str,
    ) -> tuple[str, None]:
        """Return a clarification request to the user via AgentResponse.

        The orchestrator loop is interrupted; the caller (chat route) converts
        the special return into a ``clarification_request`` message.
        """
        args = tc.arguments or {}
        question = args.get("question", "")
        question_type = args.get("question_type", "free_text")
        options_raw = args.get("options", "")
        ask_context = args.get("context", "")

        options: list[str] = []
        if options_raw:
            options = [o.strip() for o in options_raw.split(",") if o.strip()]

        import json as _json

        clarification_payload = _json.dumps(
            {
                "question": question,
                "question_type": question_type,
                "options": options,
                "context": ask_context,
            }
        )

        raise _ClarificationRequestError(clarification_payload)

    async def _handle_query_mcp_source(
        self,
        tc: ToolCall,
        context: AgentContext,
        wf_id: str,
        total_usage: dict[str, int],
    ) -> tuple[str, MCPSourceResult | None]:
        args = tc.arguments or {}
        sub_question: str = args.get("question", context.user_question)
        connection_id: str = args.get("connection_id", "")

        try:
            from app.connectors.mcp_client import MCPClientAdapter
            from app.models.base import async_session_factory
            from app.services.connection_service import ConnectionService

            conn_svc = ConnectionService()

            async with async_session_factory() as session:
                if connection_id:
                    conn = await conn_svc.get(session, connection_id)
                    if not conn or conn.source_type != "mcp":
                        return f"Error: MCP connection '{connection_id}' not found", None
                    config = await conn_svc.to_config(session, conn)
                else:
                    connections = await conn_svc.list_by_project(session, context.project_id)
                    mcp_conns = [c for c in connections if c.source_type == "mcp"]
                    if not mcp_conns:
                        return "Error: no MCP connections configured for this project", None
                    conn = mcp_conns[0]
                    config = await conn_svc.to_config(session, conn)

            adapter = MCPClientAdapter()
            try:
                await adapter.connect(config)
                self._mcp_source.set_adapter(adapter)

                async with self._tracker.step(
                    wf_id,
                    "orchestrator:mcp_source_agent",
                    "MCP Source Agent",
                ):
                    result = await self._mcp_source.run(
                        context,
                        question=sub_question,
                        source_name=conn.name,
                    )

                self.accum_usage(total_usage, result.token_usage)

                if result.status == "error":
                    return f"MCP source error: {result.error}", result

                return result.answer, result
            finally:
                try:
                    await adapter.disconnect()
                except Exception:
                    logger.warning("Failed to disconnect MCP adapter", exc_info=True)

        except Exception as e:
            logger.exception("MCP source query failed")
            return f"MCP source query failed: {e}", None

    # ------------------------------------------------------------------
    # Formatting for LLM
    # ------------------------------------------------------------------

    @staticmethod
    def _format_sql_result_for_llm(
        result: SQLAgentResult,
        warnings: list[str] | None = None,
    ) -> str:
        parts: list[str] = []

        if result.query:
            parts.append(f"**Query:** `{result.query}`")
        if result.query_explanation:
            parts.append(f"**Explanation:** {result.query_explanation}")

        if result.results:
            qr = result.results
            if qr.error:
                parts.append(f"**Error:** {qr.error}")
            elif not qr.rows:
                parts.append("Query executed successfully but returned no rows.")
            else:
                parts.append(f"**Columns:** {', '.join(qr.columns)}")
                parts.append(f"**Rows:** {qr.row_count}")
                parts.append(f"**Execution time:** {qr.execution_time_ms:.1f}ms")
                parts.append("")
                for row in qr.rows[:20]:
                    parts.append(" | ".join(str(v) for v in row))
                if qr.row_count > 20:
                    parts.append(f"... and {qr.row_count - 20} more rows")

        if warnings:
            parts.append("")
            parts.append("Warnings: " + "; ".join(warnings))

        return "\n".join(parts) if parts else "No results."

    # ------------------------------------------------------------------
    # Response type detection
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_response_type(
        sql_result: SQLAgentResult | None,
        knowledge_sources: list[RAGSource],
    ) -> str:
        if sql_result and sql_result.results is not None:
            return "sql_result"
        if knowledge_sources:
            return "knowledge"
        return "text"

    # ------------------------------------------------------------------
    # Context helpers (migrated from ConversationalAgent)
    # ------------------------------------------------------------------

    async def _has_mcp_sources(self, project_id: str) -> bool:
        """Check if the project has any MCP-type connections."""
        try:
            from app.models.base import async_session_factory
            from app.services.connection_service import ConnectionService

            conn_svc = ConnectionService()
            async with async_session_factory() as session:
                connections = await conn_svc.list_by_project(session, project_id)
                return any(c.source_type == "mcp" for c in connections)
        except Exception:
            logger.debug("Failed to check MCP sources", exc_info=True)
            return False

    def _has_knowledge_base(self, project_id: str) -> bool:
        try:
            collection = self._vector_store.get_or_create_collection(project_id)
            return collection.count() > 0
        except Exception:
            return False

    async def _build_table_map(self, connection_id: str) -> str:
        try:
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                entries = await svc.get_index(session, connection_id)
            return svc.build_table_map(entries)
        except Exception:
            logger.debug("Failed to build table map", exc_info=True)
            return ""

    async def _resolve_connection_id(
        self,
        project_id: str,
        cfg: ConnectionConfig,
    ) -> str | None:
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
