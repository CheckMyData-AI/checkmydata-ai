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
        et = error.error_type
        parts: list[str] = []

        if et == QueryErrorType.COLUMN_NOT_FOUND:
            target = error.suggested_columns[0] if error.suggested_columns else ""
            if target and isinstance(target, str):
                similar = find_similar_columns(target, schema)
                if similar:
                    parts.append("Did you mean one of these columns?")
                    for tbl, col, score in similar[:5]:
                        parts.append(f"  - {tbl}.{col} (similarity: {score})")
                for tbl, col, _ in similar[:2]:
                    parts.append(get_table_detail(tbl, schema))
            else:
                parts.append("A column was not found. Check the schema for correct names.")

        elif et == QueryErrorType.TABLE_NOT_FOUND:
            target = error.suggested_tables[0] if error.suggested_tables else ""
            if target and isinstance(target, str):
                similar = find_similar_tables(target, schema)
                if similar:
                    parts.append("Did you mean one of these tables?")
                    for tbl, score in similar:
                        parts.append(f"  - {tbl} (similarity: {score})")
            parts.append(list_all_tables_summary(schema))

        elif et == QueryErrorType.SYNTAX_ERROR:
            parts.append(
                "The query has a SQL syntax error. "
                "Review the query structure and ensure correct SQL syntax "
                f"for the {schema.db_type} dialect."
            )

        elif et == QueryErrorType.TYPE_MISMATCH:
            parts.append(
                "A type mismatch was detected. "
                "Verify column types and ensure comparisons use matching types. "
                "Check the schema for correct data types."
            )

        elif et == QueryErrorType.AMBIGUOUS_COLUMN:
            parts.append(
                "A column is ambiguous because it exists in multiple JOINed tables. "
                "Qualify the column with the table name, e.g. table.column."
            )

        elif et == QueryErrorType.TIMEOUT:
            parts.append(
                "The query timed out. Try:\n"
                "  - Add LIMIT 100\n"
                "  - Simplify aggregations\n"
                "  - Avoid correlated subqueries\n"
                "  - Use indexed columns in WHERE"
            )

        elif et == QueryErrorType.EMPTY_RESULT:
            parts.append(
                "The query returned 0 rows. Try:\n"
                "  - Broaden WHERE conditions\n"
                "  - Check date ranges\n"
                "  - Verify data exists in the target tables\n"
                "  - Remove overly restrictive filters"
            )

        elif et == QueryErrorType.EXPLAIN_WARNING:
            parts.append(
                "The EXPLAIN plan shows potential performance issues. "
                "Consider adding appropriate indexes or limiting results."
            )

        else:
            parts.append(f"An error occurred: {error.message}. Review the query and try again.")

        return "\n".join(parts)
