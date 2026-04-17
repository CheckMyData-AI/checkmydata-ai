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
            degraded_reason = None
            for stage in exec_result.stage_ctx.plan.stages:
                sr = exec_result.stage_ctx.get_result(stage.stage_id)
                if sr and sr.status == "degraded" and sr.degraded_reason:
                    degraded_reason = sr.degraded_reason
                    break
            response_type = "pipeline_complete_degraded" if degraded_reason else "pipeline_complete"
            return AgentResponse(
                answer=answer,
                query=last_sql_result.query if last_sql_result else None,
                results=last_sql_result.query_result if last_sql_result else None,
                workflow_id=wf_id,
                staleness_warning=staleness_warning,
                response_type=response_type,
                viz_type="table" if last_sql_result else "text",
                viz_config={"pipeline_run_id": pipeline_run_id},
                token_usage=total_usage,
                tool_call_log=tool_call_log,
                steps_used=completed,
                steps_total=n_stages,
                error=degraded_reason,
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
        elif exec_result.failed_stage:
            failed_sr = exec_result.stage_ctx.get_result(exec_result.failed_stage.stage_id)
            if failed_sr and failed_sr.error:
                fail_msg = failed_sr.error
        stage_desc = exec_result.failed_stage.description if exec_result.failed_stage else ""
        error_detail = (
            f"Stage '{stage_desc}' failed: {fail_msg}"
            if stage_desc
            else (fail_msg or "Pipeline failed")
        )
        return AgentResponse(
            answer=f"{error_detail}\n\n"
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
            error=error_detail,
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
        all_sql_results: list[SQLAgentResult] | None = None,
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

        results_to_summarize = all_sql_results if all_sql_results else (
            [sql_result] if sql_result else []
        )
        for idx, sr in enumerate(results_to_summarize, 1):
            if not sr:
                continue
            label = f"Query {idx}" if len(results_to_summarize) > 1 else "Query"
            if sr.query:
                data_parts.append(f"{label}: {sr.query}")
            if sr.query_explanation:
                data_parts.append(f"  Purpose: {sr.query_explanation}")
            if sr.results:
                r = sr.results
                data_parts.append(
                    f"  Result: {r.row_count} rows, columns: "
                    f"{', '.join(r.columns[:20])}"
                )
                if r.rows:
                    for row in r.rows[:10]:
                        data_parts.append(f"    {row}")
                    if r.row_count > 10:
                        data_parts.append(f"    ... and {r.row_count - 10} more rows")
            if sr.insights:
                for ins in sr.insights[:3]:
                    lbl = ins.get("label", "")
                    val = ins.get("value", "")
                    if lbl:
                        data_parts.append(f"  Insight: {lbl}: {val}")

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

        from app.config import settings as _app_settings
        from app.llm.router import LLMRouter

        budget_tokens = int(context_window * _app_settings.synthesis_data_token_budget_pct)

        collected = "DATA COLLECTED:\n" + "\n".join(data_parts)
        if tool_summaries:
            tool_section = "\n\nTOOL RESULTS SUMMARY:\n" + "\n".join(tool_summaries)
            if (
                LLMRouter.estimate_tokens(collected) + LLMRouter.estimate_tokens(tool_section)
                < budget_tokens
            ):
                collected += tool_section

        if LLMRouter.estimate_tokens(collected) > budget_tokens:
            char_budget = max(1, budget_tokens * 4)
            collected = collected[:char_budget] + "\n... (truncated)"

        user_question = ""
        for m in reversed(loop_messages):
            if m.role == "user" and m.content:
                user_question = m.content
                break

        user_msg = Message(
            role="user",
            content=(
                "Based on all the data collected below, provide a complete, "
                "professional analysis answering the original question. "
                "Structure your answer with clear sections and key findings. "
                "Do NOT mention step limits, partial results, or that "
                "anything was cut short — present this as a complete answer.\n\n"
                + (f"Original question: {user_question}\n\n" if user_question else "")
                + collected
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
