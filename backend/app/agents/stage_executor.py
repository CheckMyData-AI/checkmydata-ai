"""StageExecutor — runs pipeline stages sequentially with validation,
retry, checkpoint pauses, and resume-from-stage capability.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from app.agents.base import AgentContext, BaseAgent
from app.agents.errors import AgentError, AgentFatalError, AgentRetryableError
from app.agents.stage_context import (
    ExecutionPlan,
    PlanStage,
    StageContext,
    StageResult,
)
from app.agents.stage_validator import StageValidationOutcome, StageValidator
from app.config import settings
from app.connectors.base import QueryResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import Message
from app.llm.errors import RETRYABLE_LLM_ERRORS
from app.llm.router import LLMRouter
from app.services.data_processor import get_data_processor

logger = logging.getLogger(__name__)


class StageExecutor:
    """Executes an ``ExecutionPlan`` stage-by-stage."""

    def __init__(
        self,
        *,
        sql_agent: BaseAgent,
        knowledge_agent: BaseAgent,
        llm_router: LLMRouter,
        tracker: WorkflowTracker,
        validator: StageValidator | None = None,
        mcp_source_agent: BaseAgent | None = None,
    ) -> None:
        self._sql = sql_agent
        self._knowledge = knowledge_agent
        self._llm = llm_router
        self._tracker = tracker
        self._validator = validator or StageValidator()
        self._mcp_source = mcp_source_agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        plan: ExecutionPlan,
        context: AgentContext,
        *,
        resume_from: int = 0,
        stage_ctx: StageContext | None = None,
    ) -> _StageExecutorResult:
        """Run stages from *resume_from* onward.

        Returns a ``_StageExecutorResult`` which the orchestrator inspects
        to decide whether the pipeline is complete, at a checkpoint, or
        needs user intervention.
        """
        wf_id = context.workflow_id

        if stage_ctx is None:
            stage_ctx = StageContext(plan=plan, pipeline_run_id="")

        await self._emit_plan(wf_id, plan)

        for idx in range(resume_from, len(plan.stages)):
            stage = plan.stages[idx]
            stage_ctx.current_stage_idx = idx

            await self._emit_stage_start(wf_id, stage, idx, len(plan.stages))

            result = await self._execute_with_retries(stage, stage_ctx, context)

            if result.status == "error":
                await self._emit_stage_result(wf_id, stage, result)
                return _StageExecutorResult(
                    status="stage_failed",
                    stage_ctx=stage_ctx,
                    failed_stage=stage,
                    failed_validation=StageValidationOutcome(
                        passed=False, errors=[result.error or "unknown"]
                    ),
                )

            validation = self._validator.validate(stage, result, stage_ctx)
            await self._emit_stage_validation(wf_id, stage, validation)

            if not validation.passed:
                retried = await self._retry_failed_validation(stage, stage_ctx, context, validation)
                if retried is None:
                    await self._emit_stage_result(wf_id, stage, result)
                    return _StageExecutorResult(
                        status="stage_failed",
                        stage_ctx=stage_ctx,
                        failed_stage=stage,
                        failed_validation=validation,
                    )
                result = retried

            stage_ctx.set_result(stage.stage_id, result)
            await self._emit_stage_complete(wf_id, stage, result, idx)
            await self._emit_stage_result(wf_id, stage, result)

            if stage.checkpoint:
                await self._emit_checkpoint(wf_id, stage, result)
                return _StageExecutorResult(
                    status="checkpoint",
                    stage_ctx=stage_ctx,
                    checkpoint_stage=stage,
                    checkpoint_result=result,
                )

        last_stage = plan.stages[-1] if plan.stages else None
        if last_stage and last_stage.tool == "synthesize":
            last_result = stage_ctx.results.get(last_stage.stage_id)
            if last_result and last_result.summary:
                return _StageExecutorResult(
                    status="completed", stage_ctx=stage_ctx, final_answer=last_result.summary
                )

        final = await self._synthesize(stage_ctx, context)
        return _StageExecutorResult(status="completed", stage_ctx=stage_ctx, final_answer=final)

    # ------------------------------------------------------------------
    # Stage dispatch
    # ------------------------------------------------------------------

    async def _execute_stage(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
        error_context: str | None = None,
    ) -> StageResult:
        enriched_q = self._build_stage_question(stage, stage_ctx, error_context)

        try:
            match stage.tool:
                case "query_database":
                    return await self._run_sql_stage(enriched_q, stage, context)
                case "search_codebase":
                    return await self._run_knowledge_stage(enriched_q, stage, context)
                case "analyze_results":
                    return await self._run_analysis_stage(enriched_q, stage, stage_ctx, context)
                case "process_data":
                    return await self._run_process_data_stage(stage, stage_ctx, context)
                case "query_mcp_source":
                    return await self._run_mcp_stage(enriched_q, stage, context)
                case "synthesize":
                    return await self._synthesize_stage(stage, stage_ctx, context)
                case _:
                    return StageResult(
                        stage_id=stage.stage_id,
                        status="error",
                        error=f"Unknown tool: {stage.tool}",
                    )
        except Exception as exc:
            logger.exception("Stage '%s' raised an exception", stage.stage_id)
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=str(exc),
            )

    async def _execute_with_retries(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
    ) -> StageResult:
        """Execute a stage, retrying on retryable sub-agent errors."""
        wf_id = context.workflow_id
        for attempt in range(settings.max_stage_retries + 1):
            result = await self._execute_stage(stage, stage_ctx, context)
            if result.status != "error":
                return result
            if attempt < settings.max_stage_retries:
                await self._tracker.emit(
                    wf_id,
                    "stage_retry",
                    "retrying",
                    f"Stage '{stage.stage_id}' attempt {attempt + 2}",
                    stage_id=stage.stage_id,
                    attempt=attempt + 2,
                    reason=result.error or "",
                )
        return result

    async def _retry_failed_validation(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
        validation: StageValidationOutcome,
    ) -> StageResult | None:
        """Retry the stage up to max_stage_retries with error context."""
        wf_id = context.workflow_id
        for retry in range(settings.max_stage_retries):
            await self._tracker.emit(
                wf_id,
                "stage_retry",
                "retrying",
                f"Stage '{stage.stage_id}' validation failed, retry {retry + 1}",
                stage_id=stage.stage_id,
                attempt=retry + 2,
                reason=validation.error_summary,
            )
            result = await self._execute_stage(
                stage, stage_ctx, context, error_context=validation.error_summary
            )
            if result.status == "error":
                continue
            validation = self._validator.validate(stage, result, stage_ctx)
            await self._emit_stage_validation(wf_id, stage, validation)
            if validation.passed:
                return result
        return None

    # ------------------------------------------------------------------
    # Stage question builder
    # ------------------------------------------------------------------

    def _build_stage_question(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        error_context: str | None = None,
    ) -> str:
        parts: list[str] = []

        prev_context = stage_ctx.build_context_for_stage(stage.stage_id)
        if prev_context:
            parts.append(prev_context)

        parts.append(f"Task: {stage.description}")

        if stage.input_context:
            parts.append(f"Required input: {stage.input_context}")

        if error_context:
            parts.append(
                f"IMPORTANT: The previous attempt failed validation: {error_context}. "
                "Please adjust your approach."
            )

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Stage runners
    # ------------------------------------------------------------------

    _SUB_AGENT_HISTORY_TAIL = 4

    async def _run_sql_stage(
        self,
        question: str,
        stage: PlanStage,
        context: AgentContext,
    ) -> StageResult:
        scoped = replace(
            context,
            chat_history=context.chat_history[-self._SUB_AGENT_HISTORY_TAIL :]
            if context.chat_history
            else [],
        )
        try:
            sql_result = await self._sql.run(scoped, question=question)
        except (AgentRetryableError, AgentFatalError, AgentError) as e:
            return StageResult(stage_id=stage.stage_id, status="error", error=str(e))
        except RETRYABLE_LLM_ERRORS as e:
            return StageResult(stage_id=stage.stage_id, status="error", error=e.user_message)

        if sql_result.status == "error":
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=sql_result.error or "SQL agent error",
                token_usage=sql_result.token_usage,
            )

        qr: QueryResult | None = getattr(sql_result, "results", None)
        query: str | None = getattr(sql_result, "query", None)
        summary = self._summarize_query_result(query, qr)

        return StageResult(
            stage_id=stage.stage_id,
            status="success",
            query=query,
            query_result=qr,
            summary=summary,
            token_usage=sql_result.token_usage,
        )

    async def _run_knowledge_stage(
        self,
        question: str,
        stage: PlanStage,
        context: AgentContext,
    ) -> StageResult:
        scoped = replace(
            context,
            chat_history=context.chat_history[-self._SUB_AGENT_HISTORY_TAIL :]
            if context.chat_history
            else [],
        )
        try:
            kb_result = await self._knowledge.run(scoped, question=question)
        except (AgentRetryableError, AgentFatalError, AgentError) as e:
            return StageResult(stage_id=stage.stage_id, status="error", error=str(e))
        except RETRYABLE_LLM_ERRORS as e:
            return StageResult(stage_id=stage.stage_id, status="error", error=e.user_message)

        answer = getattr(kb_result, "answer", "")
        return StageResult(
            stage_id=stage.stage_id,
            status="success" if answer else "error",
            summary=answer,
            error=None if answer else "Knowledge agent returned empty answer",
            token_usage=kb_result.token_usage,
        )

    async def _run_analysis_stage(
        self,
        question: str,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
    ) -> StageResult:
        """Use the LLM to analyse data from previous stages."""
        messages = [
            Message(
                role="system",
                content=(
                    "You are a data analysis assistant. Analyse the data provided "
                    "from previous pipeline stages and produce the requested output."
                ),
            ),
            Message(role="user", content=question),
        ]
        try:
            resp = await self._llm.complete(
                messages=messages,
                preferred_provider=context.preferred_provider,
                model=context.model,
            )
        except Exception as exc:
            return StageResult(stage_id=stage.stage_id, status="error", error=str(exc))

        return StageResult(
            stage_id=stage.stage_id,
            status="success",
            summary=resp.content or "",
            token_usage=resp.usage or {},
        )

    async def _run_mcp_stage(
        self,
        question: str,
        stage: PlanStage,
        context: AgentContext,
    ) -> StageResult:
        """Query an external MCP data source."""
        if self._mcp_source is None:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error="MCP source agent not configured for this pipeline",
            )
        try:
            result = await self._mcp_source.run(
                replace(
                    context,
                    chat_history=context.chat_history[-4:] if context.chat_history else [],
                ),
                question=question,
            )
            answer = getattr(result, "answer", "") or ""
            return StageResult(
                stage_id=stage.stage_id,
                status="success" if getattr(result, "status", "") != "error" else "error",
                summary=answer,
                token_usage=getattr(result, "token_usage", {}),
                error=getattr(result, "error", None),
            )
        except Exception as exc:
            logger.exception("MCP stage '%s' failed", stage.stage_id)
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=str(exc),
            )

    async def _run_process_data_stage(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext | None = None,
    ) -> StageResult:
        """Apply a data-processing operation to the most recent stage with a QueryResult."""
        wf_id = context.workflow_id if context else ""

        source_qr: QueryResult | None = None
        for dep_id in reversed(stage.depends_on):
            dep_result = stage_ctx.get_result(dep_id)
            if dep_result and dep_result.query_result and dep_result.query_result.rows:
                source_qr = dep_result.query_result
                break

        if source_qr is None:
            for prev in reversed(stage_ctx.plan.stages):
                if prev.stage_id == stage.stage_id:
                    break
                sr = stage_ctx.get_result(prev.stage_id)
                if sr and sr.query_result and sr.query_result.rows:
                    source_qr = sr.query_result
                    break

        if source_qr is None:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error="No query result available from previous stages to process.",
            )

        params = self._parse_process_data_params(stage, source_qr)
        operation = params.get("operation", "unknown")

        await self._tracker.emit(
            wf_id,
            "thinking",
            "in_progress",
            f"Processing data: {operation} on {source_qr.row_count} rows…",
        )

        try:
            processor = get_data_processor()
            processed = processor.process(source_qr, params.pop("operation"), params)
        except (ValueError, Exception) as exc:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=str(exc),
            )

        await self._tracker.emit(
            wf_id,
            "thinking",
            "completed",
            processed.summary[:120],
        )

        return StageResult(
            stage_id=stage.stage_id,
            status="success",
            query_result=processed.query_result,
            summary=processed.summary,
        )

    @staticmethod
    def _parse_process_data_params(stage: PlanStage, source_qr: QueryResult) -> dict[str, Any]:
        """Extract operation params from ``input_context`` (JSON) with fallback heuristics."""
        params: dict[str, Any] = {}
        if stage.input_context:
            try:
                parsed = json.loads(stage.input_context)
                if isinstance(parsed, dict):
                    params = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        if "operation" not in params:
            desc_lower = (stage.description + " " + (stage.input_context or "")).lower()
            if "filter" in desc_lower:
                params["operation"] = "filter_data"
            elif "phone" in desc_lower or "dial" in desc_lower or "e.164" in desc_lower:
                params["operation"] = "phone_to_country"
            elif "aggregat" in desc_lower or "group" in desc_lower:
                params["operation"] = "aggregate_data"
            else:
                logger.warning(
                    "Could not determine process_data operation from input_context, "
                    "defaulting to filter_data"
                )
                params["operation"] = "filter_data"

        needs_column = params["operation"] in (
            "ip_to_country",
            "phone_to_country",
            "filter_data",
        )
        if needs_column and "column" not in params:
            keyword = "ip" if params["operation"] == "ip_to_country" else "phone"
            for col in source_qr.columns:
                if keyword in col.lower():
                    params["column"] = col
                    break
            if "column" not in params and source_qr.columns:
                params["column"] = source_qr.columns[0]

        if "aggregations" in params and isinstance(params["aggregations"], dict):
            params["aggregations"] = list(params["aggregations"].items())

        return params

    async def _synthesize_stage(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
    ) -> StageResult:
        """Produce the final user-facing answer from all stages."""
        answer = await self._synthesize(stage_ctx, context)
        return StageResult(
            stage_id=stage.stage_id,
            status="success",
            summary=answer,
        )

    async def _synthesize(
        self,
        stage_ctx: StageContext,
        context: AgentContext,
    ) -> str:
        """Combine all stage results into a final answer."""
        parts: list[str] = [
            f"Original question: {stage_ctx.plan.question}\n",
        ]
        for stage in stage_ctx.plan.stages:
            sr = stage_ctx.get_result(stage.stage_id)
            if not sr:
                continue
            parts.append(f"Stage '{stage.stage_id}' ({stage.description}):")
            parts.append(f"  Status: {sr.status}")
            if sr.query:
                parts.append(f"  SQL: {sr.query}")
            if sr.query_result:
                parts.append(f"  Columns: {sr.query_result.columns}")
                parts.append(f"  Rows: {sr.query_result.row_count}")
                if sr.query_result.rows:
                    parts.append(f"  Data sample: {sr.query_result.rows[:10]}")
            if sr.summary:
                parts.append(f"  Summary: {sr.summary}")
            parts.append("")

        for fb in stage_ctx.user_feedback:
            fb_stage = fb.get("stage_id")
            fb_text = fb.get("feedback_text", "")
            parts.append(f"User feedback (stage {fb_stage}): {fb_text}")

        messages = [
            Message(
                role="system",
                content=(
                    "You are a data analyst. Synthesise the stage results below into "
                    "a clear, complete answer. Include a summary table if the user "
                    "requested one. Provide analytical commentary where appropriate."
                ),
            ),
            Message(role="user", content="\n".join(parts)),
        ]
        try:
            resp = await self._llm.complete(
                messages=messages,
                preferred_provider=context.preferred_provider,
                model=context.model,
            )
            return resp.content or ""
        except Exception:
            logger.exception("Synthesis LLM call failed")
            lines = []
            for s in stage_ctx.plan.stages:
                sr = stage_ctx.get_result(s.stage_id)
                lines.append(f"Stage {s.stage_id}: {sr.summary if sr else 'N/A'}")
            return "Pipeline completed all stages but synthesis failed. " + "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_query_result(query: str | None, qr: QueryResult | None) -> str:
        if not qr:
            return "No results."
        parts = []
        if query:
            parts.append(f"Query: {query}")
        parts.append(f"Columns: {qr.columns}")
        parts.append(f"Rows returned: {qr.row_count}")
        if qr.rows:
            parts.append(f"Sample (first 5): {qr.rows[:5]}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # SSE event emitters
    # ------------------------------------------------------------------

    async def _emit_plan(self, wf_id: str, plan: ExecutionPlan) -> None:
        await self._tracker.emit(
            wf_id,
            "plan",
            "started",
            f"Execution plan with {len(plan.stages)} stages",
            stages=[
                {
                    "id": s.stage_id,
                    "description": s.description,
                    "tool": s.tool,
                    "checkpoint": s.checkpoint,
                }
                for s in plan.stages
            ],
        )

    async def _emit_stage_start(self, wf_id: str, stage: PlanStage, idx: int, total: int) -> None:
        await self._tracker.emit(
            wf_id,
            "stage_start",
            "started",
            stage.description,
            stage_id=stage.stage_id,
            index=idx,
            total=total,
        )

    async def _emit_stage_result(self, wf_id: str, stage: PlanStage, result: StageResult) -> None:
        extra: dict[str, Any] = {
            "stage_id": stage.stage_id,
            "status": result.status,
        }
        if result.query_result:
            extra["row_count"] = result.query_result.row_count
            extra["columns"] = result.query_result.columns
            extra["sample_rows"] = result.query_result.rows[:5]
        await self._tracker.emit(
            wf_id, "stage_result", result.status, result.summary[:200], **extra
        )

    async def _emit_stage_validation(
        self, wf_id: str, stage: PlanStage, validation: StageValidationOutcome
    ) -> None:
        await self._tracker.emit(
            wf_id,
            "stage_validation",
            "passed" if validation.passed else "failed",
            validation.error_summary or "OK",
            stage_id=stage.stage_id,
            passed=validation.passed,
            warnings=validation.warnings,
            errors=validation.errors,
        )

    async def _emit_stage_complete(
        self, wf_id: str, stage: PlanStage, result: StageResult, idx: int
    ) -> None:
        await self._tracker.emit(
            wf_id,
            "stage_complete",
            "completed",
            f"Stage {idx + 1} complete",
            stage_id=stage.stage_id,
            index=idx,
        )

    async def _emit_checkpoint(self, wf_id: str, stage: PlanStage, result: StageResult) -> None:
        preview: dict[str, Any] = {"stage_id": stage.stage_id}
        if result.query_result:
            preview["columns"] = result.query_result.columns
            preview["row_count"] = result.query_result.row_count
            preview["sample_rows"] = result.query_result.rows[:10]
        preview["summary"] = result.summary

        await self._tracker.emit(
            wf_id,
            "checkpoint",
            "waiting",
            f"Checkpoint: {stage.description}",
            **preview,
        )


# ------------------------------------------------------------------
# Result container
# ------------------------------------------------------------------


class _StageExecutorResult:
    """Returned by ``StageExecutor.execute()``."""

    def __init__(
        self,
        *,
        status: str,
        stage_ctx: StageContext,
        final_answer: str = "",
        checkpoint_stage: PlanStage | None = None,
        checkpoint_result: StageResult | None = None,
        failed_stage: PlanStage | None = None,
        failed_validation: StageValidationOutcome | None = None,
    ) -> None:
        self.status = status  # completed | checkpoint | stage_failed
        self.stage_ctx = stage_ctx
        self.final_answer = final_answer
        self.checkpoint_stage = checkpoint_stage
        self.checkpoint_result = checkpoint_result
        self.failed_stage = failed_stage
        self.failed_validation = failed_validation
