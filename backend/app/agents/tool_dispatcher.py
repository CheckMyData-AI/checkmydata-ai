"""ToolDispatcher — delegates orchestrator meta-tool calls to sub-agents.

Extracted from ``OrchestratorAgent`` to keep the orchestrator slim.
The dispatcher owns all ``_handle_*`` methods and tool-call deduplication.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from dataclasses import replace
from typing import Any, NoReturn

from app.agents.base import AgentContext, BaseAgent
from app.agents.errors import (
    AgentError,
    AgentFatalError,
    AgentRetryableError,
)
from app.agents.knowledge_agent import KnowledgeResult
from app.agents.mcp_source_agent import MCPSourceAgent, MCPSourceResult
from app.agents.sql_agent import SQLAgent, SQLAgentResult
from app.agents.validation import AgentResultValidator
from app.config import settings
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import ToolCall
from app.llm.errors import RETRYABLE_LLM_ERRORS
from app.services.data_processor import get_data_processor

logger = logging.getLogger(__name__)

_PREVIEW_MAX = 500

MAX_SUB_AGENT_RETRIES = settings.max_sub_agent_retries


class _ClarificationRequestError(Exception):
    """Internal signal: the orchestrator wants to ask the user a question."""

    def __init__(self, payload_json: str) -> None:
        self.payload_json = payload_json
        super().__init__(payload_json)


class ToolDispatcher:
    """Dispatches orchestrator meta-tool calls to the appropriate sub-agent."""

    _DEDUP_TOOL_NAMES = frozenset({"query_database", "search_codebase", "query_mcp_source"})

    def __init__(
        self,
        *,
        sql_agent: SQLAgent,
        knowledge_agent: BaseAgent,
        mcp_source_agent: MCPSourceAgent,
        validator: AgentResultValidator,
        tracker: WorkflowTracker,
        wf_sql_results: dict[str, list[SQLAgentResult]],
        wf_enriched: dict[str, tuple[SQLAgentResult, float]],
    ) -> None:
        self._sql = sql_agent
        self._knowledge = knowledge_agent
        self._mcp_source = mcp_source_agent
        self._validator = validator
        self._tracker = tracker
        self._wf_sql_results = wf_sql_results
        self._wf_enriched = wf_enriched

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        tc: ToolCall,
        context: AgentContext,
        wf_id: str,
        total_usage: dict[str, int],
        *,
        remaining_wall_seconds: float | None = None,
    ) -> tuple[str, Any]:
        """Dispatch a meta-tool call to the appropriate sub-agent.

        Returns ``(result_text_for_llm, typed_sub_result_or_None)``.
        """
        tool_labels = {
            "query_database": "SQL Agent",
            "search_codebase": "Knowledge Agent",
            "manage_rules": "Rules Manager",
            "query_mcp_source": "MCP Source Agent",
            "ask_user": "Asking user for clarification",
            "process_data": "Data Processing",
        }
        brief = (tc.arguments or {}).get("question", "")[:80]
        label = tool_labels.get(tc.name, tc.name)
        desc = f"Calling {label}"
        if brief:
            desc += f": {brief}"
        await self._tracker.emit(wf_id, "thinking", "in_progress", desc)

        if tc.name == "query_database":
            sql_text, sql_sub = await self._handle_query_database(
                tc,
                context,
                wf_id,
                total_usage,
                remaining_wall_seconds=remaining_wall_seconds,
            )
            self._emit_tool_result_thinking(wf_id, "SQL Agent", sql_sub)
            return sql_text, sql_sub
        if tc.name == "search_codebase":
            kb_text, kb_sub = await self._handle_search_codebase(tc, context, wf_id, total_usage)
            self._emit_tool_result_thinking(wf_id, "Knowledge Agent", kb_sub)
            return kb_text, kb_sub
        if tc.name == "manage_rules":
            rules_text = await self._handle_manage_rules(tc.arguments or {}, context, wf_id)
            return rules_text, None
        if tc.name == "list_rules":
            rules_text = await self._handle_list_rules(context, wf_id)
            return rules_text, None
        if tc.name == "query_mcp_source":
            mcp_text, mcp_sub = await self._handle_query_mcp_source(tc, context, wf_id, total_usage)
            self._emit_tool_result_thinking(wf_id, "MCP Source Agent", mcp_sub)
            return mcp_text, mcp_sub
        if tc.name == "process_data":
            pd_text = await self._handle_process_data(tc, wf_id)
            bucket = self._wf_sql_results.get(wf_id) or []
            pd_sub = bucket[-1] if bucket else None
            return pd_text, pd_sub
        if tc.name == "ask_user":
            return await self._handle_ask_user(tc, context, wf_id)
        logger.warning("Unknown meta-tool called: %s", tc.name)
        return (
            f"Error: unknown tool '{tc.name}'. Available tools: "
            "query_database, search_codebase, manage_rules, list_rules, "
            "query_mcp_source, process_data, ask_user."
        ), None

    # ------------------------------------------------------------------
    # Tool-call deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def dedup_tool_calls(
        tool_calls: list[ToolCall],
    ) -> tuple[list[ToolCall], dict[str, str]]:
        """Remove semantically duplicate data-retrieval tool calls.

        Prefers sentence-transformer embeddings via :mod:`app.services.text_similarity`
        when a model is configured; otherwise falls back to a word-set Jaccard
        comparison. This is the T13 upgrade: catches paraphrased duplicates like
        "top 5 customers by revenue" vs "five highest-revenue clients" that the
        word-overlap path misses.

        Returns ``(deduped_calls, skipped_map)`` where *skipped_map* maps
        ``tool_call.id`` to a synthetic result string for skipped calls.
        """
        from app.services import text_similarity

        skipped: dict[str, str] = {}
        kept: list[ToolCall] = []

        candidates: list[tuple[int, ToolCall, str]] = []
        for idx, tc in enumerate(tool_calls):
            if tc.name not in ToolDispatcher._DEDUP_TOOL_NAMES:
                continue
            args = tc.arguments or {}
            q = (args.get("question") or "").strip()
            if not q:
                continue
            candidates.append((idx, tc, q))

        embeddings: list[list[float]] | None = None
        if len(candidates) >= 2:
            embeddings = text_similarity.encode_batch([q for _, _, q in candidates])

        semantic_threshold = settings.tool_dedup_semantic_threshold
        word_threshold = settings.tool_dedup_word_overlap_threshold

        seen: list[tuple[int, str]] = []

        for pos, (_, tc, q) in enumerate(candidates):
            is_dup = False
            for prev_pos, prev_name in seen:
                if prev_name != tc.name:
                    continue
                if embeddings is not None:
                    sim = text_similarity.cosine_similarity(
                        embeddings[prev_pos], embeddings[pos]
                    )
                    if sim >= semantic_threshold:
                        is_dup = True
                        break
                else:
                    prev_q = candidates[prev_pos][2]
                    if text_similarity.jaccard_overlap(q, prev_q) > word_threshold:
                        is_dup = True
                        break

            if is_dup:
                skipped[tc.id] = (
                    "Duplicate request — this question is semantically equivalent "
                    "to another tool call in this batch. Results will come from "
                    "the first call."
                )
                logger.info("Dedup: skipped similar %s call: %s", tc.name, q[:80])
            else:
                seen.append((pos, tc.name))

        skipped_ids = set(skipped.keys())
        for tc in tool_calls:
            if tc.id in skipped_ids:
                continue
            kept.append(tc)

        if skipped:
            logger.info("Tool-call dedup: kept %d, skipped %d", len(kept), len(skipped))
        return kept, skipped

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_sql_result_for_llm(
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
    # Sub-agent handlers
    # ------------------------------------------------------------------

    async def _handle_query_database(
        self,
        tc: ToolCall,
        context: AgentContext,
        wf_id: str,
        total_usage: dict[str, int],
        *,
        remaining_wall_seconds: float | None = None,
    ) -> tuple[str, SQLAgentResult | None]:
        args = tc.arguments or {}
        sub_question: str = args.get("question", context.user_question)

        scoped_history = (
            context.chat_history[-settings.history_tail_messages :] if context.chat_history else []
        )
        sql_context = replace(context, chat_history=scoped_history)

        for attempt in range(MAX_SUB_AGENT_RETRIES + 1):
            try:
                _sd_sql: dict[str, Any] = {"input_preview": sub_question[:_PREVIEW_MAX]}
                async with self._tracker.step(
                    wf_id,
                    "orchestrator:sql_agent",
                    f"SQL Agent (attempt {attempt + 1})",
                    step_data=_sd_sql,
                    span_type="sub_agent",
                ):
                    sql_result = await self._sql.run(
                        sql_context,
                        question=sub_question,
                        wall_clock_remaining=remaining_wall_seconds,
                    )
                    preview_parts = []
                    if sql_result.query:
                        preview_parts.append(f"SQL: {sql_result.query[:300]}")
                    if sql_result.results:
                        preview_parts.append(
                            f"{sql_result.results.row_count} rows, "
                            f"{len(sql_result.results.columns)} cols"
                        )
                    _sd_sql["output_preview"] = "\n".join(preview_parts)[:_PREVIEW_MAX]

                _accum_usage(total_usage, sql_result.token_usage)

                vr = self._validator.validate_sql_result(sql_result)
                if not vr.passed and attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info(
                        "SQL agent validation failed (attempt %d): %s",
                        attempt + 1,
                        vr.errors,
                    )
                    continue

                return (
                    self.format_sql_result_for_llm(sql_result, vr.warnings),
                    sql_result,
                )

            except AgentRetryableError as e:
                if attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info("SQL agent retryable error (attempt %d): %s", attempt + 1, e)
                    continue
                return (
                    f"SQL query failed after retries: {e}. "
                    "Partial information may be available from other tools."
                ), None
            except AgentFatalError as e:
                return f"SQL query failed: {e}", None
            except AgentError as e:
                return f"SQL agent error: {e}", None
            except RETRYABLE_LLM_ERRORS as e:
                if attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info("SQL agent LLM error (attempt %d): %s", attempt + 1, e)
                    await asyncio.sleep(getattr(e, "retry_after_seconds", None) or 2.0)
                    continue
                return f"SQL query failed after retries: {e}", None

        return (
            "SQL query failed after maximum retries. "
            "Partial information may be available from other tools."
        ), None

    async def _handle_process_data(
        self,
        tc: ToolCall,
        wf_id: str,
    ) -> str:
        """Apply a data-processing operation to the last query result."""
        args = tc.arguments or {}
        operation: str = args.get("operation", "")

        bucket = self._wf_sql_results.get(wf_id) or []
        wf_sql = bucket[-1] if bucket else None
        if wf_sql is None or wf_sql.results is None:
            return (
                "Error: no query results available to process. "
                "Call query_database first to retrieve data, then use process_data."
            )

        qr = wf_sql.results
        if qr.error or not qr.rows:
            return "Error: last query result has no data rows to process."

        params = self.build_process_data_params(args)

        try:
            processor = get_data_processor()
            processed = processor.process(qr, operation, params)
        except ValueError as e:
            return f"Processing error: {e}"
        except Exception:
            logger.exception("Unexpected error in process_data")
            return "Error: data processing failed unexpectedly."

        updated_sql = replace(wf_sql, results=processed.query_result)
        if bucket:
            bucket[-1] = updated_sql
        else:
            self._wf_sql_results.setdefault(wf_id, []).append(updated_sql)
        self._wf_enriched[wf_id] = (updated_sql, _time.time())

        result_qr = processed.query_result
        parts: list[str] = [f"**Data Processing:** {processed.summary}", ""]
        parts.append(f"**Columns:** {', '.join(result_qr.columns)}")
        parts.append(f"**Total rows:** {result_qr.row_count}")

        if operation == "aggregate_data":
            parts.append("")
            parts.append("**Full aggregation results:**")
            header = " | ".join(result_qr.columns)
            parts.append(header)
            parts.append("-" * len(header))
            for row in result_qr.rows[:200]:
                parts.append(" | ".join(str(v) for v in row))
            if result_qr.row_count > 200:
                parts.append(f"... and {result_qr.row_count - 200} more groups")
        else:
            parts.append("")
            parts.append("**Sample rows (first 5):**")
            for row in result_qr.rows[:5]:
                parts.append(" | ".join(str(v) for v in row))
            if result_qr.row_count > 5:
                parts.append(
                    f"\nFull enriched data contains {result_qr.row_count} rows. "
                    "Use process_data with operation='aggregate_data' to compute "
                    "groupings and statistics over the complete dataset."
                )

        await self._tracker.emit(wf_id, "thinking", "completed", processed.summary[:120])
        return "\n".join(parts)

    @staticmethod
    def build_process_data_params(args: dict[str, Any]) -> dict[str, Any]:
        """Convert flat LLM tool-call arguments into ``DataProcessor`` params."""
        params: dict[str, Any] = {}
        if args.get("column"):
            params["column"] = args["column"]
        if args.get("group_by"):
            params["group_by"] = [c.strip() for c in str(args["group_by"]).split(",") if c.strip()]
        if args.get("aggregations"):
            agg_list: list[tuple[str, str]] = []
            for pair in str(args["aggregations"]).split(","):
                pair = pair.strip()
                if ":" in pair:
                    col, fn = pair.rsplit(":", 1)
                    agg_list.append((col.strip(), fn.strip()))
            if agg_list:
                params["aggregations"] = agg_list
        if args.get("sort_by"):
            params["sort_by"] = str(args["sort_by"]).strip()
        if args.get("order"):
            params["order"] = str(args["order"]).strip().lower()
        if args.get("op"):
            params["op"] = str(args["op"]).strip()
        if "value" in args and args["value"] is not None:
            params["value"] = args["value"]
        if str(args.get("exclude_empty", "")).lower() in ("true", "1", "yes"):
            params["exclude_empty"] = True
        return params

    async def _handle_search_codebase(
        self,
        tc: ToolCall,
        context: AgentContext,
        wf_id: str,
        total_usage: dict[str, int],
    ) -> tuple[str, KnowledgeResult | None]:
        args = tc.arguments or {}
        sub_question: str = args.get("question", context.user_question)

        for attempt in range(MAX_SUB_AGENT_RETRIES + 1):
            try:
                _sd_ka: dict[str, Any] = {"input_preview": sub_question[:_PREVIEW_MAX]}
                async with self._tracker.step(
                    wf_id,
                    "orchestrator:knowledge_agent",
                    f"Knowledge Agent (attempt {attempt + 1})",
                    step_data=_sd_ka,
                    span_type="sub_agent",
                ):
                    kb_ctx = replace(
                        context,
                        chat_history=(
                            context.chat_history[-settings.history_tail_messages :]
                            if context.chat_history
                            else []
                        ),
                    )
                    knowledge_result: KnowledgeResult = await self._knowledge.run(  # type: ignore[assignment]
                        kb_ctx, question=sub_question
                    )
                    src_count = len(knowledge_result.sources) if knowledge_result.sources else 0
                    _sd_ka["output_preview"] = (
                        f"{src_count} source(s)\n{(knowledge_result.answer or '')[:400]}"
                    )[:_PREVIEW_MAX]

                _accum_usage(total_usage, knowledge_result.token_usage)

                vr = self._validator.validate_knowledge_result(knowledge_result)
                if not vr.passed and attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info(
                        "Knowledge agent validation failed (attempt %d): %s",
                        attempt + 1,
                        vr.errors,
                    )
                    continue
                if not vr.passed:
                    return (
                        f"Knowledge search issue: {'; '.join(vr.errors)}",
                        knowledge_result,
                    )

                text = knowledge_result.answer
                if vr.warnings:
                    text += "\n\nNote: " + "; ".join(vr.warnings)
                return text, knowledge_result

            except AgentRetryableError as e:
                if attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info(
                        "Knowledge agent retryable error (attempt %d): %s",
                        attempt + 1,
                        e,
                    )
                    continue
                return f"Knowledge search failed after retries: {e}", None
            except (AgentFatalError, AgentError) as e:
                return f"Knowledge search failed: {e}", None
            except RETRYABLE_LLM_ERRORS as e:
                if attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info("Knowledge agent LLM error (attempt %d): %s", attempt + 1, e)
                    await asyncio.sleep(e.retry_after_seconds or 2.0)
                    continue
                return f"Knowledge search failed: {e.user_message}", None

        return "Knowledge search failed after maximum retries.", None

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

        try:
            _sd_rules: dict[str, Any] = {
                "input_preview": f"action={action} name={name} rule_id={rule_id}"[:_PREVIEW_MAX],
            }
            async with self._tracker.step(
                wf_id,
                "orchestrator:manage_rules",
                f"Managing rule ({action})",
                step_data=_sd_rules,
                span_type="tool_call",
            ):
                async with async_session_factory() as session:
                    if ctx.user_id:
                        from app.services.membership_service import ROLE_HIERARCHY

                        role = await membership_svc.get_role(session, ctx.project_id, ctx.user_id)
                        if role is None:
                            result_text = "Permission denied: not a member of this project."
                            _sd_rules["output_preview"] = result_text[:_PREVIEW_MAX]
                            return result_text
                        if ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY.get("editor", 0):
                            result_text = (
                                "Permission denied: requires at least"
                                " 'editor' role to manage rules."
                            )
                            _sd_rules["output_preview"] = result_text[:_PREVIEW_MAX]
                            return result_text
                    else:
                        result_text = "Error: user identity not available for permission check."
                        _sd_rules["output_preview"] = result_text[:_PREVIEW_MAX]
                        return result_text

                    if action == "create":
                        rule = await rule_svc.create(
                            session,
                            project_id=ctx.project_id,
                            name=name,
                            content=content,
                            format="markdown",
                        )
                        result_text = (
                            f"Rule created successfully.\n"
                            f"- **Name:** {rule.name}\n"
                            f"- **ID:** {rule.id}\n"
                            f"- **Content:** {rule.content[:200]}"
                        )
                        _sd_rules["output_preview"] = result_text[:_PREVIEW_MAX]
                        return result_text

                    if action == "update":
                        update_kwargs: dict = {}
                        if name:
                            update_kwargs["name"] = name
                        if content:
                            update_kwargs["content"] = content
                        updated_rule = await rule_svc.update(session, rule_id, **update_kwargs)
                        if not updated_rule:
                            result_text = f"Error: rule with id '{rule_id}' not found."
                            _sd_rules["output_preview"] = result_text[:_PREVIEW_MAX]
                            return result_text
                        result_text = (
                            f"Rule updated successfully.\n"
                            f"- **Name:** {updated_rule.name}\n"
                            f"- **ID:** {updated_rule.id}\n"
                            f"- **Content:** {updated_rule.content[:200]}"
                        )
                        _sd_rules["output_preview"] = result_text[:_PREVIEW_MAX]
                        return result_text

                    deleted = await rule_svc.delete(session, rule_id)
                    if not deleted:
                        result_text = f"Error: rule with id '{rule_id}' not found."
                        _sd_rules["output_preview"] = result_text[:_PREVIEW_MAX]
                        return result_text
                    result_text = f"Rule deleted successfully (id: {rule_id})."
                    _sd_rules["output_preview"] = result_text[:_PREVIEW_MAX]
                    return result_text
        except Exception as e:
            logger.exception("Rule management failed (%s)", action)
            return f"Error managing rule: {e}"

    async def _handle_list_rules(
        self,
        ctx: AgentContext,
        wf_id: str,
    ) -> str:
        """List all custom rules for the project."""
        from app.models.base import async_session_factory
        from app.services.rule_service import RuleService

        rule_svc = RuleService()
        try:
            async with async_session_factory() as session:
                rules = await rule_svc.list_all(session, project_id=ctx.project_id)
            if not rules:
                return "No custom rules found for this project."
            lines = [f"Found {len(rules)} rule(s):\n"]
            for r in rules:
                preview = (r.content or "")[:100].replace("\n", " ")
                lines.append(f"- **{r.name}** (id: `{r.id}`): {preview}")
            return "\n".join(lines)
        except Exception as e:
            logger.exception("list_rules failed")
            return f"Error listing rules: {e}"

    async def _handle_ask_user(
        self,
        tc: ToolCall,
        context: AgentContext,
        wf_id: str,
    ) -> NoReturn:
        """Raise a clarification request, interrupting the orchestrator loop."""
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

        from app.connectors.mcp_client import MCPClientAdapter
        from app.models.base import async_session_factory
        from app.services.connection_service import ConnectionService

        conn_svc = ConnectionService()

        async with async_session_factory() as session:
            if connection_id:
                conn = await conn_svc.get(session, connection_id)
                if not conn or conn.source_type != "mcp":
                    return (
                        f"Error: MCP connection '{connection_id}' not found",
                        None,
                    )
                if conn.project_id != context.project_id:
                    return (
                        "Error: MCP connection does not belong to this project",
                        None,
                    )
                config = await conn_svc.to_config(session, conn)
            else:
                connections = await conn_svc.list_by_project(
                    session,
                    context.project_id,
                )
                mcp_conns = [c for c in connections if c.source_type == "mcp"]
                if not mcp_conns:
                    return (
                        "Error: no MCP connections configured for this project",
                        None,
                    )
                conn = mcp_conns[0]
                config = await conn_svc.to_config(session, conn)

        for attempt in range(MAX_SUB_AGENT_RETRIES + 1):
            adapter = MCPClientAdapter()
            try:
                await adapter.connect(config)

                _sd_mcp: dict[str, Any] = {
                    "input_preview": f"source={conn.name}\n{sub_question[:400]}"[:_PREVIEW_MAX],
                }
                async with self._tracker.step(
                    wf_id,
                    "orchestrator:mcp_source_agent",
                    f"MCP Source Agent (attempt {attempt + 1})",
                    step_data=_sd_mcp,
                    span_type="sub_agent",
                ):
                    mcp_ctx = replace(
                        context,
                        chat_history=(
                            context.chat_history[-settings.history_tail_messages :]
                            if context.chat_history
                            else []
                        ),
                    )
                    result = await self._mcp_source.run(
                        mcp_ctx,
                        question=sub_question,
                        source_name=conn.name,
                        adapter=adapter,
                    )
                    _sd_mcp["output_preview"] = (
                        f"status={result.status}\n{(result.answer or '')[:400]}"
                    )[:_PREVIEW_MAX]

                _accum_usage(total_usage, result.token_usage)

                if result.status == "error":
                    return f"MCP source error: {result.error}", result

                vr = self._validator.validate_mcp_result(result)
                if not vr.passed and attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info(
                        "MCP agent validation failed (attempt %d): %s",
                        attempt + 1,
                        vr.errors,
                    )
                    continue
                if not vr.passed:
                    return (
                        f"MCP source issue: {'; '.join(vr.errors)}",
                        result,
                    )

                text = result.answer
                if vr.warnings:
                    text += "\n\nNote: " + "; ".join(vr.warnings)
                return text, result
            except RETRYABLE_LLM_ERRORS as e:
                if attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info("MCP agent LLM error (attempt %d): %s", attempt + 1, e)
                    await asyncio.sleep(e.retry_after_seconds or 2.0)
                    continue
                return f"MCP source query failed: {e.user_message}", None
            except Exception as e:
                if attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info("MCP source query error (attempt %d): %s", attempt + 1, e)
                    continue
                logger.exception("MCP source query failed")
                return f"MCP source query failed: {e}", None
            finally:
                try:
                    await adapter.disconnect()
                except Exception:
                    logger.warning("Failed to disconnect MCP adapter", exc_info=True)

        return "MCP source query failed after maximum retries.", None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit_tool_result_thinking(
        self,
        wf_id: str,
        label: str,
        sub_result: Any,
    ) -> None:
        """Fire-and-forget a thinking event summarising a sub-agent result."""
        detail = f"{label} finished"
        if isinstance(sub_result, SQLAgentResult):
            if sub_result.results:
                rc = sub_result.results.row_count
                cc = len(sub_result.results.columns)
                detail = f"{label}: {rc} rows, {cc} columns returned"
            elif sub_result.error:
                detail = f"{label}: error — {sub_result.error[:80]}"
        elif isinstance(sub_result, KnowledgeResult):
            n = len(sub_result.sources)
            detail = f"{label}: {n} source(s) found"
        task = asyncio.ensure_future(self._tracker.emit(wf_id, "thinking", "in_progress", detail))

        def _done(t: asyncio.Task) -> None:
            if not t.cancelled() and t.exception():
                logger.debug("Fire-and-forget thinking emit failed: %s", t.exception())

        task.add_done_callback(_done)


def _accum_usage(total: dict[str, int], usage: dict[str, Any] | None) -> None:
    """Merge *usage* counters into *total* in-place."""
    if not usage:
        return
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        total[key] = total.get(key, 0) + int(usage.get(key, 0))
