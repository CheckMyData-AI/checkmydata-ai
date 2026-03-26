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
from app.agents.query_planner import (
    QueryPlanner,
    detect_complexity,
    detect_complexity_adaptive,
)
from app.agents.sql_agent import SQLAgent, SQLAgentResult
from app.agents.stage_context import ExecutionPlan, StageContext
from app.agents.stage_executor import StageExecutor, _StageExecutorResult
from app.agents.stage_validator import StageValidator
from app.agents.tools.orchestrator_tools import get_orchestrator_tools
from app.agents.validation import AgentResultValidator
from app.agents.viz_agent import VizAgent, VizResult
from app.config import settings
from app.connectors.base import ConnectionConfig, QueryResult, connector_key
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
from app.services.data_processor import get_data_processor

logger = logging.getLogger(__name__)

_LLM_CALL_MAX_RETRIES = 2
_LLM_CALL_BASE_BACKOFF = 3.0

MAX_SUB_AGENT_RETRIES = 2


class _ClarificationRequestError(Exception):
    """Internal signal: the orchestrator wants to ask the user a question."""

    def __init__(self, payload_json: str) -> None:
        self.payload_json = payload_json
        super().__init__(payload_json)


PROMPT_VERSION = "v2.1"


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
    viz_config: dict = field(default_factory=dict)
    knowledge_sources: list[RAGSource] = field(default_factory=list)
    error: str | None = None
    workflow_id: str | None = None
    token_usage: dict = field(default_factory=dict)
    llm_provider: str = ""
    llm_model: str = ""
    staleness_warning: str | None = None
    response_type: str = "text"  # text | sql_result | knowledge | error
    tool_call_log: list[dict] = field(default_factory=list)
    prompt_version: str = PROMPT_VERSION
    suggested_followups: list[str] = field(default_factory=list)
    insights: list[dict] = field(default_factory=list)
    context_usage_pct: int = 0


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
        self._last_sql_result: SQLAgentResult | None = None
        self._last_enriched_result: SQLAgentResult | None = None
        self._enriched_at: float = 0.0

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
        import time as _time

        wf_id = context.workflow_id
        question = context.user_question

        stale_seconds = 300  # 5 min staleness guard
        if self._last_enriched_result and (_time.time() - self._enriched_at) < stale_seconds:
            self._last_sql_result = self._last_enriched_result
        else:
            self._last_sql_result = None
            self._last_enriched_result = None

        try:
            # Check for pipeline resume first
            resume_info = await self._check_pipeline_resume(context)
            if resume_info:
                return await self._resume_pipeline(resume_info, context)

            has_connection = context.connection_config is not None
            db_type = context.connection_config.db_type if context.connection_config else None

            # Parallel context loading
            staleness_coro = self._check_staleness(context.project_id, wf_id)
            mcp_coro = self._has_mcp_sources(context.project_id, wf_id)

            staleness_warning, has_mcp = await asyncio.gather(staleness_coro, mcp_coro)
            has_kb = self._has_knowledge_base(context.project_id)

            if context.chat_history:
                from app.config import settings as app_settings

                context.chat_history = await trim_history(
                    context.chat_history,
                    max_tokens=app_settings.max_history_tokens,
                    llm_router=self._llm,
                    preferred_provider=context.preferred_provider,
                    model=context.model,
                    summary_model=app_settings.history_summary_model or None,
                )

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
                    table_map = await self._build_table_map(cid, wf_id)

            # Complexity detection — branch to multi-stage pipeline
            is_complex = detect_complexity(question, context.chat_history)
            if not is_complex and not context.extra.get("_skip_complexity"):
                is_complex = await detect_complexity_adaptive(
                    question,
                    self._llm,
                    context.chat_history,
                    preferred_provider=context.preferred_provider,
                    model=context.model,
                )
            if has_connection and not context.extra.get("_skip_complexity") and is_complex:
                logger.info("Complex query detected — using multi-stage pipeline")
                result = await self._run_complex_pipeline(
                    context, wf_id, table_map, db_type, staleness_warning
                )
                await self._tracker.end(wf_id, "orchestrator", "completed", "complex_pipeline")
                return result

            project_overview = await self._load_project_overview(context.project_id)
            recent_learnings = await self._load_recent_learnings(context)

            context_window = self._llm.get_context_window(context.model)
            budget_mgr = ContextBudgetManager(
                total_budget=min(settings.max_context_tokens, context_window),
            )
            base_prompt = build_orchestrator_system_prompt(
                project_name=context.project_name,
                db_type=db_type,
                has_connection=has_connection,
                has_knowledge_base=has_kb,
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
                table_map=allocation.schema_text,
                current_datetime=get_current_datetime_str(),
                project_overview=allocation.overview_text,
                recent_learnings=allocation.learnings_text,
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
            used_provider = ""
            used_model = ""

            loop_budget = context_window
            wrap_up_injected = False

            max_iter = settings.max_orchestrator_iterations
            for iteration in range(max_iter):
                messages, did_trim = trim_loop_messages(messages, loop_budget)
                if did_trim:
                    await self._tracker.emit(
                        wf_id,
                        "thinking",
                        "in_progress",
                        "Compacting earlier analysis to free context space…",
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
                    async with self._tracker.step(
                        wf_id,
                        "orchestrator:llm_call",
                        f"Orchestrator LLM ({iteration + 1}/{max_iter})",
                    ):
                        llm_resp = await self._llm_call_with_retry(
                            messages=messages,
                            tools=tools if tools else None,
                            preferred_provider=context.preferred_provider,
                            model=context.model,
                            wf_id=wf_id,
                        )
                except (LLMAllProvidersFailedError, LLMTokenLimitError) as exc:
                    if _is_token_limit_error(exc):
                        logger.info(
                            "Hit context limit (wf=%s), retrying with compressed context",
                            wf_id,
                        )
                        aggressive = int(loop_budget * 0.6)
                        messages, _ = trim_loop_messages(messages, aggressive)
                        try:
                            async with self._tracker.step(
                                wf_id,
                                "orchestrator:llm_call",
                                "Orchestrator LLM (recovery)",
                            ):
                                llm_resp = await self._llm_call_with_retry(
                                    messages=messages,
                                    tools=tools if tools else None,
                                    preferred_provider=context.preferred_provider,
                                    model=context.model,
                                    wf_id=wf_id,
                                )
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

                has_process_data = any(tc.name == "process_data" for tc in llm_resp.tool_calls)

                if len(llm_resp.tool_calls) > 1 and not has_process_data:
                    gather_results = await asyncio.gather(
                        *(
                            self._handle_meta_tool(tc, context, wf_id, total_usage)
                            for tc in llm_resp.tool_calls
                        ),
                        return_exceptions=True,
                    )
                    tool_pairs: list[tuple[str, Any]] = []
                    for i, res in enumerate(gather_results):
                        if isinstance(res, Exception):
                            logger.warning(
                                "Parallel tool call %s failed: %s",
                                llm_resp.tool_calls[i].name,
                                res,
                            )
                            tool_pairs.append((f"Error: {res}", None))
                        else:
                            tool_pairs.append(res)  # type: ignore[arg-type]
                else:
                    tool_pairs = []
                    for single_tc in llm_resp.tool_calls:
                        tool_pairs.append(
                            await self._handle_meta_tool(single_tc, context, wf_id, total_usage)
                        )

                for tc, (result_text, sub_result) in zip(llm_resp.tool_calls, tool_pairs):
                    tool_call_log.append(
                        {
                            "tool": tc.name,
                            "arguments": tc.arguments,
                            "result_preview": result_text[:200],
                        }
                    )

                    if isinstance(sub_result, SQLAgentResult):
                        last_sql_result = sub_result
                        self._last_sql_result = sub_result
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
                await self._tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    "Reached maximum iterations, composing from partial data…",
                )
                partial_parts: list[str] = ["I reached the maximum number of analysis steps."]
                if last_sql_result and last_sql_result.results:
                    rc = last_sql_result.results.row_count
                    partial_parts.append(f"I found {rc} rows of data from the database.")
                if knowledge_sources:
                    partial_parts.append(
                        f"I found {len(knowledge_sources)} relevant document(s) "
                        "from the knowledge base."
                    )
                partial_parts.append("Here is what I found so far based on the tools I used.")
                final_text = " ".join(partial_parts)

            response_type = self._determine_response_type(last_sql_result, knowledge_sources)

            viz_type = "text"
            viz_config: dict = {}
            if last_sql_result and last_sql_result.results and response_type == "sql_result":
                try:
                    await self._tracker.emit(
                        wf_id,
                        "thinking",
                        "in_progress",
                        "Choosing the best visualization…",
                    )
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
                    await self._tracker.emit(
                        wf_id,
                        "thinking",
                        "in_progress",
                        f"Selected {viz_type} visualization",
                    )

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
                llm_provider=used_provider,
                llm_model=used_model,
                staleness_warning=staleness_warning,
                response_type=response_type,
                tool_call_log=tool_call_log,
                insights=last_sql_result.insights if last_sql_result else [],
                suggested_followups=followups,
                context_usage_pct=final_pct,
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
                viz_config=payload,
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
        """Plan and execute a multi-stage pipeline for complex queries."""
        await self._tracker.emit(
            wf_id,
            "thinking",
            "in_progress",
            "Complex query detected, creating execution plan…",
        )
        planner = QueryPlanner(self._llm)

        async with self._tracker.step(wf_id, "orchestrator:planning", "Creating execution plan"):
            plan = await planner.plan(
                context.user_question,
                table_map=table_map,
                db_type=db_type,
                preferred_provider=context.preferred_provider,
                model=context.model,
            )

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

        pipeline_run = await self._create_pipeline_run(context, plan)

        executor = StageExecutor(
            sql_agent=self._sql,
            knowledge_agent=self._knowledge,
            llm_router=self._llm,
            tracker=self._tracker,
            validator=StageValidator(),
        )

        stage_ctx = StageContext(plan=plan, pipeline_run_id=pipeline_run.id)
        exec_result = await executor.execute(plan, context, stage_ctx=stage_ctx)

        await self._persist_stage_results(pipeline_run.id, exec_result.stage_ctx)

        return self._build_pipeline_response(exec_result, wf_id, staleness_warning, pipeline_run.id)

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
            result = await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            pipeline_run = result.scalar_one_or_none()
            if not pipeline_run:
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

        executor = StageExecutor(
            sql_agent=self._sql,
            knowledge_agent=self._knowledge,
            llm_router=self._llm,
            tracker=self._tracker,
            validator=StageValidator(),
        )
        exec_result = await executor.execute(
            plan, context, resume_from=resume_from, stage_ctx=stage_ctx
        )

        await self._persist_stage_results(run_id, exec_result.stage_ctx, user_feedback)

        result = self._build_pipeline_response(exec_result, wf_id, None, run_id)
        await self._tracker.end(wf_id, "orchestrator", "completed", "pipeline_resume")
        return result

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

        async with async_session_factory() as session:
            session.add(run)
            await session.commit()
            await session.refresh(run)

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

    def _build_pipeline_response(
        self,
        exec_result: _StageExecutorResult,
        wf_id: str,
        staleness_warning: str | None,
        pipeline_run_id: str,
    ) -> AgentResponse:
        """Convert a ``_StageExecutorResult`` into an ``AgentResponse``."""
        last_sql_result = None
        for stage in reversed(exec_result.stage_ctx.plan.stages):
            sr = exec_result.stage_ctx.get_result(stage.stage_id)
            if sr and sr.query_result:
                last_sql_result = sr
                break

        if exec_result.status == "completed":
            return AgentResponse(
                answer=exec_result.final_answer,
                query=last_sql_result.query if last_sql_result else None,
                results=last_sql_result.query_result if last_sql_result else None,
                workflow_id=wf_id,
                staleness_warning=staleness_warning,
                response_type="pipeline_complete",
                viz_type="table" if last_sql_result else "text",
                viz_config={"pipeline_run_id": pipeline_run_id},
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
            )

        # stage_failed
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
                "stage_id": exec_result.failed_stage.stage_id if exec_result.failed_stage else "",
            },
        )

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
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        """Convert arbitrary exceptions to user-friendly messages."""
        msg = str(exc).lower()
        if "connection" in msg and ("refused" in msg or "reset" in msg or "timeout" in msg):
            return "Database connection error. Please check your connection settings and try again."
        if "permission" in msg or "access denied" in msg:
            return "Permission error. Please check your database credentials and permissions."
        return "An unexpected error occurred. Please try again shortly."

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
            )
            self._emit_tool_result_thinking(wf_id, "SQL Agent", sql_sub)
            return sql_text, sql_sub
        if tc.name == "search_codebase":
            kb_text, kb_sub = await self._handle_search_codebase(
                tc,
                context,
                wf_id,
                total_usage,
            )
            self._emit_tool_result_thinking(wf_id, "Knowledge Agent", kb_sub)
            return kb_text, kb_sub
        if tc.name == "manage_rules":
            rules_text = await self._handle_manage_rules(
                tc.arguments or {},
                context,
                wf_id,
            )
            return rules_text, None
        if tc.name == "query_mcp_source":
            mcp_text, mcp_sub = await self._handle_query_mcp_source(
                tc,
                context,
                wf_id,
                total_usage,
            )
            return mcp_text, mcp_sub
        if tc.name == "process_data":
            pd_text = await self._handle_process_data(tc, wf_id)
            operation = (tc.arguments or {}).get("operation", "")
            pd_sub = self._last_sql_result if operation == "aggregate_data" else None
            return pd_text, pd_sub
        if tc.name == "ask_user":
            return await self._handle_ask_user(tc, context, wf_id)
        logger.warning("Unknown meta-tool called: %s", tc.name)
        return (
            f"Error: unknown tool '{tc.name}'. Available tools: "
            "query_database, search_codebase, manage_rules, "
            "query_mcp_source, process_data, ask_user."
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
                return (
                    f"SQL query failed after retries: {e}. "
                    "Partial information may be available from other tools."
                ), None
            except AgentFatalError as e:
                return f"SQL query failed: {e}", None
            except AgentError as e:
                return f"SQL agent error: {e}", None

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

        if self._last_sql_result is None or self._last_sql_result.results is None:
            return (
                "Error: no query results available to process. "
                "Call query_database first to retrieve data, then use process_data."
            )

        qr = self._last_sql_result.results
        if qr.error or not qr.rows:
            return "Error: last query result has no data rows to process."

        params = self._build_process_data_params(args)

        try:
            processor = get_data_processor()
            processed = processor.process(qr, operation, params)
        except ValueError as e:
            return f"Processing error: {e}"
        except Exception:
            logger.exception("Unexpected error in process_data")
            return "Error: data processing failed unexpectedly."

        import time as _time

        self._last_sql_result.results = processed.query_result
        self._last_enriched_result = self._last_sql_result
        self._enriched_at = _time.time()

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
    def _build_process_data_params(args: dict[str, Any]) -> dict[str, Any]:
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
        if args.get("exclude_empty"):
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
                async with self._tracker.step(
                    wf_id,
                    "orchestrator:knowledge_agent",
                    f"Knowledge Agent (attempt {attempt + 1})",
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

            except AgentRetryableError as e:
                if attempt < MAX_SUB_AGENT_RETRIES:
                    logger.info("Knowledge agent retryable error (attempt %d): %s", attempt + 1, e)
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
        except Exception as e:
            logger.exception("Rule management failed (%s)", action)
            return f"Error managing rule: {e}"

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

        for attempt in range(MAX_SUB_AGENT_RETRIES + 1):
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
                        if conn.project_id != context.project_id:
                            return "Error: MCP connection does not belong to this project", None
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

                adapter = MCPClientAdapter()
                try:
                    await adapter.connect(config)

                    async with self._tracker.step(
                        wf_id,
                        "orchestrator:mcp_source_agent",
                        f"MCP Source Agent (attempt {attempt + 1})",
                    ):
                        result = await self._mcp_source.run(
                            context,
                            question=sub_question,
                            source_name=conn.name,
                            adapter=adapter,
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

        return "MCP source query failed after maximum retries.", None

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

    async def _has_mcp_sources(self, project_id: str, wf_id: str = "") -> bool:
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
            if wf_id:
                try:
                    await self._tracker.emit(
                        wf_id,
                        "orchestrator:warning",
                        "degraded",
                        "MCP source check failed; MCP tools unavailable this request",
                    )
                except Exception:
                    logger.debug("Failed to emit MCP degradation warning", exc_info=True)
            return False

    def _has_knowledge_base(self, project_id: str) -> bool:
        try:
            collection = self._vector_store.get_or_create_collection(project_id)
            return collection.count() > 0
        except Exception:
            return False

    async def _build_table_map(self, connection_id: str, wf_id: str = "") -> str:
        try:
            from app.models.base import async_session_factory
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            async with async_session_factory() as session:
                entries = await svc.get_index(session, connection_id)
            return svc.build_table_map(entries)
        except Exception:
            logger.debug("Failed to build table map", exc_info=True)
            if wf_id:
                try:
                    await self._tracker.emit(
                        wf_id,
                        "orchestrator:warning",
                        "degraded",
                        "Schema map unavailable; SQL quality may be reduced",
                    )
                except Exception:
                    logger.debug("Failed to emit schema-map degradation warning", exc_info=True)
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

    async def _load_project_overview(self, project_id: str) -> str | None:
        """Load the pre-generated project knowledge overview."""
        try:
            from sqlalchemy import select

            from app.models.base import async_session_factory
            from app.models.project_cache import ProjectCache

            async with async_session_factory() as session:
                result = await session.execute(
                    select(ProjectCache.overview_text).where(ProjectCache.project_id == project_id)
                )
                text = result.scalar_one_or_none()
                if isinstance(text, str) and text:
                    return text
                return None
        except Exception:
            logger.debug("Failed to load project overview", exc_info=True)
            return None

    async def _load_recent_learnings(
        self,
        context: AgentContext,
    ) -> str | None:
        """Load high-confidence / recent learnings for orchestrator context."""
        cfg = context.connection_config
        if not cfg or not cfg.connection_id:
            return None
        try:
            from app.models.base import async_session_factory
            from app.services.agent_learning_service import AgentLearningService

            svc = AgentLearningService()
            async with async_session_factory() as session:
                learnings = await svc.get_learnings(
                    session,
                    cfg.connection_id,
                    min_confidence=0.6,
                    active_only=True,
                )
            if not learnings:
                return None

            top = sorted(
                learnings,
                key=lambda lrn: (lrn.times_confirmed, lrn.confidence),
                reverse=True,
            )[:15]

            lines = ["RECENT AGENT LEARNINGS (verified insights):"]
            for lrn in top:
                conf = int(lrn.confidence * 100)
                lines.append(f"- [{lrn.category}] {lrn.subject}: {lrn.lesson} ({conf}%)")
            return "\n".join(lines)
        except Exception:
            logger.debug(
                "Failed to load recent learnings for orchestrator",
                exc_info=True,
            )
            return None

    async def _check_staleness(self, project_id: str, wf_id: str = "") -> str | None:
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
            if wf_id:
                try:
                    await self._tracker.emit(
                        wf_id,
                        "orchestrator:warning",
                        "degraded",
                        "Staleness check failed; unable to verify knowledge base freshness",
                    )
                except Exception:
                    logger.debug("Failed to emit staleness degradation warning", exc_info=True)
            return None
