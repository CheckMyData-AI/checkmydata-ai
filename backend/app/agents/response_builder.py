"""ResponseBuilder — assembles final AgentResponse objects.

Extracted from ``OrchestratorAgent`` to keep the orchestrator slim.
Contains pipeline response builders, synthesis helpers, response-type
detection, and follow-up suggestion generation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.agents.sql_agent import SQLAgentResult

if TYPE_CHECKING:
    from app.agents.orchestrator import AgentResponse
from app.agents.stage_executor import _StageExecutorResult
from app.connectors.base import QueryResult
from app.core.types import RAGSource
from app.llm.base import Message

logger = logging.getLogger(__name__)


@dataclass
class SQLResultBlock:
    """One SQL result with its own visualization and metadata."""

    query: str | None = None
    query_explanation: str | None = None
    results: QueryResult | None = None
    viz_type: str = "table"
    viz_config: dict[str, Any] = field(default_factory=dict)
    insights: list[dict[str, Any]] = field(default_factory=list)


class ResponseBuilder:
    """Builds AgentResponse objects from execution results."""

    @staticmethod
    def build_pipeline_response(
        exec_result: _StageExecutorResult,
        wf_id: str,
        staleness_warning: str | None,
        pipeline_run_id: str,
    ) -> AgentResponse:
        from app.agents.orchestrator import AgentResponse

        last_sql_result = None
        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        tool_call_log: list[dict] = []
        for stage in exec_result.stage_ctx.plan.stages:
            sr = exec_result.stage_ctx.get_result(stage.stage_id)
            if not sr:
                continue
            for k in total_usage:
                total_usage[k] += sr.token_usage.get(k, 0)
            if sr.query:
                tool_call_log.append(
                    {"tool": "query_database", "stage": stage.stage_id, "query": sr.query}
                )
            if sr.query_result:
                last_sql_result = sr

        n_stages = len(exec_result.stage_ctx.plan.stages)
        completed = sum(
            1
            for s in exec_result.stage_ctx.plan.stages
            if exec_result.stage_ctx.get_result(s.stage_id)
        )

        if exec_result.status == "completed":
            answer = exec_result.final_answer or (
                "The analysis pipeline completed, but no summary was generated. "
                "Please review the data or try rephrasing your question."
            )
            return AgentResponse(
                answer=answer,
                query=last_sql_result.query if last_sql_result else None,
                results=last_sql_result.query_result if last_sql_result else None,
                workflow_id=wf_id,
                staleness_warning=staleness_warning,
                response_type="pipeline_complete",
                viz_type="table" if last_sql_result else "text",
                viz_config={"pipeline_run_id": pipeline_run_id},
                token_usage=total_usage,
                tool_call_log=tool_call_log,
                steps_used=completed,
                steps_total=n_stages,
            )

        if exec_result.status == "checkpoint":
            cp = exec_result.checkpoint_result
            preview = ""
            if cp and cp.query_result:
                preview = (
                    f"Found {cp.query_result.row_count} rows "
                    f"(columns: {', '.join(cp.query_result.columns)}). "
                )
            cp_stage = exec_result.checkpoint_stage
            stage_desc = cp_stage.description if cp_stage else ""
            return AgentResponse(
                answer=(
                    f"{preview}{stage_desc}\n\nDoes this look correct? "
                    "You can **continue**, **modify** the request, "
                    "or **retry** this stage."
                ),
                query=cp.query if cp else None,
                results=cp.query_result if cp else None,
                workflow_id=wf_id,
                staleness_warning=staleness_warning,
                response_type="stage_checkpoint",
                viz_type="table" if cp and cp.query_result else "text",
                viz_config={
                    "pipeline_run_id": pipeline_run_id,
                    "stage_id": cp_stage.stage_id if cp_stage else "",
                },
                token_usage=total_usage,
                tool_call_log=tool_call_log,
                steps_used=completed,
                steps_total=n_stages,
            )

        fail_msg = ""
        if exec_result.failed_validation:
            fail_msg = exec_result.failed_validation.error_summary
        stage_desc = exec_result.failed_stage.description if exec_result.failed_stage else ""
        return AgentResponse(
            answer=f"Stage '{stage_desc}' failed: {fail_msg}\n\n"
            "Would you like me to **retry** with a different approach, "
            "or **modify** the request?",
            workflow_id=wf_id,
            staleness_warning=staleness_warning,
            response_type="stage_failed",
            viz_config={
                "pipeline_run_id": pipeline_run_id,
                "stage_id": (exec_result.failed_stage.stage_id if exec_result.failed_stage else ""),
            },
            token_usage=total_usage,
            tool_call_log=tool_call_log,
            steps_used=completed,
            steps_total=n_stages,
        )

    @staticmethod
    def build_partial_text(
        sql_result: SQLAgentResult | None,
        knowledge_sources: list[RAGSource],
    ) -> str:
        """Build a static fallback message when the step limit is reached."""
        parts: list[str] = ["I reached the maximum number of analysis steps."]
        if sql_result and sql_result.results:
            rc = sql_result.results.row_count
            parts.append(f"I found {rc} rows of data from the database.")
        if knowledge_sources:
            parts.append(
                f"I found {len(knowledge_sources)} relevant document(s) from the knowledge base."
            )
        parts.append("Here is what I found so far based on the tools I used.")
        return " ".join(parts)

    @staticmethod
    def build_timeout_text(
        sql_result: SQLAgentResult | None,
        knowledge_sources: list[RAGSource],
    ) -> str:
        """Build a static fallback message when the wall-clock time limit is reached."""
        parts: list[str] = ["I reached the processing time limit."]
        if sql_result and sql_result.results:
            rc = sql_result.results.row_count
            parts.append(f"I found {rc} rows of data from the database.")
        if knowledge_sources:
            parts.append(
                f"I found {len(knowledge_sources)} relevant document(s) from the knowledge base."
            )
        parts.append("Here is what I found so far based on the tools I used.")
        return " ".join(parts)

    @staticmethod
    def build_synthesis_messages(
        loop_messages: list[Message],
        sql_result: SQLAgentResult | None,
        knowledge_sources: list[RAGSource],
        context_window: int,
    ) -> list[Message]:
        """Build a compact message list for a final synthesis LLM call.

        Keeps the system prompt and constructs a user message that summarises
        all collected data, staying within ~40% of the context window.
        """
        system_msg = (
            loop_messages[0]
            if loop_messages
            else Message(role="system", content="You are a helpful data assistant.")
        )

        data_parts: list[str] = []
        if sql_result and sql_result.query:
            data_parts.append(f"SQL query executed: {sql_result.query}")
        if sql_result and sql_result.results:
            r = sql_result.results
            data_parts.append(
                f"Query returned {r.row_count} rows, {len(r.columns)} columns: "
                f"{', '.join(r.columns[:20])}"
            )
            if r.rows:
                sample = r.rows[:5]
                for row in sample:
                    data_parts.append(f"  {row}")
        if knowledge_sources:
            for src in knowledge_sources[:5]:
                raw = getattr(src, "content", "") if hasattr(src, "content") else str(src)
                snippet = raw[:200]
                data_parts.append(f"Knowledge source: {snippet}")

        tool_summaries: list[str] = []
        for m in loop_messages:
            if m.role == "tool" and m.content:
                name = m.name or "tool"
                preview = m.content[:300].replace("\n", " ").strip()
                tool_summaries.append(f"[{name}] {preview}")

        budget = int(context_window * 0.4)
        chars_budget = budget * 4

        collected = "DATA COLLECTED SO FAR:\n" + "\n".join(data_parts)
        if tool_summaries:
            tool_section = "\n\nTOOL RESULTS SUMMARY:\n" + "\n".join(tool_summaries)
            if len(collected) + len(tool_section) < chars_budget:
                collected += tool_section

        if len(collected) > chars_budget:
            collected = collected[:chars_budget] + "\n... (truncated)"

        user_msg = Message(
            role="user",
            content=(
                "The analysis reached its step limit before completing. "
                "Based on all the data collected above, please provide a "
                "comprehensive answer to the original question. Summarize "
                "the findings clearly and note if the analysis is incomplete.\n\n" + collected
            ),
        )

        return [system_msg, user_msg]

    @staticmethod
    def determine_response_type(
        sql_result: SQLAgentResult | None,
        knowledge_sources: list[RAGSource],
        has_mcp_result: bool = False,
    ) -> str:
        if sql_result and sql_result.results is not None:
            return "sql_result"
        if knowledge_sources:
            return "knowledge"
        if has_mcp_result:
            return "mcp_source"
        return "text"

    @staticmethod
    def generate_followups(
        sql_result: SQLAgentResult | None,
        response_type: str,
    ) -> list[str]:
        """Generate follow-up suggestions based on the SQL result."""
        followups: list[str] = []
        if response_type == "sql_result" and sql_result and sql_result.results and sql_result.query:
            try:
                from app.services.suggestion_engine import SuggestionEngine

                followups = SuggestionEngine.generate_followups(
                    query=sql_result.query,
                    columns=list(sql_result.results.columns),
                    row_count=sql_result.results.row_count,
                )
            except Exception:
                logger.debug("Failed to generate follow-up suggestions", exc_info=True)
        return followups
