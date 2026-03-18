"""Schema-aware pre-execution query validator."""

from __future__ import annotations

import logging

from app.connectors.base import SchemaInfo
from app.core.query_validation import QueryError, QueryErrorType, ValidationResult
from app.core.schema_hints import find_similar_columns, find_similar_tables
from app.core.sql_parser import extract_column_table_pairs, extract_tables

logger = logging.getLogger(__name__)


class PreValidator:
    """Validates a generated query against a known schema BEFORE execution."""

    def __init__(self, schema: SchemaInfo):
        self._schema = schema
        self._table_names: set[str] = {t.name.lower() for t in schema.tables}
        self._column_map: dict[str, set[str]] = {
            t.name.lower(): {c.name.lower() for c in t.columns} for t in schema.tables
        }

    def validate(self, query: str, db_type: str) -> ValidationResult:
        if db_type.lower() in {"mongodb", "mongo"}:
            return ValidationResult(is_valid=True)

        tables = extract_tables(query)
        for table in tables:
            if table.lower() not in self._table_names:
                logger.debug("Pre-validation failed: table '%s' not found in schema", table)
                similar = find_similar_tables(table, self._schema)
                suggestions = [s[0] for s in similar]
                return ValidationResult(
                    is_valid=False,
                    error=QueryError(
                        error_type=QueryErrorType.TABLE_NOT_FOUND,
                        message=f"Table '{table}' does not exist in schema",
                        raw_error=f"pre_validation: table '{table}' not found",
                        is_retryable=True,
                        suggested_tables=suggestions,
                        schema_hint=self._build_table_list_hint(),
                    ),
                )

        pairs = extract_column_table_pairs(query)
        table_alias_map = self._resolve_aliases(query, tables)

        for col, qualifier in pairs:
            if qualifier:
                resolved_table = table_alias_map.get(
                    qualifier.lower(),
                    qualifier.lower(),
                )
                if resolved_table in self._column_map:
                    if col.lower() not in self._column_map[resolved_table]:
                        logger.debug(
                            "Pre-validation failed: column '%s' not in table '%s'",
                            col,
                            resolved_table,
                        )
                        similar = find_similar_columns(col, self._schema)
                        table_cols = [s[1] for s in similar if s[0].lower() == resolved_table]
                        all_suggestions = table_cols or [s[1] for s in similar[:3]]
                        return ValidationResult(
                            is_valid=False,
                            error=QueryError(
                                error_type=QueryErrorType.COLUMN_NOT_FOUND,
                                message=(
                                    f"Column '{col}' does not exist in table '{resolved_table}'"
                                ),
                                raw_error=(
                                    f"pre_validation: column '{col}' not in '{resolved_table}'"
                                ),
                                is_retryable=True,
                                suggested_columns=all_suggestions,
                                schema_hint=self._build_column_hint(resolved_table),
                            ),
                        )

        if len(tables) > 1:
            ambig = self._check_ambiguous_columns(pairs, tables, table_alias_map)
            if ambig:
                return ambig

        return ValidationResult(is_valid=True)

    def _resolve_aliases(
        self,
        query: str,
        tables: list[str],
    ) -> dict[str, str]:
        """Build alias -> real_table map from query."""
        import re

        alias_map: dict[str, str] = {}
        for table in tables:
            pattern = re.compile(
                rf"\b{re.escape(table)}\s+(?:AS\s+)?(\w+)\b",
                re.IGNORECASE,
            )
            for m in pattern.finditer(query):
                alias = m.group(1).lower()
                if alias.upper() not in {
                    "ON",
                    "WHERE",
                    "SET",
                    "JOIN",
                    "INNER",
                    "LEFT",
                    "RIGHT",
                    "CROSS",
                    "GROUP",
                    "ORDER",
                    "LIMIT",
                    "HAVING",
                    "UNION",
                    "SELECT",
                    "FROM",
                }:
                    alias_map[alias] = table.lower()
            alias_map[table.lower()] = table.lower()
        return alias_map

    def _check_ambiguous_columns(
        self,
        pairs: list[tuple[str, str | None]],
        tables: list[str],
        alias_map: dict[str, str],
    ) -> ValidationResult | None:
        unqualified = [col for col, qualifier in pairs if qualifier is None]
        for col in unqualified:
            found_in: list[str] = []
            for table in tables:
                real = alias_map.get(table.lower(), table.lower())
                cols = self._column_map.get(real, set())
                if col.lower() in cols:
                    found_in.append(real)
            if len(found_in) > 1:
                return ValidationResult(
                    is_valid=False,
                    error=QueryError(
                        error_type=QueryErrorType.AMBIGUOUS_COLUMN,
                        message=(
                            f"Column '{col}' is ambiguous — found in tables: {', '.join(found_in)}"
                        ),
                        raw_error=f"pre_validation: ambiguous column '{col}'",
                        is_retryable=True,
                        schema_hint=(f"Qualify the column as table.{col} to resolve."),
                    ),
                )
        return None

    def _build_table_list_hint(self) -> str:
        return "Available tables: " + ", ".join(sorted(self._table_names))

    def _build_column_hint(self, table_name: str) -> str:
        cols = self._column_map.get(table_name, set())
        return f"Columns in '{table_name}': " + ", ".join(sorted(cols))
