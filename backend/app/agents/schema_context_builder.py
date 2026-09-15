"""Schema-context rendering extracted from SQLAgent (W0 decomposition; Wave 4 owner).

Wave 4 will extend this module with comments, indexes, and enum labels
(DBIDX-D8). Keeping it separate means Wave 4 never has to edit sql_agent.py
core.
"""

from __future__ import annotations

import json as _json
from typing import Any

from app.config import settings


def nullability_suffix(is_nullable: bool | None) -> str:
    """The positive claim, or silence.

    This line read `" NULL" if col.is_nullable else ""` and was the ONE reader of
    four that survived a `None` unharmed — by accident, since `None` is falsy. It
    is spelled out so the next edit cannot break it silently, and so the other
    three readers have something to copy.
    """
    return " NULL" if is_nullable is True else ""


#: How many measured columns are worth spending prompt tokens on. The measurement is the
#: valuable half, but a wide table would otherwise fill the window with it.
_MEASURED_COLUMN_CAP = 15


def _as_fraction(value: Any) -> float | None:
    """A stored null rate as a number, or nothing.

    It arrives from JSON written by four connectors and has been seen as a float, as the
    string ``"0"``, and as absent. Returning ``None`` rather than swallowing the failure
    with a bare ``pass`` keeps the decision — say nothing about nulls — where a reader
    can see it, which is the whole argument this file makes about measurements.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def render_measured_facts(db_entry: Any) -> str:
    """What the indexer COUNTED about this table's columns, labelled as counted.

    B-12. Measured on production 2026-09-15: **139 of 214 indexed tables** carry hedged
    prose somewhere in their generated text — "possibly", "likely", "appears to" — and
    **209 of 214** carry real column statistics beside it. Guess and measurement sit in
    one block with nothing to tell them apart, so an agent reading "Currency code, likely
    USD" has no way to know that `distinct_count` for that column is 14.

    This module already rendered `column_distinct_values_json` under "Distinct values",
    and never rendered `column_stats_json` at all — so the agent saw the value LISTS,
    which the sampler had spent on identifier columns (`id`, `user_id`, `payment_id`),
    and not the counts, which is where the answer lives. For `purchases` that meant
    thirty payment UUIDs on screen and `currency: 14 distinct` nowhere.

    The word MEASURED is the point of the label, and it is the same one
    `apply_measured_corrections` (B-08) and the rival-table caveat (B-09) use. A reader
    who can see which claims were counted can discount the ones that were not; a reader
    who cannot must treat them alike, and the hedged ones read as facts.
    """
    raw = getattr(db_entry, "column_stats_json", "") or ""
    try:
        stats = _json.loads(raw) if raw else {}
    except (_json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(stats, dict) or not stats:
        return ""

    #: Ordered by how much the count narrows the column: a low distinct count is an
    #: enum and settles a question, a high one is an identifier and settles nothing.
    def _rank(item: tuple[str, Any]) -> tuple[int, str]:
        dc = (item[1] or {}).get("distinct_count") if isinstance(item[1], dict) else None
        return (dc if isinstance(dc, int) else 10**9, item[0])

    lines: list[str] = []
    for col, facts in sorted(stats.items(), key=_rank)[:_MEASURED_COLUMN_CAP]:
        if not isinstance(facts, dict):
            continue
        bits: list[str] = []
        dc = facts.get("distinct_count")
        if isinstance(dc, int):
            bits.append(f"{dc} distinct")
        lo, hi = facts.get("min"), facts.get("max")
        if lo is not None and hi is not None and str(lo) != str(hi):
            bits.append(f"range {lo} … {hi}")
        null_rate = _as_fraction(facts.get("null_rate"))
        if null_rate is not None and null_rate > 0:
            bits.append(f"{null_rate * 100:.0f}% NULL")
        if bits:
            lines.append(f"  {col}: {', '.join(bits)}")

    if not lines:
        return ""
    return "MEASURED (counted by the indexer, not inferred):\n" + "\n".join(lines)


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
    # B-12: what was counted goes above what was generated. The prose below hedges in
    # 65% of indexed tables and is indistinguishable from a measurement once both are in
    # the same block; put the measurement first and label it, and the hedge reads as one.
    measured = render_measured_facts(db_entry)
    if measured:
        parts.append(measured)
    if db_entry.business_description:
        parts.append(f"{db_entry.business_description}")
    if db_entry.row_count is not None:
        parts.append(f"Rows: ~{db_entry.row_count:,}")

    if schema_table:
        cols_lines: list[str] = []
        for col in schema_table.columns:
            pk = " PK" if col.is_primary_key else ""
            null = nullability_suffix(col.is_nullable)
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
