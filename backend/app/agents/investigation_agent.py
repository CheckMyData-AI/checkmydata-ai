"""InvestigationAgent — diagnoses 'Wrong Data' reports.

Called by the orchestrator when a user clicks the 'Wrong Data' button.
Systematically investigates query result errors through 4 phases:
1. collect_info  — gather user complaint details (handled by UI)
2. investigate   — run diagnostic queries, check formats/filters
3. present_fix   — show corrected query + results
4. update_memory — create learnings, notes, benchmarks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.prompts.investigation_prompt import INVESTIGATION_SYSTEM_PROMPT
from app.agents.tools.investigation_tools import get_investigation_tools
from app.config import settings
from app.connectors.registry import get_connector
from app.llm.base import LLMResponse, Message, ToolCall
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)


@dataclass
class InvestigationResult(AgentResult):
    corrected_query: str | None = None
    corrected_result: dict | None = None
    root_cause: str | None = None
    root_cause_category: str | None = None
    investigation_log: list[dict] = field(default_factory=list)


class InvestigationAgent(BaseAgent):
    """Specialized agent for diagnosing data accuracy issues."""

    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self._llm = llm_router or LLMRouter()
        self._investigation_context: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "investigation"

    async def run(
        self,
        context: AgentContext,
        *,
        investigation_id: str = "",
        original_query: str = "",
        original_result_summary: str = "{}",
        user_complaint_type: str = "other",
        user_complaint_detail: str = "",
        user_expected_value: str = "",
        problematic_column: str = "",
    ) -> InvestigationResult:
        self._investigation_context = {
            "investigation_id": investigation_id,
            "original_query": original_query,
            "original_result_summary": original_result_summary,
            "user_complaint_type": user_complaint_type,
            "user_complaint_detail": user_complaint_detail,
            "user_expected_value": user_expected_value,
            "problematic_column": problematic_column,
        }

        user_message = (
            f"The user flagged a query result as incorrect.\n"
            f"Complaint type: {user_complaint_type}\n"
            f"Detail: {user_complaint_detail or 'not specified'}\n"
            f"Expected value: {user_expected_value or 'not specified'}\n"
            f"Problematic column: {problematic_column or 'not specified'}\n\n"
            f"Original query:\n```sql\n{original_query}\n```\n\n"
            f"Original result summary: {original_result_summary[:500]}\n\n"
            "Please investigate and find the root cause."
        )

        tools = get_investigation_tools()
        messages: list[Message] = [
            Message(role="system", content=INVESTIGATION_SYSTEM_PROMPT),
            Message(role="user", content=user_message),
        ]

        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        result = InvestigationResult()

        provider = context.sql_provider or context.preferred_provider
        model = context.sql_model or context.model

        max_iters = getattr(settings, "max_investigation_iterations", 12)

        for iteration in range(max_iters):
            async with context.tracker.step(
                context.workflow_id,
                "investigation:llm_call",
                f"Investigation LLM ({iteration + 1}/{max_iters})",
            ):
                llm_resp: LLMResponse = await self._llm.complete(
                    messages=messages,
                    tools=tools,
                    preferred_provider=provider,
                    model=model,
                )

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
                result_text = await self._dispatch_tool(tc, context)
                result.investigation_log.append(
                    {
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "result_preview": result_text[:300],
                    }
                )
                if tc.name == "record_investigation_finding" and tc.arguments:
                    result.corrected_query = (
                        tc.arguments.get("corrected_query") or result.corrected_query
                    )
                    result.root_cause = tc.arguments.get("root_cause") or result.root_cause
                    result.root_cause_category = (
                        tc.arguments.get("root_cause_category") or result.root_cause_category
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
        result.status = "success" if result.corrected_query else "no_fix_found"
        return result

    async def _dispatch_tool(self, tc: ToolCall, ctx: AgentContext) -> str:
        handlers = {
            "get_original_context": self._handle_get_original_context,
            "run_diagnostic_query": self._handle_run_diagnostic_query,
            "compare_results": self._handle_compare_results,
            "check_column_formats": self._handle_check_column_formats,
            "get_related_learnings": self._handle_get_related_learnings,
            "record_investigation_finding": self._handle_record_finding,
        }
        handler = handlers.get(tc.name)
        if handler is None:
            return f"Error: unknown tool '{tc.name}'"
        try:
            return await handler(tc.arguments or {}, ctx)
        except Exception as exc:
            logger.exception("Investigation tool %s failed", tc.name)
            return f"Error: {exc}"

    async def _handle_get_original_context(self, _args: dict, ctx: AgentContext) -> str:
        ic = self._investigation_context
        parts = [
            f"Original query: {ic.get('original_query', 'N/A')}",
            f"Result summary: {ic.get('original_result_summary', '{}')[:1000]}",
            f"Complaint: {ic.get('user_complaint_type', 'N/A')}"
            f" — {ic.get('user_complaint_detail', 'N/A')}",
            f"Expected value: {ic.get('user_expected_value', 'N/A')}",
            f"Problematic column: {ic.get('problematic_column', 'N/A')}",
        ]
        return "\n".join(parts)

    async def _handle_run_diagnostic_query(self, args: dict, ctx: AgentContext) -> str:
        query: str = args.get("query", "")
        hypothesis: str = args.get("hypothesis", "")
        cfg = ctx.connection_config
        if cfg is None:
            return "Error: no database connection."

        connector = get_connector(cfg.db_type, ssh_exec_mode=cfg.ssh_exec_mode)
        await connector.connect(cfg)
        try:
            result = await connector.execute_query(query)
            if result.error:
                return f"Query error: {result.error}"
            lines = [f"Hypothesis: {hypothesis}", f"Columns: {', '.join(result.columns)}"]
            for row in result.rows[:15]:
                lines.append(" | ".join(str(v) for v in row))
            if result.row_count > 15:
                lines.append(f"... {result.row_count - 15} more rows")
            return "\n".join(lines)
        finally:
            await connector.disconnect()

    async def _handle_compare_results(self, args: dict, _ctx: AgentContext) -> str:
        original = args.get("original_summary", "")
        new = args.get("new_summary", "")
        return f"ORIGINAL:\n{original}\n\nCORRECTED:\n{new}"

    async def _handle_check_column_formats(self, args: dict, ctx: AgentContext) -> str:
        table_name: str = args.get("table_name", "")
        column_name: str = args.get("column_name", "")
        cfg = ctx.connection_config
        if cfg is None:
            return "Error: no database connection."

        query = (
            f"SELECT {column_name}, COUNT(*) as cnt "
            f"FROM {table_name} "
            f"GROUP BY {column_name} "
            f"ORDER BY cnt DESC LIMIT 20"
        )
        connector = get_connector(cfg.db_type, ssh_exec_mode=cfg.ssh_exec_mode)
        await connector.connect(cfg)
        try:
            result = await connector.execute_query(query)
            if result.error:
                return f"Error: {result.error}"
            lines = [f"Column {table_name}.{column_name} — distinct values:"]
            for row in result.rows[:20]:
                lines.append(f"  {row[0]} (count: {row[1]})")
            return "\n".join(lines)
        finally:
            await connector.disconnect()

    async def _handle_get_related_learnings(self, args: dict, ctx: AgentContext) -> str:
        table_name: str = args.get("table_name", "")
        cfg = ctx.connection_config
        if cfg is None or not cfg.connection_id:
            return "No learnings available."

        from app.models.base import async_session_factory
        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()
        async with async_session_factory() as session:
            learnings = await svc.get_learnings_for_table(session, cfg.connection_id, table_name)

        if not learnings:
            return f"No learnings found for table '{table_name}'."

        lines = [f"Learnings for '{table_name}' ({len(learnings)}):"]
        for lrn in learnings:
            conf = int(lrn.confidence * 100)
            lines.append(f"- [{lrn.category}] {lrn.lesson} ({conf}% conf, id={lrn.id})")
        return "\n".join(lines)

    async def _handle_record_finding(self, args: dict, ctx: AgentContext) -> str:
        corrected_query: str = args.get("corrected_query", "")
        root_cause: str = args.get("root_cause", "")
        root_cause_category: str = args.get("root_cause_category", "other")
        investigation_id = self._investigation_context.get("investigation_id", "")

        if not investigation_id:
            return "Error: no investigation_id in context."

        from app.models.base import async_session_factory
        from app.services.investigation_service import InvestigationService

        svc = InvestigationService()
        async with async_session_factory() as session:
            inv = await svc.record_finding(
                session,
                investigation_id=investigation_id,
                corrected_query=corrected_query,
                root_cause=root_cause,
                root_cause_category=root_cause_category,
            )
            await session.commit()

        if not inv:
            return "Error: investigation not found."

        return (
            f"Finding recorded.\n"
            f"- Root cause: {root_cause}\n"
            f"- Category: {root_cause_category}\n"
            f"- Corrected query saved."
        )
