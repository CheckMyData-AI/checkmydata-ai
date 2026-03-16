"""Lightweight regex-based SQL parser for pre-validation.

Not a full parser — handles common patterns for table/column extraction.
"""

from __future__ import annotations

import re

_STRIP_STRINGS = re.compile(r"'[^']*'|\"[^\"]*\"")
_STRIP_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)

_FROM_JOIN = re.compile(
    r"\b(?:FROM|JOIN|INNER\s+JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|CROSS\s+JOIN"
    r"|LEFT\s+OUTER\s+JOIN|RIGHT\s+OUTER\s+JOIN|FULL\s+JOIN"
    r"|FULL\s+OUTER\s+JOIN)\s+"
    r"(`?\w+`?(?:\.\w+)?)",
    re.IGNORECASE,
)

_INTO_TABLE = re.compile(r"\bINTO\s+(`?\w+`?)", re.IGNORECASE)

_QUALIFIED_COL = re.compile(r"\b(`?\w+`?)\.(`?\w+`?)\b")

_SUBQUERY = re.compile(r"\(\s*SELECT\b", re.IGNORECASE)

_CTE = re.compile(r"\bWITH\s+(\w+)\s+AS\s*\(", re.IGNORECASE)

_AGGREGATIONS = re.compile(
    r"\b(COUNT|SUM|AVG|MIN|MAX|GROUP_CONCAT|STRING_AGG|ARRAY_AGG)\s*\(",
    re.IGNORECASE,
)

_ALIAS_PATTERN = re.compile(
    r"\b(\w+)\s+(?:AS\s+)?(\w+)\s*(?:ON|WHERE|GROUP|ORDER|LIMIT|HAVING|$|,)",
    re.IGNORECASE,
)


def _clean(sql: str) -> str:
    sql = _STRIP_COMMENTS.sub(" ", sql)
    sql = _STRIP_STRINGS.sub("''", sql)
    return sql


def _unquote(name: str) -> str:
    return name.strip("`").strip('"').strip("'")


def extract_tables(query: str) -> list[str]:
    """Extract table names from FROM, JOIN, and INTO clauses."""
    cleaned = _clean(query)
    tables: list[str] = []

    for match in _FROM_JOIN.finditer(cleaned):
        raw = match.group(1)
        parts = raw.split(".")
        table = _unquote(parts[-1])
        tables.append(table)

    for match in _INTO_TABLE.finditer(cleaned):
        tables.append(_unquote(match.group(1)))

    cte_names = {m.group(1).lower() for m in _CTE.finditer(cleaned)}
    tables = [t for t in tables if t.lower() not in cte_names]

    seen: set[str] = set()
    deduped: list[str] = []
    for t in tables:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    return deduped


def extract_column_table_pairs(
    query: str,
) -> list[tuple[str, str | None]]:
    """Extract column references as (column, table_or_alias_or_None).

    Handles qualified refs like ``users.id`` and unqualified refs.
    """
    cleaned = _clean(query)
    pairs: list[tuple[str, str | None]] = []

    for match in _QUALIFIED_COL.finditer(cleaned):
        table_or_alias = _unquote(match.group(1))
        col = _unquote(match.group(2))
        if table_or_alias.upper() in {
            "FROM", "JOIN", "WHERE", "SELECT", "ON", "AND", "OR",
            "SET", "INTO", "ORDER", "GROUP", "HAVING", "LIMIT", "AS",
            "INNER", "LEFT", "RIGHT", "CROSS", "FULL", "OUTER",
            "NOT", "IN", "IS", "NULL", "BETWEEN", "LIKE", "EXISTS",
            "CASE", "WHEN", "THEN", "ELSE", "END",
        }:
            continue
        pairs.append((col, table_or_alias))

    return pairs


def extract_columns(query: str) -> list[str]:
    """Extract column names (deduplicated, lowercased)."""
    pairs = extract_column_table_pairs(query)
    seen: set[str] = set()
    result: list[str] = []
    for col, _ in pairs:
        key = col.lower()
        if key not in seen and key != "*":
            seen.add(key)
            result.append(col)
    return result


def detect_subqueries(query: str) -> bool:
    cleaned = _clean(query)
    return bool(_SUBQUERY.search(cleaned))


def detect_aggregations(query: str) -> list[str]:
    cleaned = _clean(query)
    return [m.group(1).upper() for m in _AGGREGATIONS.finditer(cleaned)]
