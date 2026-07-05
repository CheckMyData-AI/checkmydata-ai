"""Schema-context rendering extracted from SQLAgent (W0 decomposition; Wave 4 owner).

Wave 4 will extend this module with comments, indexes, and enum labels
(DBIDX-D8). Keeping it separate means Wave 4 never has to edit sql_agent.py
core.
"""

from __future__ import annotations

import json as _json
from typing import Any

from app.config import settings


def format_table_context(
    db_entry: Any,
    schema_table: Any,
    sync_entry: Any,
    knowledge: Any,
) -> str:
    """Render a single table's schema context block for the SQL agent prompt.

    Pure function — no side effects, no I/O.  All arguments may be None
    except *db_entry*.
    """
    parts: list[str] = [f"### {db_entry.table_name}"]
    if db_entry.business_description:
        parts.append(f"{db_entry.business_description}")
    if db_entry.row_count is not None:
        parts.append(f"Rows: ~{db_entry.row_count:,}")

    if schema_table:
        cols_lines: list[str] = []
        for col in schema_table.columns:
            pk = " PK" if col.is_primary_key else ""
            null = " NULL" if col.is_nullable else ""
            sort = " [sort key]" if getattr(col, "is_sort_key", False) else ""
            comment_suffix = f" — {col.comment}" if getattr(col, "comment", None) else ""
            line = f"  {col.name}: {col.data_type}{pk}{null}{sort}{comment_suffix}"
            enum_labels = getattr(col, "enum_labels", None)
            if enum_labels:
                labels_str = ", ".join(str(v) for v in enum_labels[:20])
                line += f" | Allowed: [{labels_str}]"
            cols_lines.append(line)
        parts.append("Columns:\n" + "\n".join(cols_lines))
        if schema_table.foreign_keys:
            fk_lines = [
                f"  {fk.column} -> {fk.references_table}.{fk.references_column}"
                for fk in schema_table.foreign_keys
            ]
            parts.append("FKs:\n" + "\n".join(fk_lines))
        indexes = getattr(schema_table, "indexes", None)
        if indexes:
            idx_lines = []
            for idx in indexes:
                u = "UNIQUE " if idx.is_unique else ""
                idx_lines.append(f"  {u}{idx.name}({', '.join(idx.columns)})")
            parts.append("Indexes:\n" + "\n".join(idx_lines))

    dv_json = getattr(db_entry, "column_distinct_values_json", "{}")
    try:
        distinct = _json.loads(dv_json) if dv_json else {}
    except (_json.JSONDecodeError, TypeError):
        distinct = {}
    if distinct:
        dv_lines = []
        for col, vals in distinct.items():
            vals_str = " | ".join(str(v) for v in vals[:20])
            dv_lines.append(f"  {col}: [{vals_str}]")
        parts.append("Distinct values:\n" + "\n".join(dv_lines))

    if sync_entry and sync_entry.conversion_warnings:
        parts.append(f"WARNINGS: {sync_entry.conversion_warnings}")

    col_notes_merged: dict[str, str] = {}
    try:
        db_notes = _json.loads(db_entry.column_notes_json) if db_entry.column_notes_json else {}
    except (_json.JSONDecodeError, TypeError):
        db_notes = {}
    if db_notes and isinstance(db_notes, dict):
        col_notes_merged.update(db_notes)
    if sync_entry:
        try:
            raw = sync_entry.column_sync_notes_json
            sync_notes = _json.loads(raw) if raw else {}
        except (_json.JSONDecodeError, TypeError):
            sync_notes = {}
        if sync_notes and isinstance(sync_notes, dict):
            for col, note in sync_notes.items():
                existing = col_notes_merged.get(col, "")
                if existing and note not in existing:
                    col_notes_merged[col] = f"{existing}; {note}"
                else:
                    col_notes_merged[col] = note
    if col_notes_merged:
        notes_lines = [f"  {c}: {n}" for c, n in col_notes_merged.items()]
        parts.append("Column notes:\n" + "\n".join(notes_lines))

    numeric_notes_raw = getattr(db_entry, "numeric_format_notes", "{}")
    try:
        numeric_notes = _json.loads(numeric_notes_raw) if numeric_notes_raw else {}
    except (_json.JSONDecodeError, TypeError):
        numeric_notes = {}
    if numeric_notes and isinstance(numeric_notes, dict):
        nf_lines = [f"  {c}: {n}" for c, n in numeric_notes.items()]
        parts.append("Numeric formats:\n" + "\n".join(nf_lines))

    if sync_entry and sync_entry.business_logic_notes:
        parts.append(f"Business logic: {sync_entry.business_logic_notes[:200]}")

    if sync_entry and sync_entry.query_recommendations:
        parts.append(f"Query tips: {sync_entry.query_recommendations}")
    if db_entry.query_hints:
        parts.append(f"Query hints: {db_entry.query_hints}")

    if knowledge:
        tbl_lower = db_entry.table_name.lower()
        for _name, entity in knowledge.entities.items():
            if entity.table_name and entity.table_name.lower() == tbl_lower:
                if entity.read_queries or entity.write_queries:
                    parts.append(
                        f"Code usage: {entity.read_queries} reads, {entity.write_queries} writes"
                    )
                # M5: graph-derived lineage helps the SQL agent reason
                # about required filters (e.g. ``status != 'archived'``
                # for a customer-facing list endpoint) and which call
                # paths are read vs write surfaces.
                graph_callers = getattr(entity, "graph_callers", None) or []
                if graph_callers and settings.lineage_enabled:
                    # Top 5 by descending confidence — graph_callers is
                    # already sorted by GraphDBBridge.
                    top = graph_callers[:5]
                    parts.append("Lineage (top callers):")
                    for ref in top:
                        kind = ref.get("endpoint_kind", "unknown")
                        op = ref.get("op_kind", "unknown")
                        name = ref.get("caller_name", "?")
                        conf = float(ref.get("confidence", 0.0))
                        parts.append(f"  - {name} [{kind}/{op}] (conf={conf:.2f})")
                break
    parts.append("")
    return "\n".join(parts)
