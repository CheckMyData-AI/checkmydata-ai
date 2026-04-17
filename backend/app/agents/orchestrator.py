"""OrchestratorAgent — the main conversation coordinator.

Replaces the monolithic ``ConversationalAgent``.  The orchestrator:
1. Analyses the user's question.
2. Delegates to the right sub-agent (SQL, Knowledge, or Viz).
3. Validates sub-agent results.
4. Composes the final response.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any

from app.agents.adaptive_planner import AdaptivePlanner
from app.agents.base import AgentContext, BaseAgent
from app.agents.context_loader import ContextLoader
from app.agents.data_gate import DataGate
from app.agents.errors import (
    AgentFatalError,
)
from app.agents.knowledge_agent import KnowledgeAgent, KnowledgeResult
from app.agents.mcp_source_agent import MCPSourceAgent, MCPSourceResult
from app.agents.pipeline_learning import PipelineLearningExtractor
from app.agents.prompts import get_current_datetime_str
from app.agents.prompts.orchestrator_prompt import (
    build_direct_response_prompt,
    build_orchestrator_system_prompt,
)
from app.agents.response_builder import (
    ResponseBuilder,
    SQLResultBlock,
)
from app.agents.router import RouteResult, route_request
from app.agents.sql_agent import SQLAgent, SQLAgentResult
from app.agents.stage_context import ExecutionPlan, StageContext
from app.agents.stage_executor import StageExecutor, _StageExecutorResult
from app.agents.stage_validator import StageValidator
from app.agents.tool_dispatcher import (
    ToolDispatcher,
    _ClarificationRequestError,
)
from app.agents.tools.orchestrator_tools import get_orchestrator_tools
from app.agents.validation import AgentResultValidator
from app.agents.viz_agent import VizAgent
from app.config import settings
from app.connectors.base import QueryResult
from app.core.context_budget import ContextBudgetManager
from app.core.history_trimmer import (
    estimate_messages_tokens,
    should_wrap_up,
    trim_history,
    trim_loop_messages,
)
from app.core.types import RAGSource
from app.core.workflow_tracker import WorkflowTracker
from app.core.workflow_tracker import tracker as default_tracker
from app.knowledge.custom_rules import CustomRulesEngine
from app.knowledge.vector_store import VectorStore
from app.llm.base import LLMResponse, Message, ToolCall
from app.llm.errors import (
    RETRYABLE_LLM_ERRORS,
    LLMAllProvidersFailedError,
    LLMError,
    LLMTokenLimitError,
)
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

_LLM_CALL_MAX_RETRIES = 2
_LLM_CALL_BASE_BACKOFF = 3.0

MAX_SUB_AGENT_RETRIES = settings.max_sub_agent_retries


PROMPT_VERSION = "v2.1"

_PREVIEW_MAX = 500


def _messages_preview(messages: list[Message], max_len: int = _PREVIEW_MAX) -> str:
    """Build a truncated summary of the last user/assistant messages for trace previews."""
    parts: list[str] = []
    for m in reversed(messages):
        if m.role in ("user", "assistant"):
            snippet = m.content[:200] if m.content else ""
            parts.append(f"[{m.role}] {snippet}")
            if len("\n".join(parts)) > max_len:
                break
    return "\n".join(reversed(parts))[:max_len]


def _llm_step_data(
    messages: list[Message],
    resp: LLMResponse,
) -> dict[str, Any]:
    """Build step_data dict for an LLM call span."""
    data: dict[str, Any] = {
        "input_preview": _messages_preview(messages),
        "output_preview": (resp.content or "")[:_PREVIEW_MAX],
    }
    if resp.model:
        data["model"] = resp.model
    usage = resp.usage or {}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if k in usage:
            data[k] = usage[k]
    return data


def _is_token_limit_error(exc: BaseException) -> bool:
    """Return True if *exc* (or its __cause__) is a token limit error."""
    if isinstance(exc, LLMTokenLimitError):
        return True
    cause = getattr(exc, "__cause__", None)
    return isinstance(cause, LLMTokenLimitError)


@dataclass
class AgentResponse:
    """Final response returned to the caller (chat route)."""

    answer: str = ""
    query: str | None = None
    query_explanation: str | None = None
    results: QueryResult | None = None
    viz_type: str = "text"
    viz_config: dict[str, Any] = field(default_factory=dict)
    knowledge_sources: list[RAGSource] = field(default_factory=list)
    error: str | None = None
    workflow_id: str | None = None
    token_usage: dict[str, int] = field(default_factory=dict)
    llm_provider: str = ""
    llm_model: str = ""
    staleness_warning: str | None = None
    response_type: str = "text"
    tool_call_log: list[dict[str, Any]] = field(default_factory=list)
    prompt_version: str = PROMPT_VERSION
    suggested_followups: list[str] = field(default_factory=list)
    insights: list[dict[str, Any]] = field(default_factory=list)
    context_usage_pct: int = 0
    steps_used: int = 0
    steps_total: int = 0
    continuation_context: str | None = None
    clarification_data: dict[str, Any] | None = None
    sql_results: list[SQLResultBlock] = field(default_factory=list)


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
        self._wf_sql_results: dict[str, list[SQLAgentResult]] = {}
        self._wf_sql_lock = asyncio.Lock()
        self._wf_enriched: dict[str, tuple[SQLAgentResult, float]] = {}
        self._parallel_tool_sem = asyncio.Semaphore(settings.max_parallel_tool_calls)
        self._mcp_cache: dict[str, tuple[bool, float]] = {}
        self._MCP_CACHE_TTL = 60.0
        self._dispatcher = ToolDispatcher(
            sql_agent=self._sql,
            knowledge_agent=self._knowledge,
            mcp_source_agent=self._mcp_source,
            validator=self._validator,
            tracker=self._tracker,
            wf_sql_results=self._wf_sql_results,
            wf_enriched=self._wf_enriched,
        )
        self._ctx_loader = ContextLoader(
            vector_store=self._vector_store,
            tracker=self._tracker,
            mcp_cache=self._mcp_cache,
            mcp_cache_ttl=self._MCP_CACHE_TTL,
        )

    @property
    def name(self) -> str:
        return "orchestrator"

    def _cleanup_stale_results(self, stale_seconds: float) -> None:
        """Remove per-workflow SQL caches older than *stale_seconds*."""
        import time as _time

        now = _time.time()
        stale_wf_ids = [
            wid for wid, (_, ts) in self._wf_enriched.items() if (now - ts) > stale_seconds
        ]
        for wid in stale_wf_ids:
            self._wf_enriched.pop(wid, None)
            self._wf_sql_results.pop(wid, None)

    _ORCH_RULES_MAX_CHARS = 2000

    async def _load_custom_rules_text(self, project_id: str) -> str:
        """Load custom rules for injection into the orchestrator system prompt."""
        try:
            rules_dir = f"{settings.custom_rules_dir}/{project_id}"
            file_rules = self._custom_rules.load_rules(project_rules_dir=rules_dir)
            db_rules = await self._custom_rules.load_db_rules(project_id=project_id)
            text = self._custom_rules.rules_to_context(file_rules + db_rules)
            if not text:
                return ""
            if len(text) > self._ORCH_RULES_MAX_CHARS:
                text = text[: self._ORCH_RULES_MAX_CHARS] + "\n... (truncated)"
            return text
        except Exception:
            logger.debug("_load_custom_rules_text failed", exc_info=True)
            return ""

    @staticmethod
    async def _emit_plan_summary(
        tracker: WorkflowTracker,
        wf_id: str,
        *,
        table_map: str,
        custom_rules: str,
        recent_learnings: str,
    ) -> None:
        """Emit a plan_summary event so the frontend can display context."""
        import re as _re

        tables = _re.findall(r"(\w+)\(", table_map) if table_map else []
        rule_names: list[str] = []
        if custom_rules:
            rule_names = _re.findall(r"###\s+(.+?)(?:\s+\(id:|\n)", custom_rules)
            if not rule_names:
                rule_names = ["(custom rules loaded)"]
        learning_subjects: list[str] = []
        if recent_learnings:
            for line in recent_learnings.splitlines():
                line = line.strip().lstrip("- ")
                if line.startswith("["):
                    parts = line.split("]", 1)
                    if len(parts) > 1:
                        subj = parts[1].strip().split(":")[0].strip()
                        if subj:
                            learning_subjects.append(subj)
            learning_subjects = learning_subjects[:10]

        strategy = "pipeline" if len(tables) > 3 else "single_query"

        await tracker.emit(
            wf_id,
            "plan_summary",
            "started",
            extra={
                "tables": tables[:20],
                "strategy": strategy,
                "rules_applied": rule_names[:10],
                "learnings_applied": learning_subjects,
            },
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(  # type: ignore[override]
        self,
        context: AgentContext,
        **_kwargs: Any,
    ) -> AgentResponse:
        import time as _time

        wf_id = context.workflow_id

        stale_seconds = 300
        enriched = self._wf_enriched.get(wf_id)
        if enriched and (_time.time() - enriched[1]) < stale_seconds:
            self._wf_sql_results[wf_id] = [enriched[0]]
        else:
            self._wf_sql_results.pop(wf_id, None)
            self._wf_enriched.pop(wf_id, None)

        self._cleanup_stale_results(stale_seconds)

        try:
            is_continuation = context.extra.get("pipeline_action") == "continue_analysis"
            if is_continuation:
                context = self._apply_continuation_context(context)

            resume_info = await self._check_pipeline_resume(context)
            if resume_info:
                return await self._resume_pipeline(resume_info, context)

            has_connection = context.connection_config is not None
            db_type = context.connection_config.db_type if context.connection_config else None

            # Lightweight capability checks (KB is local, MCP needs DB)
            has_kb = self._ctx_loader.has_knowledge_base(context.project_id)
            has_mcp = await self._ctx_loader.has_mcp_sources(context.project_id, wf_id)

            # --- LLM-driven routing ---
            await self._tracker.emit(wf_id, "thinking", "in_progress", "Routing request…")

            if is_continuation or context.extra.get("_skip_complexity"):
                route_result = RouteResult(
                    route="explore",
                    complexity="moderate",
                    approach="Continuation — resuming previous analysis with all tools.",
                    estimated_queries=2,
                    needs_multiple_data_sources=False,
                )
            else:
                route_result = await route_request(
                    context.user_question,
                    self._llm,
                    has_connection=has_connection,
                    has_knowledge_base=has_kb,
                    has_mcp_sources=has_mcp,
                    chat_history=context.chat_history,
                    preferred_provider=context.preferred_provider,
                    model=context.model,
                )
            logger.info(
                "Router: route=%s complexity=%s (wf=%s)",
                route_result.route,
                route_result.complexity,
                wf_id,
            )
            await self._tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                f"Route: {route_result.route} ({route_result.complexity})",
            )

            # --- Direct response: no tools needed ---
            if route_result.is_direct:
                return await self._run_direct_response(
                    context,
                    wf_id,
                    has_connection,
                    has_kb,
                    has_mcp,
                )

            # --- Complex pipeline for multi-stage analysis ---
            if route_result.use_complex_pipeline and has_connection:
                table_map = await self._load_table_map(context, wf_id)
                return await self._run_complex_pipeline(
                    context,
                    wf_id,
                    table_map,
                    db_type,
                    staleness_warning=None,
                )

            # --- Unified tool loop for everything else ---
            return await self._run_unified_agent(
                context,
                wf_id,
                has_connection,
                db_type,
                has_kb,
                has_mcp,
                route_result=route_result,
            )

        except _ClarificationRequestError as cr:
            import json as _json

            payload = _json.loads(cr.payload_json)
            try:
                await self._tracker.end(wf_id, "orchestrator", "clarification", "ask_user")
            except Exception:
                logger.warning("Failed to emit pipeline_end for clarification", exc_info=True)
            return AgentResponse(
                answer=payload.get("question", ""),
                workflow_id=wf_id,
                response_type="clarification_request",
                clarification_data=payload,
            )

        except LLMError as llm_exc:
            if _is_token_limit_error(llm_exc):
                cause = llm_exc.__cause__ if llm_exc.__cause__ else llm_exc
                user_msg = getattr(cause, "user_message", str(cause))
            else:
                user_msg = llm_exc.user_message
            logger.error(
                "Orchestrator LLM error [%s]: %s",
                type(llm_exc).__name__,
                llm_exc,
            )
            try:
                await self._tracker.end(wf_id, "orchestrator", "failed", type(llm_exc).__name__)
            except Exception:
                logger.warning("Failed to emit pipeline_end for LLM error", exc_info=True)
            return AgentResponse(
                answer=user_msg,
                error=type(llm_exc).__name__,
                workflow_id=wf_id,
                response_type="error",
            )

        except Exception as exc:
            logger.exception("Orchestrator error processing question")
            try:
                await self._tracker.end(wf_id, "orchestrator", "failed", str(exc))
            except Exception:
                logger.warning("Failed to emit pipeline_end for error", exc_info=True)
            user_msg = self._friendly_error(exc)
            return AgentResponse(
                answer=user_msg,
                error=str(exc),
                workflow_id=wf_id,
                response_type="error",
            )

    # ------------------------------------------------------------------
    # Execution paths
    # ------------------------------------------------------------------

    async def _run_direct_response(
        self,
        context: AgentContext,
        wf_id: str,
        has_connection: bool,
        has_kb: bool,
        has_mcp: bool,
    ) -> AgentResponse:
        """Handle conversational/meta questions with a single LLM call, no tools."""
        await self._tracker.emit(wf_id, "thinking", "in_progress", "Responding directly…")

        system_prompt = build_direct_response_prompt(
            project_name=context.project_name,
            has_connection=has_connection,
            has_knowledge_base=has_kb,
            has_mcp_sources=has_mcp,
        )

        messages: list[Message] = [Message(role="system", content=system_prompt)]
        if context.chat_history:
            for m in context.chat_history[-settings.history_tail_messages :]:
                messages.append(m)
        messages.append(Message(role="user", content=context.user_question))

        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        _sd: dict[str, Any] = {}
        async with self._tracker.step(
            wf_id,
            "orchestrator:llm_call",
            "Direct response LLM",
            step_data=_sd,
        ):
            llm_resp = await self._llm_call_with_retry(
                messages=messages,
                tools=None,
                preferred_provider=context.preferred_provider,
                model=context.model,
                wf_id=wf_id,
            )
            _sd.update(_llm_step_data(messages, llm_resp))

        self.accum_usage(total_usage, llm_resp.usage)
        final_text = llm_resp.content or ""
        await self._stream_tokens(wf_id, final_text)

        await self._tracker.end(wf_id, "orchestrator", "completed", "type=text")
        return AgentResponse(
            answer=final_text,
            workflow_id=wf_id,
            token_usage=total_usage,
            llm_provider=llm_resp.provider or "",
            llm_model=llm_resp.model or "",
            response_type="text",
            steps_used=1,
            steps_total=1,
        )

    async def _load_table_map(self, context: AgentContext, wf_id: str) -> str:
        """Load the table map for the connected database, if available."""
        if not context.connection_config:
            return ""
        cid = context.connection_config.connection_id
        if not cid:
            cid = await self._ctx_loader.resolve_connection_id(
                context.project_id,
                context.connection_config,
            )
            if cid and context.connection_config:
                context.connection_config.connection_id = cid
        if cid:
            return await self._ctx_loader.build_table_map(cid, wf_id)
        return ""

    async def _run_unified_agent(
        self,
        context: AgentContext,
        wf_id: str,
        has_connection: bool,
        db_type: str | None,
        has_kb: bool,
        has_mcp: bool,
        *,
        route_result: RouteResult,
    ) -> AgentResponse:
        """Unified agent loop — all tools available, LLM decides usage."""
        if context.chat_history:
            from app.config import settings as app_settings

            trimmed = await trim_history(
                context.chat_history,
                max_tokens=app_settings.max_history_tokens,
                llm_router=self._llm,
                preferred_provider=context.preferred_provider,
                model=context.model,
                summary_model=app_settings.history_summary_model or None,
            )
            context = replace(context, chat_history=trimmed)

        cfg_for_staleness = context.connection_config
        connection_id_for_staleness = cfg_for_staleness.connection_id if cfg_for_staleness else None
        staleness_warning = (
            await self._ctx_loader.check_staleness(
                context.project_id,
                wf_id,
                connection_id=connection_id_for_staleness,
            )
            if (has_kb or connection_id_for_staleness)
            else None
        )

        table_map = ""
        if has_connection:
            table_map = await self._load_table_map(context, wf_id)

        project_overview = await self._ctx_loader.load_project_overview(context.project_id)
        recent_learnings = await self._ctx_loader.load_recent_learnings(context)
        active_insights = await self._ctx_loader.load_relevant_insights(context.project_id)
        if active_insights:
            recent_learnings = (
                (recent_learnings + "\n\n" + active_insights)
                if recent_learnings
                else active_insights
            )
        if has_kb and context.user_question:
            relevant_knowledge = await self._ctx_loader.load_relevant_knowledge(
                context.project_id, context.user_question
            )
            if relevant_knowledge:
                recent_learnings = (
                    (recent_learnings + "\n\n" + relevant_knowledge)
                    if recent_learnings
                    else relevant_knowledge
                )
        custom_rules_text = await self._load_custom_rules_text(context.project_id)

        tools = get_orchestrator_tools(
            has_connection=has_connection,
            has_knowledge_base=has_kb,
            has_mcp_sources=has_mcp,
        )

        return await self._run_tool_loop(
            context,
            wf_id,
            has_connection=has_connection,
            db_type=db_type,
            has_kb=has_kb,
            has_mcp=has_mcp,
            table_map=table_map,
            project_overview=project_overview,
            recent_learnings=recent_learnings,
            custom_rules=custom_rules_text,
            tools=tools,
            staleness_warning=staleness_warning,
            route_result=route_result,
        )

    # ------------------------------------------------------------------
    # Shared tool-calling loop (used by data_query, knowledge_query,
    # mcp_query, and full_pipeline paths)
    # ------------------------------------------------------------------

    async def _run_tool_loop(
        self,
        context: AgentContext,
        wf_id: str,
        *,
        has_connection: bool,
        db_type: str | None,
        has_kb: bool,
        has_mcp: bool,
        table_map: str,
        project_overview: str | None,
        recent_learnings: str | None,
        custom_rules: str = "",
        tools: list,
        staleness_warning: str | None = None,
        route_result: RouteResult | None = None,
    ) -> AgentResponse:
        """Run the orchestrator tool-calling loop with the given context and tools."""
        if table_map and not context.table_map:
            context = replace(context, table_map=table_map)
        question = context.user_question

        context_window = self._llm.get_context_window(context.model)
        budget_mgr = ContextBudgetManager(
            total_budget=min(settings.max_context_tokens, context_window),
        )
        base_prompt = build_orchestrator_system_prompt(
            project_name=context.project_name,
            db_type=db_type,
            has_connection=has_connection,
            has_knowledge_base=has_kb,
            has_mcp_sources=has_mcp,
            table_map="",
            current_datetime=get_current_datetime_str(),
            project_overview="",
            recent_learnings="",
            custom_rules="",
        )
        allocation = budget_mgr.allocate(
            system_prompt=base_prompt,
            schema_text=table_map,
            rules_text=custom_rules,
            learnings_text=recent_learnings or "",
            overview_text=project_overview or "",
        )

        system_prompt = build_orchestrator_system_prompt(
            project_name=context.project_name,
            db_type=db_type,
            has_connection=has_connection,
            has_knowledge_base=has_kb,
            has_mcp_sources=has_mcp,
            table_map=allocation.schema_text,
            current_datetime=get_current_datetime_str(),
            project_overview=allocation.overview_text,
            recent_learnings=allocation.learnings_text,
            custom_rules=allocation.rules_text,
        )

        if route_result and route_result.approach:
            system_prompt += (
                f"\n\nROUTER ANALYSIS (complexity={route_result.complexity}):\n"
                f"{route_result.approach}"
            )

        await self._emit_plan_summary(
            context.tracker,
            wf_id,
            table_map=allocation.schema_text,
            custom_rules=allocation.rules_text,
            recent_learnings=allocation.learnings_text,
        )

        messages: list[Message] = [Message(role="system", content=system_prompt)]
        continuation_summary = context.extra.get("_continuation_summary")
        if context.chat_history:
            messages.extend(context.chat_history)
            if continuation_summary:
                messages.append(
                    Message(
                        role="system",
                        content=(
                            "--- END OF CONVERSATION HISTORY ---\n"
                            "The messages above are past exchanges. The LAST assistant message "
                            "was a partial result cut short by the step limit. The next system "
                            "message contains the full context of work already done."
                        ),
                    )
                )
            else:
                messages.append(
                    Message(
                        role="system",
                        content=(
                            "--- END OF CONVERSATION HISTORY ---\n"
                            "The messages above are COMPLETED past exchanges for reference only. "
                            "Do NOT re-execute any queries or tools from the history. "
                            "Focus EXCLUSIVELY on the new user message below."
                        ),
                    )
                )
        if continuation_summary:
            messages.append(Message(role="system", content=continuation_summary))
        messages.append(Message(role="user", content=question))

        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        final_text = ""
        tool_call_log: list[dict] = []
        last_sql_result: SQLAgentResult | None = None
        all_sql_results: list[SQLAgentResult] = []
        knowledge_sources: list[RAGSource] = []
        has_mcp_result = False
        used_provider = ""
        used_model = ""
        query_db_count = 0

        loop_budget = min(settings.max_context_tokens, context_window)
        history_budget = allocation.chat_history_tokens or None
        synthesis_phase = False
        step_limit_hit = False
        wall_clock_timeout_hit = False
        wall_clock_start = time.monotonic()
        wall_clock_limit = settings.agent_wall_clock_timeout_seconds

        is_continuation = bool(context.extra.get("_continuation_summary"))
        if is_continuation:
            wall_clock_limit = int(wall_clock_limit * 1.5)

        max_iter = context.max_orchestrator_steps or settings.max_orchestrator_iterations
        if is_continuation:
            max_iter = int(max_iter * 1.5)

        emergency_pct = settings.agent_emergency_synthesis_pct
        iteration = 0
        for iteration in range(max_iter):
            messages, did_trim = trim_loop_messages(
                messages, loop_budget, history_budget_tokens=history_budget
            )
            if did_trim:
                await self._tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    "Compacting earlier analysis to free context space…",
                )

            elapsed_wall = time.monotonic() - wall_clock_start

            step_pct = (iteration + 1) / max_iter
            time_pct = elapsed_wall / wall_clock_limit if wall_clock_limit else 1.0
            budget_pct = max(step_pct, time_pct)

            if not synthesis_phase and (
                budget_pct >= emergency_pct or should_wrap_up(messages, loop_budget)
            ):
                synthesis_phase = True
                reason = (
                    "emergency budget limit" if budget_pct >= emergency_pct else "context budget"
                )
                messages.append(
                    Message(
                        role="system",
                        content=(
                            "EMERGENCY: You have used most of your analysis budget "
                            f"({reason}, {budget_pct:.0%} used). You MUST compose "
                            "your complete final answer NOW using the data you have "
                            "gathered so far. Do NOT make any more tool calls."
                        ),
                    )
                )
                logger.info(
                    "Emergency synthesis (%s, step %d/%d, %.1fs/%.0fs, wf=%s)",
                    reason,
                    iteration + 1,
                    max_iter,
                    elapsed_wall,
                    wall_clock_limit,
                    wf_id,
                )
            elif not synthesis_phase and iteration > 0:
                budget_status = (
                    f"[Budget: step {iteration + 1}/{max_iter}, "
                    f"time {int(elapsed_wall)}s/{int(wall_clock_limit)}s, "
                    f"queries: {query_db_count}]"
                )
                messages.append(Message(role="system", content=budget_status))

            pct = int(estimate_messages_tokens(messages) / max(loop_budget, 1) * 100)
            if pct > 50:
                logger.debug("Context usage: ~%d%% of model limit (wf=%s)", pct, wf_id)

            phase_label = "synthesis" if synthesis_phase else f"step {iteration + 1}/{max_iter}"
            await self._tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                f"Analyzing request ({phase_label})…",
            )
            effective_tools = None if synthesis_phase else (tools if tools else None)
            try:
                _sd: dict[str, Any] = {}
                async with self._tracker.step(
                    wf_id,
                    "orchestrator:llm_call",
                    f"Orchestrator LLM ({phase_label})",
                    step_data=_sd,
                ):
                    llm_resp = await self._llm_call_with_retry(
                        messages=messages,
                        tools=effective_tools,
                        preferred_provider=context.preferred_provider,
                        model=context.model,
                        wf_id=wf_id,
                    )
                    _sd.update(_llm_step_data(messages, llm_resp))
            except (LLMAllProvidersFailedError, LLMTokenLimitError) as exc:
                if _is_token_limit_error(exc):
                    logger.info(
                        "Hit context limit (wf=%s), retrying with compressed context",
                        wf_id,
                    )
                    aggressive = int(loop_budget * 0.6)
                    messages, _ = trim_loop_messages(
                        messages, aggressive, history_budget_tokens=history_budget
                    )
                    try:
                        _sd_r: dict[str, Any] = {}
                        async with self._tracker.step(
                            wf_id,
                            "orchestrator:llm_call",
                            "Orchestrator LLM (recovery)",
                            step_data=_sd_r,
                        ):
                            llm_resp = await self._llm_call_with_retry(
                                messages=messages,
                                tools=effective_tools,
                                preferred_provider=context.preferred_provider,
                                model=context.model,
                                wf_id=wf_id,
                            )
                            _sd_r.update(_llm_step_data(messages, llm_resp))
                    except LLMError:
                        partial = [
                            "Note: This answer is based on partial analysis. "
                            "The conversation context was too large to "
                            "analyze everything."
                        ]
                        if last_sql_result and last_sql_result.results:
                            rc = last_sql_result.results.row_count
                            partial.append(f"I found {rc} rows from the database.")
                        if knowledge_sources:
                            partial.append(
                                f"I found {len(knowledge_sources)} relevant document(s)."
                            )
                        partial.append(
                            "Consider starting a new conversation for further questions."
                        )
                        final_text = " ".join(partial)
                        break
                else:
                    raise

            if not used_provider:
                used_provider = llm_resp.provider or ""
                used_model = llm_resp.model or ""
            self.accum_usage(total_usage, llm_resp.usage)

            if not llm_resp.tool_calls:
                await self._tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    "Composing final answer…",
                )
                final_text = llm_resp.content or ""
                if not final_text.strip() and all_sql_results:
                    final_text = ResponseBuilder.build_partial_text(
                        last_sql_result, knowledge_sources
                    )
                await self._stream_tokens(wf_id, final_text)
                break

            hard_elapsed = time.monotonic() - wall_clock_start
            if hard_elapsed > wall_clock_limit * 1.2:
                logger.warning(
                    "Hard wall-clock cutoff (%.1fs > %.1fs, wf=%s), "
                    "LLM returned tool calls despite wrap-up — forcing break",
                    hard_elapsed,
                    wall_clock_limit * 1.2,
                    wf_id,
                )
                final_text = llm_resp.content or ResponseBuilder.build_timeout_text(
                    last_sql_result, knowledge_sources
                )
                wall_clock_timeout_hit = True
                await self._stream_tokens(wf_id, final_text)
                break

            tool_names = ", ".join(tc.name for tc in llm_resp.tool_calls)
            thinking_detail = f"Decided to use: {tool_names}"
            if llm_resp.content:
                snippet = llm_resp.content[:120].replace("\n", " ")
                thinking_detail += f" — {snippet}"
            await self._tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                thinking_detail,
            )

            messages.append(
                Message(
                    role="assistant",
                    content=llm_resp.content or "",
                    tool_calls=llm_resp.tool_calls,
                )
            )

            active_calls, skipped_map = ToolDispatcher.dedup_tool_calls(llm_resp.tool_calls)

            has_process_data = any(tc.name == "process_data" for tc in active_calls)

            _dispatch_wall = max(0.0, wall_clock_limit - (time.monotonic() - wall_clock_start))

            if len(active_calls) > 1 and not has_process_data:

                async def _throttled_meta_tool(
                    _tc: ToolCall,
                ) -> tuple[str, Any]:
                    async with self._parallel_tool_sem:
                        return await self._dispatcher.dispatch(
                            _tc,
                            context,
                            wf_id,
                            total_usage,
                            remaining_wall_seconds=_dispatch_wall,
                        )

                gather_results = await asyncio.gather(
                    *(_throttled_meta_tool(tc) for tc in active_calls),
                    return_exceptions=True,
                )
                executed_pairs: dict[str, tuple[str, Any]] = {}
                for i, res in enumerate(gather_results):
                    tc_id = active_calls[i].id
                    if isinstance(res, _ClarificationRequestError):
                        raise res
                    if isinstance(res, Exception):
                        from app.agents.errors import (
                            AgentError,
                            AgentFatalError,
                            AgentRetryableError,
                        )

                        if isinstance(res, LLMError):
                            err_msg = res.user_message
                        elif isinstance(res, (AgentRetryableError, AgentFatalError, AgentError)):
                            err_msg = str(res) or type(res).__name__
                        else:
                            err_msg = f"{type(res).__name__}: {res}"

                        logger.warning(
                            "Parallel tool call %s failed (%s): %s",
                            active_calls[i].name,
                            type(res).__name__,
                            res,
                            exc_info=res,
                        )
                        await self._tracker.emit(
                            wf_id,
                            "tool_call:error",
                            "error",
                            f"{active_calls[i].name} failed: {err_msg}",
                            tool=active_calls[i].name,
                            error=err_msg,
                            error_type=type(res).__name__,
                        )
                        executed_pairs[tc_id] = (
                            f"Tool '{active_calls[i].name}' failed: {err_msg}",
                            None,
                        )
                    else:
                        executed_pairs[tc_id] = res  # type: ignore[assignment]
            else:
                executed_pairs = {}
                for single_tc in active_calls:
                    executed_pairs[single_tc.id] = await self._dispatcher.dispatch(
                        single_tc,
                        context,
                        wf_id,
                        total_usage,
                        remaining_wall_seconds=_dispatch_wall,
                    )

            tool_pairs: list[tuple[str, Any]] = []
            for tc in llm_resp.tool_calls:
                if tc.id in skipped_map:
                    tool_pairs.append((skipped_map[tc.id], None))
                else:
                    tool_pairs.append(executed_pairs[tc.id])

            for tc, (result_text, sub_result) in zip(llm_resp.tool_calls, tool_pairs):
                tool_call_log.append(
                    {
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "result_preview": result_text[:200],
                    }
                )

                if tc.name == "query_database":
                    query_db_count += 1
                if isinstance(sub_result, SQLAgentResult):
                    last_sql_result = sub_result
                    bucket = self._wf_sql_results.setdefault(wf_id, [])
                    if tc.name == "process_data" and bucket:
                        bucket[-1] = sub_result
                    else:
                        bucket.append(sub_result)
                    if tc.name == "process_data" and all_sql_results:
                        all_sql_results[-1] = sub_result
                    else:
                        all_sql_results.append(sub_result)
                elif isinstance(sub_result, KnowledgeResult):
                    knowledge_sources.extend(sub_result.sources)
                elif isinstance(sub_result, MCPSourceResult):
                    has_mcp_result = True

                messages.append(
                    Message(
                        role="tool",
                        content=result_text,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )
        else:
            await self._tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                "Reached step limit, synthesizing collected data…",
            )
            if settings.orchestrator_final_synthesis:
                synthesis_messages = ResponseBuilder.build_synthesis_messages(
                    messages,
                    last_sql_result,
                    knowledge_sources,
                    loop_budget,
                    all_sql_results=all_sql_results,
                )
                try:
                    _sd_s: dict[str, Any] = {}
                    async with self._tracker.step(
                        wf_id,
                        "orchestrator:llm_call",
                        "Orchestrator LLM (final synthesis)",
                        step_data=_sd_s,
                    ):
                        synth_resp = await self._llm_call_with_retry(
                            messages=synthesis_messages,
                            tools=None,
                            preferred_provider=context.preferred_provider,
                            model=context.model,
                            wf_id=wf_id,
                        )
                        _sd_s.update(_llm_step_data(synthesis_messages, synth_resp))
                    self.accum_usage(total_usage, synth_resp.usage)
                    final_text = synth_resp.content or ""
                    if not final_text.strip() and all_sql_results:
                        final_text = ResponseBuilder.build_partial_text(
                            last_sql_result, knowledge_sources
                        )
                    await self._stream_tokens(wf_id, final_text)
                except LLMError:
                    logger.warning(
                        "Final synthesis LLM call failed (wf=%s), using partial text",
                        wf_id,
                        exc_info=True,
                    )
                    final_text = ResponseBuilder.build_partial_text(
                        last_sql_result, knowledge_sources
                    )
                    await self._stream_tokens(wf_id, final_text)
            else:
                final_text = ResponseBuilder.build_partial_text(last_sql_result, knowledge_sources)
                await self._stream_tokens(wf_id, final_text)
            step_limit_hit = True

        if step_limit_hit or wall_clock_timeout_hit:
            has_meaningful_data = (
                last_sql_result is not None
                and last_sql_result.results is not None
                and last_sql_result.results.rows
            )
            answer_addresses_question = await self._validate_partial_answer(
                final_text,
                question=question,
                sql_results=all_sql_results,
                preferred_provider=context.preferred_provider,
                model=context.model,
                wf_id=wf_id,
            )
            if has_meaningful_data and answer_addresses_question:
                response_type = ResponseBuilder.determine_response_type(
                    last_sql_result, knowledge_sources, has_mcp_result
                )
            else:
                response_type = "step_limit_reached"
        else:
            response_type = ResponseBuilder.determine_response_type(
                last_sql_result, knowledge_sources, has_mcp_result
            )

        viz_type = "text"
        viz_config: dict = {}
        sql_result_blocks: list[SQLResultBlock] = []
        viable_sql_raw = [sr for sr in all_sql_results if sr.results and sr.results.rows]
        seen_queries: dict[str, int] = {}
        viable_sql: list[SQLAgentResult] = []
        for sr in viable_sql_raw:
            key = (sr.query or "").strip().lower()
            if key in seen_queries:
                prev_idx = seen_queries[key]
                prev = viable_sql[prev_idx]
                if sr.results and prev.results and sr.results.row_count > prev.results.row_count:
                    viable_sql[prev_idx] = sr
            else:
                seen_queries[key] = len(viable_sql)
                viable_sql.append(sr)
        if viable_sql and response_type in ("sql_result", "step_limit_reached"):
            viz_ctx = replace(
                context,
                chat_history=(
                    context.chat_history[-settings.history_tail_messages :]
                    if context.chat_history
                    else []
                ),
            )
            n_viz = len(viable_sql)
            label = f"Choosing visualization{'s' if n_viz > 1 else ''}…"
            await self._tracker.emit(wf_id, "thinking", "in_progress", label)
            for sr_idx, sr in enumerate(viable_sql):
                sr_viz_type = "table"
                sr_viz_config: dict[str, Any] = {}
                try:
                    _sd_viz: dict[str, Any] = {"input_preview": question[:_PREVIEW_MAX]}
                    step_label = (
                        f"Choosing visualization ({sr_idx + 1}/{n_viz})"
                        if n_viz > 1
                        else "Choosing visualization"
                    )
                    assert sr.results is not None  # guaranteed by viable_sql filter
                    async with self._tracker.step(
                        wf_id,
                        "orchestrator:viz",
                        step_label,
                        step_data=_sd_viz,
                    ):
                        viz_result = await asyncio.wait_for(
                            self._viz.run(
                                viz_ctx,
                                results=sr.results,
                                question=question,
                                query=sr.query or "",
                            ),
                            timeout=settings.viz_timeout_seconds,
                        )
                        _sd_viz["output_preview"] = f"type={viz_result.viz_type}"
                    self.accum_usage(total_usage, viz_result.token_usage)
                    sr_viz_type = viz_result.viz_type
                    sr_viz_config = viz_result.viz_config

                    vv = self._validator.validate_viz_result(
                        viz_result,
                        row_count=sr.results.row_count,
                        column_count=len(sr.results.columns),
                    )
                    if vv.fallback_viz_type:
                        sr_viz_type = vv.fallback_viz_type
                except (Exception, asyncio.CancelledError):
                    logger.debug(
                        "Visualization %d/%d failed, falling back to table",
                        sr_idx + 1,
                        n_viz,
                        exc_info=True,
                    )
                    sr_viz_type = "table"

                sql_result_blocks.append(
                    SQLResultBlock(
                        query=sr.query,
                        query_explanation=sr.query_explanation,
                        results=sr.results,
                        viz_type=sr_viz_type,
                        viz_config=sr_viz_config,
                        insights=sr.insights,
                    )
                )
            if sql_result_blocks:
                viz_type = sql_result_blocks[-1].viz_type
                viz_config = sql_result_blocks[-1].viz_config
                await self._tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    f"Selected {viz_type} visualization",
                )

        await self._tracker.end(wf_id, "orchestrator", "completed", f"type={response_type}")

        total_wall_clock = time.monotonic() - wall_clock_start
        error_types = []
        for sr in all_sql_results:
            if sr.error:
                error_types.append(sr.error[:60])
        logger.info(
            "request_summary wf=%s steps=%d/%d wall_clock=%.1fs sql_calls=%d response=%s errors=%s",
            wf_id,
            iteration + 1,
            max_iter,
            total_wall_clock,
            len(all_sql_results),
            response_type,
            error_types or "none",
        )
        try:
            from app.core.metrics import RequestMetrics, get_metrics_collector

            get_metrics_collector().record_request(
                RequestMetrics(
                    route="unified",
                    complexity=str(context.extra.get("complexity") or "unknown"),
                    response_type=response_type,
                    sql_calls=len(all_sql_results),
                    iterations=iteration + 1,
                    wall_clock_seconds=total_wall_clock,
                    error=bool(error_types),
                )
            )
        except Exception:
            logger.debug("metrics collector failed (non-critical)", exc_info=True)

        followups: list[str] = []
        if (
            response_type == "sql_result"
            and last_sql_result
            and last_sql_result.results
            and last_sql_result.query
        ):
            try:
                from app.services.suggestion_engine import SuggestionEngine

                followups = SuggestionEngine.generate_followups(
                    query=last_sql_result.query,
                    columns=list(last_sql_result.results.columns),
                    row_count=last_sql_result.results.row_count,
                )
            except Exception:
                logger.debug("Failed to generate follow-up suggestions", exc_info=True)

        final_pct = int(estimate_messages_tokens(messages) / max(loop_budget, 1) * 100)

        continuation_ctx: str | None = None
        if step_limit_hit or wall_clock_timeout_hit:
            import json as _cont_json

            sql_summaries = []
            for sr in all_sql_results:
                if not sr.query:
                    continue
                summary: dict[str, Any] = {
                    "query": sr.query,
                    "row_count": sr.results.row_count if sr.results else 0,
                    "columns": sr.results.columns if sr.results else [],
                }
                if sr.results and sr.results.rows:
                    summary["sample_rows"] = sr.results.rows[:3]
                if sr.query_explanation:
                    summary["explanation"] = sr.query_explanation
                if sr.insights:
                    summary["insights"] = sr.insights[:3]
                sql_summaries.append(summary)

            continuation_ctx = _cont_json.dumps(
                {
                    "tool_call_log": [
                        {
                            "tool": tc["tool"],
                            "arguments": tc.get("arguments", ""),
                            "result_preview": tc.get("result_preview", "")[:500],
                        }
                        for tc in tool_call_log
                    ],
                    "sql_queries": sql_summaries,
                    "partial_answer": final_text[:2000],
                    "knowledge_source_count": len(knowledge_sources),
                    "steps_used": iteration + 1,
                    "steps_total": max_iter,
                },
                default=str,
            )

        return AgentResponse(
            answer=final_text,
            query=last_sql_result.query if last_sql_result else None,
            query_explanation=(last_sql_result.query_explanation if last_sql_result else None),
            results=last_sql_result.results if last_sql_result else None,
            viz_type=viz_type,
            viz_config=viz_config,
            knowledge_sources=knowledge_sources,
            workflow_id=wf_id,
            token_usage=total_usage,
            llm_provider=used_provider,
            llm_model=used_model,
            staleness_warning=staleness_warning,
            response_type=response_type,
            tool_call_log=tool_call_log,
            insights=last_sql_result.insights if last_sql_result else [],
            suggested_followups=followups,
            context_usage_pct=final_pct,
            steps_used=iteration + 1,
            steps_total=max_iter,
            continuation_context=continuation_ctx,
            sql_results=sql_result_blocks,
        )

    # ------------------------------------------------------------------
    # Multi-stage pipeline
    # ------------------------------------------------------------------

    async def _run_complex_pipeline(
        self,
        context: AgentContext,
        wf_id: str,
        table_map: str,
        db_type: str | None,
        staleness_warning: str | None,
    ) -> AgentResponse:
        """Plan and execute a multi-stage pipeline for complex queries.

        Includes a replan loop: when a stage fails and is replan-eligible,
        the ``AdaptivePlanner`` generates a new plan that avoids the failed
        approach and reuses completed results.
        """
        await self._tracker.emit(
            wf_id,
            "thinking",
            "in_progress",
            "Complex query detected, creating execution plan…",
        )
        adaptive = AdaptivePlanner(self._llm)

        recent_learnings = await self._ctx_loader.load_recent_learnings(context)
        active_insights = await self._ctx_loader.load_relevant_insights(context.project_id)
        if active_insights:
            recent_learnings = (
                (recent_learnings + "\n\n" + active_insights)
                if recent_learnings
                else active_insights
            )

        _sd_plan: dict[str, Any] = {"input_preview": context.user_question[:_PREVIEW_MAX]}
        async with self._tracker.step(
            wf_id,
            "orchestrator:planning",
            "Creating execution plan",
            step_data=_sd_plan,
        ):
            plan = await adaptive._llm_plan(
                context.user_question,
                table_map=table_map,
                db_type=db_type,
                preferred_provider=context.preferred_provider,
                model=context.model,
                project_overview=context.extra.get("project_overview"),
                current_datetime=get_current_datetime_str(),
                recent_learnings=recent_learnings,
            )
            if plan:
                _sd_plan["output_preview"] = f"{len(plan.stages)} stage(s)"

        if not plan:
            await self._tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                "Planning failed, falling back to standard approach…",
            )
            logger.warning("Planner failed — falling back to flat loop")
            return await self.run(
                AgentContext(
                    project_id=context.project_id,
                    connection_config=context.connection_config,
                    user_question=context.user_question,
                    chat_history=context.chat_history,
                    llm_router=context.llm_router,
                    tracker=context.tracker,
                    workflow_id=wf_id,
                    user_id=context.user_id,
                    preferred_provider=context.preferred_provider,
                    model=context.model,
                    sql_provider=context.sql_provider,
                    sql_model=context.sql_model,
                    project_name=context.project_name,
                    extra={**context.extra, "_skip_complexity": True},
                ),
            )

        n_stages = len(plan.stages)
        await self._tracker.emit(
            wf_id,
            "thinking",
            "in_progress",
            f"Plan created: {n_stages} stages",
        )

        try:
            pipeline_run = await self._create_pipeline_run(context, plan)
        except Exception as exc:
            logger.exception("Failed to create pipeline run record")
            raise AgentFatalError("Pipeline initialisation failed") from exc

        data_gate = DataGate()
        executor = StageExecutor(
            sql_agent=self._sql,
            knowledge_agent=self._knowledge,
            llm_router=self._llm,
            tracker=self._tracker,
            validator=StageValidator(),
            data_gate=data_gate,
            mcp_source_agent=self._mcp_source,
        )

        pipeline_ctx = replace(
            context,
            chat_history=(
                context.chat_history[-settings.history_tail_messages :]
                if context.chat_history
                else []
            ),
        )
        replan_history: list[dict[str, Any]] = []

        try:
            stage_ctx = StageContext(plan=plan, pipeline_run_id=pipeline_run.id)
            exec_result = await executor.execute(plan, pipeline_ctx, stage_ctx=stage_ctx)

            replan_count = 0
            max_replans = settings.max_pipeline_replans
            while (
                exec_result.status == "stage_failed"
                and exec_result.replan_eligible
                and replan_count < max_replans
            ):
                failed = exec_result.failed_stage
                if not failed:
                    break

                error_msg = (
                    exec_result.failed_validation.error_summary
                    if exec_result.failed_validation
                    else "unknown error"
                )
                if exec_result.data_gate_outcome and exec_result.data_gate_outcome.errors:
                    error_msg += " | DataGate: " + "; ".join(exec_result.data_gate_outcome.errors)
                    if exec_result.data_gate_outcome.suggestions:
                        error_msg += " Suggestions: " + "; ".join(
                            exec_result.data_gate_outcome.suggestions
                        )

                replan_count += 1
                replan_history.append(
                    {
                        "attempt": replan_count,
                        "failed_stage": failed.stage_id,
                        "error": error_msg,
                    }
                )

                await self._tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    f"Stage '{failed.stage_id}' failed after retries — replanning "
                    f"(attempt {replan_count}/{max_replans})…",
                )

                completed = exec_result.stage_ctx.results
                new_plan = await adaptive.replan(
                    context.user_question,
                    completed_stages=completed,
                    failed_stage=failed,
                    error=error_msg,
                    table_map=table_map,
                    db_type=db_type,
                    preferred_provider=context.preferred_provider,
                    model=context.model,
                    replan_history=replan_history,
                )
                if not new_plan:
                    logger.warning("Replanning returned no plan — giving up")
                    await self._tracker.emit(
                        wf_id,
                        "thinking",
                        "in_progress",
                        "Replanning failed — returning partial results.",
                    )
                    break

                await self._tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    f"New plan: {len(new_plan.stages)} stages",
                )

                new_stage_ctx = StageContext(
                    plan=new_plan,
                    pipeline_run_id=pipeline_run.id,
                )
                for sid, sr in completed.items():
                    if sr.status == "success":
                        new_stage_ctx.set_result(sid, sr)

                exec_result = await executor.execute(
                    new_plan,
                    pipeline_ctx,
                    stage_ctx=new_stage_ctx,
                )

            await self._persist_stage_results(pipeline_run.id, exec_result.stage_ctx)
        except Exception:
            logger.exception("Pipeline execution failed (run_id=%s)", pipeline_run.id)
            raise

        if replan_history:
            logger.info(
                "Pipeline completed after %d replan(s): %s (run_id=%s)",
                len(replan_history),
                [h["failed_stage"] for h in replan_history],
                pipeline_run.id,
            )

        conn_id = context.connection_config.connection_id if context.connection_config else None
        if conn_id:
            await self._extract_pipeline_learnings(
                conn_id,
                exec_result=exec_result,
                replan_history=replan_history,
            )

        await self._tracker.end(wf_id, "orchestrator", "completed", "complex_pipeline")
        try:
            from app.core.metrics import RequestMetrics, get_metrics_collector

            stage_ctx = exec_result.stage_ctx
            error_count = sum(1 for sr in stage_ctx.results.values() if sr.status == "error")
            get_metrics_collector().record_request(
                RequestMetrics(
                    route="complex_pipeline",
                    complexity=str(context.extra.get("complexity") or "complex"),
                    response_type=("pipeline_failed" if error_count else "pipeline_success"),
                    replan_count=len(replan_history),
                    sql_calls=sum(1 for s in stage_ctx.plan.stages if s.tool == "query_database"),
                    iterations=len(stage_ctx.plan.stages),
                    error=bool(error_count),
                )
            )
        except Exception:
            logger.debug("metrics collector failed (non-critical)", exc_info=True)
        return ResponseBuilder.build_pipeline_response(
            exec_result,
            wf_id,
            staleness_warning,
            pipeline_run.id,
        )

    @staticmethod
    def _apply_continuation_context(context: AgentContext) -> AgentContext:
        """Augment the user question with continuation context from a previous step-limited run.

        Parses the rich ``continuation_context`` JSON and stores a structured
        ``_continuation_summary`` in ``extra`` so the tool loop can inject it
        as a system message.  The user question is kept clean — only the
        original request text.
        """
        import json as _cj

        raw = context.extra.get("continuation_context", "")
        parsed: dict = {}
        if raw:
            try:
                parsed = _cj.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                parsed = {}

        summary_parts: list[str] = []
        summary_parts.append(
            "CONTINUATION: The previous analysis run was cut short by the step/time limit. "
            "Below is a summary of work already completed. Do NOT re-execute these queries — "
            "use the results below and continue the analysis from where it stopped."
        )

        sql_queries = parsed.get("sql_queries", [])
        if sql_queries:
            summary_parts.append("\n## Previously executed SQL queries and results:")
            for i, sq in enumerate(sql_queries, 1):
                q = sq.get("query", "")
                cols = sq.get("columns", [])
                rc = sq.get("row_count", 0)
                explanation = sq.get("explanation", "")
                sample = sq.get("sample_rows", [])
                insights = sq.get("insights", [])
                summary_parts.append(f"\n### Query {i}:")
                if explanation:
                    summary_parts.append(f"Purpose: {explanation}")
                summary_parts.append(f"```sql\n{q}\n```")
                summary_parts.append(f"Result: {rc} rows, columns: {', '.join(cols)}")
                if sample:
                    preview_lines = []
                    for row in sample[:3]:
                        preview_lines.append(str(row))
                    summary_parts.append("Sample data:\n" + "\n".join(preview_lines))
                if insights:
                    for ins in insights[:2]:
                        label = ins.get("label", "")
                        val = ins.get("value", "")
                        if label:
                            summary_parts.append(f"Insight: {label}: {val}")

        tool_log = parsed.get("tool_call_log", [])
        non_sql_tools = [t for t in tool_log if t.get("tool") != "query_database"]
        if non_sql_tools:
            summary_parts.append("\n## Other tools already called:")
            for t in non_sql_tools:
                preview = t.get("result_preview", "")[:300]
                summary_parts.append(f"- {t.get('tool', '?')}: {preview}")

        partial = parsed.get("partial_answer", "")
        if partial:
            summary_parts.append(f"\n## Partial answer composed so far:\n{partial}")

        steps_used = parsed.get("steps_used", 0)
        steps_total = parsed.get("steps_total", 0)
        if steps_used:
            summary_parts.append(
                f"\nPrevious run used {steps_used}/{steps_total} steps before stopping."
            )

        continuation_summary = "\n".join(summary_parts)

        new_extra = {k: v for k, v in context.extra.items() if k != "pipeline_action"}
        new_extra["_continuation_summary"] = continuation_summary

        return replace(context, extra=new_extra)

    async def _check_pipeline_resume(self, context: AgentContext) -> dict | None:
        """Detect if the user message is a pipeline action (continue/modify/retry)."""
        action = context.extra.get("pipeline_action")
        run_id = context.extra.get("pipeline_run_id")
        if not action or not run_id:
            return None
        return {
            "action": action,
            "pipeline_run_id": run_id,
            "modification": context.extra.get("modification", ""),
        }

    async def _resume_pipeline(self, resume_info: dict, context: AgentContext) -> AgentResponse:
        """Resume a pipeline from a checkpoint or failed stage."""
        import json as _json

        from sqlalchemy import select

        from app.models.base import async_session_factory
        from app.models.pipeline_run import PipelineRun

        run_id = resume_info["pipeline_run_id"]
        action = resume_info["action"]
        modification = resume_info.get("modification", "")
        wf_id = context.workflow_id

        async with async_session_factory() as session:
            db_result = await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            pipeline_run = db_result.scalar_one_or_none()
            if not pipeline_run:
                await self._tracker.end(wf_id, "orchestrator", "failed", "Pipeline not found")
                return AgentResponse(
                    answer="Could not find the pipeline to resume. Please try your question again.",
                    workflow_id=wf_id,
                    response_type="error",
                )

            try:
                plan = ExecutionPlan.from_json(pipeline_run.plan_json)
                stage_results_raw = _json.loads(pipeline_run.stage_results_json)
                user_feedback = _json.loads(pipeline_run.user_feedback_json)
            except (_json.JSONDecodeError, TypeError, KeyError) as exc:
                logger.warning("Failed to parse pipeline state for run %s: %s", run_id[:8], exc)
                await self._tracker.end(wf_id, "orchestrator", "failed", "Corrupted pipeline state")
                return AgentResponse(
                    answer=(
                        "The saved analysis state is corrupted and cannot be resumed. "
                        "Please start a new query."
                    ),
                    workflow_id=wf_id,
                    response_type="error",
                )
            current_idx = pipeline_run.current_stage_idx

        cur_stage_id = plan.stages[current_idx].stage_id if current_idx < len(plan.stages) else ""
        if modification:
            user_feedback.append(
                {
                    "stage_id": cur_stage_id,
                    "feedback_text": modification,
                    "action": action,
                }
            )
        elif action == "continue":
            user_feedback.append(
                {
                    "stage_id": cur_stage_id,
                    "feedback_text": "",
                    "action": "continue",
                }
            )

        stage_ctx = StageContext.from_persistence(
            plan=plan,
            stage_results_raw=stage_results_raw,
            user_feedback=user_feedback,
            current_stage_idx=current_idx,
            pipeline_run_id=run_id,
        )

        resume_from = current_idx + 1 if action == "continue" else current_idx

        try:
            executor = StageExecutor(
                sql_agent=self._sql,
                knowledge_agent=self._knowledge,
                llm_router=self._llm,
                tracker=self._tracker,
                validator=StageValidator(),
                data_gate=DataGate(),
                mcp_source_agent=self._mcp_source,
            )
            resume_ctx = replace(
                context,
                chat_history=(
                    context.chat_history[-settings.history_tail_messages :]
                    if context.chat_history
                    else []
                ),
            )
            exec_result = await executor.execute(
                plan, resume_ctx, resume_from=resume_from, stage_ctx=stage_ctx
            )

            await self._persist_stage_results(run_id, exec_result.stage_ctx, user_feedback)
        except Exception:
            logger.exception("Pipeline resume failed (run_id=%s)", run_id)
            raise

        return ResponseBuilder.build_pipeline_response(exec_result, wf_id, None, run_id)

    async def _create_pipeline_run(
        self,
        context: AgentContext,
        plan: ExecutionPlan,
    ) -> Any:
        """Create a PipelineRun DB record."""
        from app.models.base import async_session_factory
        from app.models.pipeline_run import PipelineRun

        run = PipelineRun(
            session_id=context.extra.get("session_id", ""),
            user_question=context.user_question,
            plan_json=plan.to_json(),
            status="executing",
        )

        try:
            async with async_session_factory() as session:
                session.add(run)
                await session.commit()
                await session.refresh(run)
        except Exception:
            logger.exception("Failed to create PipelineRun record")
            raise

        return run

    async def _persist_stage_results(
        self,
        run_id: str,
        stage_ctx: StageContext,
        user_feedback: list[dict] | None = None,
    ) -> None:
        """Update the PipelineRun with latest stage results."""
        import json as _json

        from sqlalchemy import update

        from app.models.base import async_session_factory
        from app.models.pipeline_run import PipelineRun

        status = "executing"
        results = list(stage_ctx.results.values())
        any_failed = any(sr.status == "error" for sr in results)
        all_terminal_success = all(
            sr.status in ("success", "skipped", "degraded") for sr in results
        ) and len(results) == len(stage_ctx.plan.stages)
        if any_failed:
            status = "failed"
        elif all_terminal_success:
            status = "completed"

        try:
            async with async_session_factory() as session:
                values: dict[str, Any] = {
                    "stage_results_json": _json.dumps(stage_ctx.to_persistence_dict(), default=str),
                    "current_stage_idx": stage_ctx.current_stage_idx,
                    "status": status,
                }
                if user_feedback is not None:
                    values["user_feedback_json"] = _json.dumps(user_feedback, default=str)
                await session.execute(
                    update(PipelineRun).where(PipelineRun.id == run_id).values(**values)
                )
                await session.commit()
        except Exception:
            logger.exception("Failed to persist stage results (run_id=%s)", run_id)

    async def _extract_pipeline_learnings(
        self,
        connection_id: str,
        *,
        exec_result: _StageExecutorResult,
        replan_history: list[dict[str, Any]],
    ) -> None:
        """Best-effort extraction of pipeline-level learnings after execution."""
        try:
            from app.models.base import async_session_factory

            extractor = PipelineLearningExtractor()

            async with async_session_factory() as session:
                for rh in replan_history:
                    await extractor.extract_from_replan(
                        session,
                        connection_id,
                        question="",
                        failed_stage_id=rh.get("failed_stage", ""),
                        failed_stage_tool=rh.get("failed_stage", ""),
                        error=rh.get("error", ""),
                        replan_succeeded=(exec_result.status == "completed"),
                    )

                if exec_result.data_gate_outcome and exec_result.failed_stage:
                    await extractor.extract_from_data_gate(
                        session,
                        connection_id,
                        stage_id=exec_result.failed_stage.stage_id,
                        stage_tool=exec_result.failed_stage.tool,
                        outcome=exec_result.data_gate_outcome,
                    )

                await extractor.extract_from_pipeline_completion(
                    session,
                    connection_id,
                    stage_ctx=exec_result.stage_ctx,
                    replan_history=replan_history,
                )
        except Exception:
            logger.debug("Pipeline learning extraction failed", exc_info=True)

    async def _llm_call_with_retry(
        self,
        messages: list[Message],
        tools: list | None,
        preferred_provider: str | None,
        model: str | None,
        wf_id: str,
    ) -> LLMResponse:
        """Wrapper that retries the LLM router call on transient failures."""
        delay = _LLM_CALL_BASE_BACKOFF
        last_exc: Exception | None = None

        for attempt in range(1, _LLM_CALL_MAX_RETRIES + 1):
            try:
                return await self._llm.complete(
                    messages=messages,
                    tools=tools,
                    preferred_provider=preferred_provider,
                    model=model,
                )
            except RETRYABLE_LLM_ERRORS as exc:
                last_exc = exc
                if attempt >= _LLM_CALL_MAX_RETRIES:
                    break
                wait = exc.retry_after_seconds or delay
                logger.warning(
                    "Orchestrator LLM retryable error (attempt %d/%d), retrying in %.1fs: [%s] %s",
                    attempt,
                    _LLM_CALL_MAX_RETRIES,
                    wait,
                    type(exc).__name__,
                    exc,
                )
                await self._tracker.emit(
                    wf_id,
                    "orchestrator:llm_retry",
                    "retrying",
                    f"Attempt {attempt} failed, retrying…",
                )
                await self._tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    f"Provider error, retrying (attempt {attempt + 1})…",
                )
                await asyncio.sleep(wait)
                delay *= 2.0
            except LLMAllProvidersFailedError:
                # Router has already exhausted every provider — bubble up.
                raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LLM call failed without exception")

    async def _validate_partial_answer(
        self,
        final_text: str,
        *,
        question: str,
        sql_results: list[SQLAgentResult],
        preferred_provider: str | None,
        model: str | None,
        wf_id: str,
    ) -> bool:
        """Return ``True`` when the partial answer addresses the question.

        Used after the agent hits ``step_limit_hit`` / ``wall_clock_timeout_hit``
        to decide whether to surface the answer as ``sql_result`` or as
        ``step_limit_reached`` (with the "Continue analysis" CTA). Failures
        default to ``True`` so we never block a usable answer behind a flaky
        validator call.
        """
        if not final_text or not final_text.strip():
            return False
        if not settings.answer_validator_enabled:
            return len(final_text.strip()) > 80
        try:
            from app.agents.answer_validator import AnswerValidator

            validator = AnswerValidator(self._llm)
            sql_summaries = [
                (sr.query_explanation or sr.query or "")[:200]
                for sr in sql_results
                if sr is not None
            ]
            verdict = await validator.validate(
                question=question,
                answer=final_text,
                sql_summaries=sql_summaries,
                preferred_provider=preferred_provider,
                model=model,
            )
            await self._tracker.emit(
                wf_id,
                "orchestrator:answer_validator",
                "completed",
                f"answer addresses question = {verdict.addresses_question}",
                addresses_question=verdict.addresses_question,
                confidence=verdict.confidence,
                reason=verdict.reason,
            )
            return verdict.addresses_question
        except Exception:
            logger.debug("Answer validator failed (non-critical)", exc_info=True)
            return len(final_text.strip()) > 80

    async def _stream_tokens(
        self,
        wf_id: str,
        text: str,
        chunk_size: int = 12,
    ) -> None:
        """Emit final answer text as progressive token events for frontend typing effect."""
        if not text:
            return
        for i in range(0, len(text), chunk_size):
            chunk = text[i : i + chunk_size]
            await self._tracker.emit(wf_id, "token", "streaming", chunk)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        """Convert arbitrary exceptions to user-friendly messages."""
        msg = str(exc).lower()
        if "connection" in msg and ("refused" in msg or "reset" in msg or "timeout" in msg):
            return "Database connection error. Please check your connection settings and try again."
        if "permission" in msg or "access denied" in msg:
            return "Permission error. Please check your database credentials and permissions."
        return "An unexpected error occurred. Please try again shortly."

    # Backward-compatible aliases — delegate to ToolDispatcher
    _DEDUP_TOOL_NAMES = ToolDispatcher._DEDUP_TOOL_NAMES
    _dedup_tool_calls = staticmethod(ToolDispatcher.dedup_tool_calls)
    _build_process_data_params = staticmethod(ToolDispatcher.build_process_data_params)
    _format_sql_result_for_llm = staticmethod(ToolDispatcher.format_sql_result_for_llm)

    # Backward-compatible aliases — delegate to ResponseBuilder
    _build_partial_text = staticmethod(ResponseBuilder.build_partial_text)
    _build_timeout_text = staticmethod(ResponseBuilder.build_timeout_text)
    _build_synthesis_messages = staticmethod(ResponseBuilder.build_synthesis_messages)
    _determine_response_type = staticmethod(ResponseBuilder.determine_response_type)
