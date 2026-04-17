"""Smart retry decision logic — determines whether and how to retry."""

from __future__ import annotations

from app.connectors.base import SchemaInfo
from app.core.query_validation import NON_RETRYABLE_ERRORS, QueryError, QueryErrorType
from app.core.schema_hints import (
    find_similar_columns,
    find_similar_tables,
    get_table_detail,
    list_all_tables_summary,
)


class RetryStrategy:
    """Decides whether to retry and generates repair hints per error type."""

    def should_retry(
        self,
        error: QueryError,
        attempt: int,
        max_attempts: int,
    ) -> bool:
        if error.error_type in NON_RETRYABLE_ERRORS:
            return False
        if attempt >= max_attempts:
            return False
        if not error.is_retryable:
            return False
        return True

    def get_repair_hints(
        self,
        error: QueryError,
        schema: SchemaInfo,
    ) -> str:
        """Build repair context from the raw error and schema.

        Provides the error details and relevant schema context directly,
        letting the LLM decide how to fix the query.
        """
        et = error.error_type
        parts: list[str] = [
            f"Error type: {et.value}",
            f"Error message: {error.message}",
            f"Database dialect: {schema.db_type}",
        ]

        if et == QueryErrorType.COLUMN_NOT_FOUND:
            target = error.suggested_columns[0] if error.suggested_columns else ""
            if target and isinstance(target, str):
                similar = find_similar_columns(target, schema)
                if similar:
                    parts.append("Similar columns in schema:")
                    for tbl, col, score in similar[:5]:
                        parts.append(f"  - {tbl}.{col} (similarity: {score})")
                    for tbl, col, _ in similar[:2]:
                        parts.append(get_table_detail(tbl, schema))

        elif et == QueryErrorType.TABLE_NOT_FOUND:
            target = error.suggested_tables[0] if error.suggested_tables else ""
            if target and isinstance(target, str):
                similar_tables = find_similar_tables(target, schema)
                if similar_tables:
                    parts.append("Similar tables in schema:")
                    for tbl, score in similar_tables:
                        parts.append(f"  - {tbl} (similarity: {score})")
            parts.append(list_all_tables_summary(schema))

        return "\n".join(parts)
