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
from app.agents.intent_classifier import (
    IntentType,
    classify_intent,
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
        self._wf_sql_results: dict[str, SQLAgentResult] = {}
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
            self._wf_sql_results[wf_id] = enriched[0]
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

            # Skip classification for continuation or pipeline/complexity overrides
            if is_continuation or context.extra.get("_skip_complexity"):
                logger.info(
                    "Skipping intent classification (%s, wf=%s)",
                    "continuation" if is_continuation else "complexity_override",
                    wf_id,
                )
                return await self._run_full_pipeline(
                    context, wf_id, has_connection, db_type, has_kb, has_mcp
                )

            # --- Phase 1: LLM intent classification ---
            await self._tracker.emit(wf_id, "thinking", "in_progress", "Classifying request…")
            intent_result = await classify_intent(
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
                "Intent classified as %s (reason: %s, wf=%s)",
                intent_result.intent.value,
                intent_result.reason,
                wf_id,
            )
            await self._tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                f"Intent: {intent_result.intent.value} ({intent_result.reason})",
            )

            # --- Phase 2: Route to the appropriate execution chain ---
            if intent_result.intent == IntentType.DIRECT_RESPONSE:
                return await self._run_direct_response(
                    context,
                    wf_id,
                    has_connection,
                    has_kb,
                    has_mcp,
                )

            if intent_result.intent == IntentType.DATA_QUERY:
                return await self._run_data_query(
                    context, wf_id, has_connection, db_type, has_kb, has_mcp
                )

            if intent_result.intent == IntentType.KNOWLEDGE_QUERY:
                return await self._run_knowledge_query(context, wf_id, has_kb)

            if intent_result.intent == IntentType.MCP_QUERY:
                return await self._run_mcp_query(context, wf_id, has_mcp)

            # IntentType.MIXED or any unexpected value
            return await self._run_full_pipeline(
                context, wf_id, has_connection, db_type, has_kb, has_mcp
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
    # Intent-based execution paths
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
            for m in context.chat_history[-4:]:
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

    async def _run_data_query(
        self,
        context: AgentContext,
        wf_id: str,
        has_connection: bool,
        db_type: str | None,
        has_kb: bool,
        has_mcp: bool,
    ) -> AgentResponse:
        """Handle data/SQL questions: load DB context, expose DB tools, check complexity."""
        question = context.user_question

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

        table_map = ""
        if has_connection and context.connection_config:
            cid = context.connection_config.connection_id
            if not cid:
                cid = await self._ctx_loader.resolve_connection_id(
                    context.project_id,
                    context.connection_config,
                )
                if cid and context.connection_config:
                    context.connection_config.connection_id = cid
            if cid:
                table_map = await self._ctx_loader.build_table_map(cid, wf_id)

        if has_connection and AdaptivePlanner._is_complex(question):
            logger.info("Complex data query detected — using multi-stage pipeline")
            return await self._run_complex_pipeline(
                context, wf_id, table_map, db_type, staleness_warning=None
            )

        project_overview = await self._ctx_loader.load_project_overview(context.project_id)
        recent_learnings = await self._ctx_loader.load_recent_learnings(context)

        tools = get_orchestrator_tools(
            has_connection=has_connection,
            has_knowledge_base=False,
            has_mcp_sources=False,
        )

        return await self._run_tool_loop(
            context,
            wf_id,
            has_connection=has_connection,
            db_type=db_type,
            has_kb=False,
            has_mcp=False,
            table_map=table_map,
            project_overview=project_overview,
            recent_learnings=recent_learnings,
            tools=tools,
            max_steps_override=settings.max_simple_query_steps,
        )

    async def _run_knowledge_query(
        self,
        context: AgentContext,
        wf_id: str,
        has_kb: bool,
    ) -> AgentResponse:
        """Handle code/architecture questions: load KB context, expose search_codebase only."""
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

        staleness_warning = await self._ctx_loader.check_staleness(context.project_id, wf_id)
        project_overview = await self._ctx_loader.load_project_overview(context.project_id)

        tools = get_orchestrator_tools(
            has_connection=False,
            has_knowledge_base=has_kb,
            has_mcp_sources=False,
        )

        return await self._run_tool_loop(
            context,
            wf_id,
            has_connection=False,
            db_type=None,
            has_kb=has_kb,
            has_mcp=False,
            table_map="",
            project_overview=project_overview,
            recent_learnings=None,
            tools=tools,
            staleness_warning=staleness_warning,
        )

    async def _run_mcp_query(
        self,
        context: AgentContext,
        wf_id: str,
        has_mcp: bool,
    ) -> AgentResponse:
        """Handle MCP source questions: expose only query_mcp_source tool."""
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

        tools = get_orchestrator_tools(
            has_connection=False,
            has_knowledge_base=False,
            has_mcp_sources=has_mcp,
        )

        return await self._run_tool_loop(
            context,
            wf_id,
            has_connection=False,
            db_type=None,
            has_kb=False,
            has_mcp=has_mcp,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            tools=tools,
        )

    async def _run_full_pipeline(
        self,
        context: AgentContext,
        wf_id: str,
        has_connection: bool,
        db_type: str | None,
        has_kb: bool,
        has_mcp: bool,
    ) -> AgentResponse:
        """Full pipeline for mixed/ambiguous intents — loads ALL context, ALL tools."""
        question = context.user_question

        staleness_warning = await self._ctx_loader.check_staleness(context.project_id, wf_id)

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

        table_map = ""
        if has_connection and context.connection_config:
            cid = context.connection_config.connection_id
            if not cid:
                cid = await self._ctx_loader.resolve_connection_id(
                    context.project_id,
                    context.connection_config,
                )
                if cid and context.connection_config:
                    context.connection_config.connection_id = cid
            if cid:
                table_map = await self._ctx_loader.build_table_map(cid, wf_id)

        is_complex = not context.extra.get("_skip_complexity") and AdaptivePlanner._is_complex(
            question
        )
        if has_connection and is_complex:
            logger.info("Complex query detected — using multi-stage pipeline")
            return await self._run_complex_pipeline(
                context, wf_id, table_map, db_type, staleness_warning
            )

        project_overview = await self._ctx_loader.load_project_overview(context.project_id)
        recent_learnings = await self._ctx_loader.load_recent_learnings(context)

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
            tools=tools,
            staleness_warning=staleness_warning,
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
        tools: list,
        staleness_warning: str | None = None,
        max_steps_override: int | None = None,
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
        )
        allocation = budget_mgr.allocate(
            system_prompt=base_prompt,
            schema_text=table_map,
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
        query_db_cap_injected = False

        loop_budget = min(settings.max_context_tokens, context_window)
        wrap_up_injected = False
        step_limit_hit = False
        wall_clock_timeout_hit = False
        wall_clock_start = time.monotonic()
        wall_clock_limit = settings.agent_wall_clock_timeout_seconds

        max_iter = (
            max_steps_override
            or context.max_orchestrator_steps
            or settings.max_orchestrator_iterations
        )
        iteration = 0
        for iteration in range(max_iter):
            messages, did_trim = trim_loop_messages(messages, loop_budget)
            if did_trim:
                await self._tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    "Compacting earlier analysis to free context space…",
                )

            elapsed_wall = time.monotonic() - wall_clock_start
            if not wrap_up_injected and elapsed_wall > wall_clock_limit:
                messages.append(
                    Message(
                        role="system",
                        content=(
                            "CRITICAL: TIME LIMIT REACHED. You MUST compose your "
                            "final answer NOW. Any further tool calls will be "
                            "REJECTED. Use only the data you already have."
                        ),
                    )
                )
                wrap_up_injected = True
                logger.warning(
                    "Wall-clock timeout (%.1fs > %ds, wf=%s), forcing wrap-up",
                    elapsed_wall,
                    wall_clock_limit,
                    wf_id,
                )

            if not wrap_up_injected and should_wrap_up(messages, loop_budget):
                messages.append(
                    Message(
                        role="system",
                        content=(
                            "IMPORTANT: You are running low on context space. "
                            "Do NOT make any more tool calls. Compose your "
                            "final answer now using the data you have "
                            "gathered so far."
                        ),
                    )
                )
                wrap_up_injected = True
                logger.info(
                    "Approaching context limit (wf=%s), finishing with available data",
                    wf_id,
                )

            remaining_steps = max_iter - iteration - 1
            if not wrap_up_injected and remaining_steps <= settings.orchestrator_wrap_up_steps:
                messages.append(
                    Message(
                        role="system",
                        content=(
                            f"CRITICAL: You have {remaining_steps} analysis step(s) "
                            "remaining. You MUST compose your final answer NOW using "
                            "the data you have gathered so far. Do NOT make any more "
                            "tool calls unless absolutely essential."
                        ),
                    )
                )
                wrap_up_injected = True
                logger.info(
                    "Approaching step limit (%d/%d, wf=%s), finishing with available data",
                    iteration + 1,
                    max_iter,
                    wf_id,
                )

            if query_db_count >= 2 and not query_db_cap_injected:
                messages.append(
                    Message(
                        role="system",
                        content=(
                            f"CRITICAL: You have already executed {query_db_count} "
                            "database queries. Do NOT call query_database again. "
                            "Compose your FINAL ANSWER now using all the data "
                            "you have collected so far."
                        ),
                    )
                )
                tools = [t for t in tools if t.name != "query_database"]
                query_db_cap_injected = True
                logger.info(
                    "query_database cap reached (%d calls, wf=%s), "
                    "tool stripped from further iterations",
                    query_db_count,
                    wf_id,
                )

            pct = int(estimate_messages_tokens(messages) / max(loop_budget, 1) * 100)
            if pct > 50:
                logger.debug("Context usage: ~%d%% of model limit (wf=%s)", pct, wf_id)

            await self._tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                f"Analyzing request (step {iteration + 1}/{max_iter})…",
            )
            try:
                _sd: dict[str, Any] = {}
                async with self._tracker.step(
                    wf_id,
                    "orchestrator:llm_call",
                    f"Orchestrator LLM ({iteration + 1}/{max_iter})",
                    step_data=_sd,
                ):
                    llm_resp = await self._llm_call_with_retry(
                        messages=messages,
                        tools=tools if tools else None,
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
                    messages, _ = trim_loop_messages(messages, aggressive)
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
                                tools=tools if tools else None,
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

            active_calls, skipped_map = ToolDispatcher.dedup_tool_calls(
                llm_resp.tool_calls, context.chat_history
            )

            has_process_data = any(tc.name == "process_data" for tc in active_calls)

            if len(active_calls) > 1 and not has_process_data:

                async def _throttled_meta_tool(
                    _tc: ToolCall,
                ) -> tuple[str, Any]:
                    async with self._parallel_tool_sem:
                        return await self._dispatcher.dispatch(_tc, context, wf_id, total_usage)

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
                        logger.warning(
                            "Parallel tool call %s failed: %s",
                            active_calls[i].name,
                            res,
                        )
                        executed_pairs[tc_id] = (f"Error: {res}", None)
                    else:
                        executed_pairs[tc_id] = res  # type: ignore[assignment]
            else:
                executed_pairs = {}
                for single_tc in active_calls:
                    executed_pairs[single_tc.id] = await self._dispatcher.dispatch(
                        single_tc, context, wf_id, total_usage
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
                    self._wf_sql_results[wf_id] = sub_result
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
                    messages, last_sql_result, knowledge_sources, loop_budget
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
                chat_history=context.chat_history[-4:] if context.chat_history else [],
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

    _MAX_REPLANS = 2

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
        except Exception:
            logger.exception("Failed to create pipeline run record")
            raise AgentFatalError("Pipeline initialisation failed") from None

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
            chat_history=context.chat_history[-4:] if context.chat_history else [],
        )
        replan_history: list[dict[str, Any]] = []

        try:
            stage_ctx = StageContext(plan=plan, pipeline_run_id=pipeline_run.id)
            exec_result = await executor.execute(plan, pipeline_ctx, stage_ctx=stage_ctx)

            replan_count = 0
            while (
                exec_result.status == "stage_failed"
                and exec_result.replan_eligible
                and replan_count < self._MAX_REPLANS
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
                    f"(attempt {replan_count}/{self._MAX_REPLANS})…",
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

            plan = ExecutionPlan.from_json(pipeline_run.plan_json)
            stage_results_raw = _json.loads(pipeline_run.stage_results_json)
            user_feedback = _json.loads(pipeline_run.user_feedback_json)
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
                chat_history=context.chat_history[-4:] if context.chat_history else [],
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
        if all(sr.status in ("success", "skipped") for sr in stage_ctx.results.values()) and len(
            stage_ctx.results
        ) == len(stage_ctx.plan.stages):
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
            except LLMAllProvidersFailedError as exc:
                last_exc = exc
                if attempt >= _LLM_CALL_MAX_RETRIES:
                    break
                logger.warning(
                    "All providers failed (attempt %d/%d), retrying whole chain in %.1fs",
                    attempt,
                    _LLM_CALL_MAX_RETRIES,
                    delay,
                )
                await self._tracker.emit(
                    wf_id,
                    "orchestrator:llm_retry",
                    "retrying",
                    "All providers failed, retrying…",
                )
                await self._tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    "All providers failed, retrying…",
                )
                await asyncio.sleep(delay)
                delay *= 2.0

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LLM call failed without exception")

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
