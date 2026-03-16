"""Post-execution validator — checks query results after DB execution."""

from __future__ import annotations

import logging

from app.connectors.base import QueryResult, SchemaInfo
from app.core.error_classifier import ErrorClassifier
from app.core.query_validation import QueryError, QueryErrorType, ValidationConfig, ValidationResult

logger = logging.getLogger(__name__)

_classifier = ErrorClassifier()

SLOW_QUERY_MS = 30_000


class PostValidator:
    """Validates query results after execution."""

    def validate(
        self,
        result: QueryResult,
        query: str,
        schema: SchemaInfo,
        config: ValidationConfig,
    ) -> ValidationResult:
        if result.error:
            classified = _classifier.classify(result.error, schema.db_type)
            return ValidationResult(is_valid=False, error=classified)

        warnings: list[str] = []

        if result.row_count == 0 and config.empty_result_retry:
            return ValidationResult(
                is_valid=False,
                error=QueryError(
                    error_type=QueryErrorType.EMPTY_RESULT,
                    message="Query returned 0 rows",
                    raw_error="post_validation: empty result set",
                    is_retryable=True,
                    schema_hint=(
                        "Consider broadening WHERE conditions, "
                        "checking date ranges, or verifying data exists."
                    ),
                ),
            )

        if result.row_count == 0:
            warnings.append("Query returned 0 rows.")

        timeout_ms = config.query_timeout_seconds * 1000
        if result.execution_time_ms > timeout_ms:
            warnings.append(
                f"Slow query: {result.execution_time_ms:.0f}ms "
                f"(threshold: {timeout_ms}ms)."
            )

        return ValidationResult(is_valid=True, warnings=warnings)
