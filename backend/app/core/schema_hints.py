"""Utilities for extracting targeted schema information for error repair."""

from __future__ import annotations

import difflib

from app.connectors.base import SchemaInfo


def find_similar_columns(
    target: str,
    schema: SchemaInfo,
    threshold: float = 0.6,
    max_results: int = 5,
) -> list[tuple[str, str, float]]:
    """Find columns similar to *target* across all tables.

    Returns ``(table_name, column_name, score)`` sorted by score desc.
    """
    candidates: list[tuple[str, str, float]] = []
    target_lower = target.lower()
    for table in schema.tables:
        col_names = [c.name for c in table.columns]
        matches = difflib.get_close_matches(
            target_lower,
            [c.lower() for c in col_names],
            n=3,
            cutoff=threshold,
        )
        for m in matches:
            original = next(c for c in col_names if c.lower() == m)
            score = difflib.SequenceMatcher(None, target_lower, m).ratio()
            candidates.append((table.name, original, round(score, 3)))

    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates[:max_results]


def find_similar_tables(
    target: str,
    schema: SchemaInfo,
    threshold: float = 0.6,
    max_results: int = 5,
) -> list[tuple[str, float]]:
    """Find tables whose name is similar to *target*."""
    target_lower = target.lower()
    table_names = [t.name for t in schema.tables]
    matches = difflib.get_close_matches(
        target_lower,
        [t.lower() for t in table_names],
        n=max_results,
        cutoff=threshold,
    )
    results: list[tuple[str, float]] = []
    for m in matches:
        original = next(t for t in table_names if t.lower() == m)
        score = difflib.SequenceMatcher(None, target_lower, m).ratio()
        results.append((original, round(score, 3)))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def get_table_detail(table_name: str, schema: SchemaInfo) -> str:
    """Full markdown description of a single table."""
    table = next(
        (t for t in schema.tables if t.name.lower() == table_name.lower()),
        None,
    )
    if not table:
        return f"Table '{table_name}' not found in schema."

    lines = [f"## {table.name}"]
    if table.comment:
        lines.append(f"  {table.comment}")
    if table.row_count is not None:
        lines.append(f"  Rows: ~{table.row_count:,}")

    lines.append("| Column | Type | PK | Nullable | Comment |")
    lines.append("|--------|------|----|----------|---------|")
    for col in table.columns:
        pk = "PK" if col.is_primary_key else ""
        nullable = "YES" if col.is_nullable else "NO"
        comment = col.comment or ""
        lines.append(
            f"| {col.name} | {col.data_type} | {pk} | {nullable} | {comment} |"
        )

    if table.foreign_keys:
        fks = "; ".join(
            f"{fk.column} -> {fk.references_table}.{fk.references_column}"
            for fk in table.foreign_keys
        )
        lines.append(f"  FK: {fks}")

    if table.indexes:
        idxs = "; ".join(
            f"{'UNIQUE ' if i.is_unique else ''}{i.name}({', '.join(i.columns)})"
            for i in table.indexes
        )
        lines.append(f"  Indexes: {idxs}")

    return "\n".join(lines)


def get_related_tables(table_name: str, schema: SchemaInfo) -> list[str]:
    """Tables connected to *table_name* via foreign keys (outgoing + incoming)."""
    related: set[str] = set()
    name_lower = table_name.lower()

    for table in schema.tables:
        if table.name.lower() == name_lower:
            for fk in table.foreign_keys:
                related.add(fk.references_table)
        else:
            for fk in table.foreign_keys:
                if fk.references_table.lower() == name_lower:
                    related.add(table.name)

    return sorted(related)


def list_all_tables_summary(schema: SchemaInfo) -> str:
    """One-line summary per table for full table list context."""
    lines = ["Available tables:"]
    for t in schema.tables:
        col_count = len(t.columns)
        row_hint = f", ~{t.row_count:,} rows" if t.row_count is not None else ""
        lines.append(f"  - {t.name} ({col_count} columns{row_hint})")
    return "\n".join(lines)
