"""ValidationLoop — orchestrates the pre/execute/post/repair cycle."""

from __future__ import annotations

import logging
import time

from app.connectors.base import BaseConnector, ConnectionConfig, SchemaInfo
from app.core.context_enricher import ContextEnricher
from app.core.error_classifier import ErrorClassifier
from app.core.explain_validator import ExplainValidator
from app.core.post_validator import PostValidator
from app.core.pre_validator import PreValidator
from app.core.query_repair import QueryRepairer
from app.core.query_validation import (
    QueryAttempt,
    QueryError,
    QueryErrorType,
    ValidationConfig,
    ValidationLoopResult,
)
from app.core.retry_strategy import RetryStrategy
from app.core.safety import SafetyGuard, SafetyLevel
from app.core.workflow_tracker import WorkflowTracker

logger = logging.getLogger(__name__)


class ValidationLoop:
    """Ties together pre-validation, execution, post-validation, and repair."""

    def __init__(
        self,
        config: ValidationConfig,
        error_classifier: ErrorClassifier,
        context_enricher: ContextEnricher,
        query_repairer: QueryRepairer,
        retry_strategy: RetryStrategy,
        tracker: WorkflowTracker,
    ):
        self._config = config
        self._classifier = error_classifier
        self._enricher = context_enricher
        self._repairer = query_repairer
        self._retry = retry_strategy
        self._tracker = tracker

    async def execute(
        self,
        initial_query: str,
        initial_explanation: str,
        connector: BaseConnector,
        schema: SchemaInfo,
        question: str,
        project_id: str,
        workflow_id: str,
        connection_config: ConnectionConfig,
        chat_history: list | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> ValidationLoopResult:
        pre_validator = (
            PreValidator(schema)
            if self._config.enable_schema_validation else None
        )
        explain_validator = (
            ExplainValidator(self._config.explain_row_warning_threshold)
            if self._config.enable_explain else None
        )
        post_validator = PostValidator()
        safety_level = (
            SafetyLevel.READ_ONLY
            if connection_config.is_read_only
            else SafetyLevel.ALLOW_DML
        )
        safety_guard = SafetyGuard(level=safety_level)

        current_query = initial_query
        current_explanation = initial_explanation
        attempts: list[QueryAttempt] = []
        all_warnings: list[str] = []

        for attempt_num in range(1, self._config.max_retries + 1):
            attempt = QueryAttempt(
                attempt_number=attempt_num,
                query=current_query,
                explanation=current_explanation,
            )
            t0 = time.monotonic()

            # --- Pre-validation ---
            if pre_validator:
                async with self._tracker.step(
                    workflow_id, "pre_validate",
                    f"Schema validation (attempt {attempt_num}/{self._config.max_retries})",
                ):
                    pre_result = pre_validator.validate(current_query, schema.db_type)

                if not pre_result.is_valid and pre_result.error:
                    attempt.error = pre_result.error
                    attempt.elapsed_ms = (time.monotonic() - t0) * 1000
                    attempts.append(attempt)

                    repair = await self._try_repair(
                        pre_result.error, question, current_query,
                        attempts, project_id, workflow_id, schema,
                        connection_config, attempt_num,
                        chat_history=chat_history,
                        preferred_provider=preferred_provider,
                        model=model,
                    )
                    if repair is None:
                        return self._fail(
                            current_query, current_explanation,
                            attempts, pre_result.error, all_warnings,
                        )
                    current_query, current_explanation = repair
                    continue

                all_warnings.extend(pre_result.warnings)

            # --- Safety check ---
            async with self._tracker.step(workflow_id, "safety_check", "Validating query safety"):
                safety_result = safety_guard.validate(current_query, connection_config.db_type)

            if not safety_result.is_safe:
                attempt.error = QueryError(
                    error_type=QueryErrorType.PERMISSION_DENIED,
                    message=f"Blocked: {safety_result.reason}",
                    raw_error=safety_result.reason,
                    is_retryable=False,
                )
                attempt.elapsed_ms = (time.monotonic() - t0) * 1000
                attempts.append(attempt)
                return self._fail(
                    current_query, current_explanation, attempts,
                    attempt.error, all_warnings,
                )

            # --- EXPLAIN dry-run ---
            if explain_validator:
                async with self._tracker.step(
                    workflow_id, "explain_check",
                    f"EXPLAIN dry-run (attempt {attempt_num}/{self._config.max_retries})",
                ):
                    explain_result = await explain_validator.validate(
                        connector, current_query, schema.db_type,
                    )

                if not explain_result.is_valid and explain_result.error:
                    attempt.error = explain_result.error
                    attempt.elapsed_ms = (time.monotonic() - t0) * 1000
                    attempts.append(attempt)

                    repair = await self._try_repair(
                        explain_result.error, question, current_query,
                        attempts, project_id, workflow_id, schema,
                        connection_config, attempt_num,
                        chat_history=chat_history,
                        preferred_provider=preferred_provider,
                        model=model,
                    )
                    if repair is None:
                        return self._fail(
                            current_query, current_explanation,
                            attempts, explain_result.error,
                            all_warnings,
                        )
                    current_query, current_explanation = repair
                    continue

                all_warnings.extend(explain_result.warnings)

            # --- Execute ---
            async with self._tracker.step(
                workflow_id, "execute_query",
                f"Running query (attempt {attempt_num}/{self._config.max_retries})",
            ):
                try:
                    results = await connector.execute_query(current_query)
                except Exception as exc:
                    logger.warning("execute_query raised: %s", exc)
                    classified = self._classifier.classify(
                        str(exc), connection_config.db_type,
                    )
                    attempt.error = classified
                    attempt.elapsed_ms = (time.monotonic() - t0) * 1000
                    attempts.append(attempt)

                    repair = await self._try_repair(
                        classified, question, current_query,
                        attempts, project_id, workflow_id, schema,
                        connection_config, attempt_num,
                        chat_history=chat_history,
                        preferred_provider=preferred_provider,
                        model=model,
                    )
                    if repair is None:
                        return self._fail(
                            current_query, current_explanation,
                            attempts, classified, all_warnings,
                        )
                    current_query, current_explanation = repair
                    continue

            attempt.results = results
            attempt.elapsed_ms = (time.monotonic() - t0) * 1000

            # --- Post-validation ---
            async with self._tracker.step(
                workflow_id, "post_validate",
                f"Result validation (attempt {attempt_num}/{self._config.max_retries})",
            ):
                post_result = post_validator.validate(
                    results, current_query, schema, self._config,
                )

            if not post_result.is_valid and post_result.error:
                attempt.error = post_result.error
                attempts.append(attempt)

                repair = await self._try_repair(
                    post_result.error, question, current_query,
                    attempts, project_id, workflow_id, schema,
                    connection_config, attempt_num,
                    chat_history=chat_history,
                    preferred_provider=preferred_provider,
                    model=model,
                )
                if repair is None:
                    return self._fail(
                        current_query, current_explanation,
                        attempts, post_result.error, all_warnings,
                    )
                current_query, current_explanation = repair
                continue

            all_warnings.extend(post_result.warnings)

            # --- Success ---
            attempts.append(attempt)
            await self._tracker.emit(
                workflow_id, "execute_query", "completed",
                f"{results.row_count} rows in {results.execution_time_ms:.0f}ms",
            )
            return ValidationLoopResult(
                success=True,
                query=current_query,
                explanation=current_explanation,
                results=results,
                attempts=attempts,
                total_attempts=attempt_num,
                warnings=all_warnings,
            )

        return self._fail(
            current_query, current_explanation, attempts,
            attempts[-1].error if attempts else None, all_warnings,
        )

    async def _try_repair(
        self,
        error: QueryError,
        question: str,
        failed_query: str,
        attempts: list[QueryAttempt],
        project_id: str,
        workflow_id: str,
        schema: SchemaInfo,
        connection_config: ConnectionConfig,
        current_attempt: int,
        chat_history: list | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> tuple[str, str] | None:
        """Attempt to repair. Returns (new_query, new_explanation) or None."""
        if not self._retry.should_retry(error, current_attempt, self._config.max_retries):
            return None

        async with self._tracker.step(
            workflow_id, "error_classify",
            f"Analyzing error: {error.error_type.value}",
        ):
            pass  # classification already done, step is for UI feedback

        async with self._tracker.step(
            workflow_id, "query_repair",
            f"Repairing query (attempt {current_attempt}/{self._config.max_retries})",
        ):
            repair_context = await self._enricher.build_repair_context(
                error=error,
                original_question=question,
                failed_query=failed_query,
                attempt_history=attempts,
                project_id=project_id,
            )
            repair_result = await self._repairer.repair(
                repair_context=repair_context,
                db_type=connection_config.db_type,
                chat_history=chat_history,
                preferred_provider=preferred_provider,
                model=model,
            )

        if repair_result.get("error") or not repair_result.get("query"):
            logger.warning(
                "Query repair failed: %s", repair_result.get("error"),
            )
            return None

        return repair_result["query"], repair_result.get("explanation", "")

    @staticmethod
    def _fail(
        query: str,
        explanation: str,
        attempts: list[QueryAttempt],
        error: QueryError | None,
        warnings: list[str],
    ) -> ValidationLoopResult:
        return ValidationLoopResult(
            success=False,
            query=query,
            explanation=explanation,
            attempts=attempts,
            total_attempts=len(attempts),
            final_error=error,
            warnings=warnings,
        )
