"""System prompt builder for the SQL agent.

The SQL agent receives a focused prompt about database querying — dialect
hints, schema conventions, safety rules, and any pre-loaded context
(table map, learnings, DB index staleness).
"""

from __future__ import annotations

DIALECT_HINTS: dict[str, str] = {
    "mysql": (
        "- Use backtick quoting for identifiers: `table`.`column`\n"
        "- Date functions: DATE_FORMAT(), NOW(), CURDATE(), DATE_SUB()\n"
        "- String: CONCAT(), IFNULL(), GROUP_CONCAT()\n"
        "- Use LIMIT N at end (no OFFSET required unless paginating)"
    ),
    "postgres": (
        "- Use double-quote quoting for identifiers if needed\n"
        "- Date functions: NOW(), CURRENT_DATE, date_trunc(), age()\n"
        "- String: CONCAT(), COALESCE(), string_agg()\n"
        "- Use LIMIT N OFFSET M for pagination"
    ),
    "clickhouse": (
        "- ClickHouse SQL dialect: use toDate(), toDateTime(), formatDateTime()\n"
        "- Aggregations: countIf(), sumIf(), argMax(), argMin()\n"
        "- For large tables prefer approximate functions: uniq() over COUNT(DISTINCT)\n"
        "- Arrays: arrayJoin(), groupArray()\n"
        "- Use LIMIT N at end"
    ),
    "mongodb": (
        "- Generate a JSON query spec with keys: operation, collection, filter, "
        "projection, sort, limit\n"
        "- operation: find | aggregate | count\n"
        "- For aggregations use pipeline with $match, $group, $sort, $limit stages"
    ),
}


def build_sql_system_prompt(
    *,
    db_type: str | None = None,
    has_db_index: bool = False,
    db_index_stale: bool = False,
    has_code_db_sync: bool = False,
    has_learnings: bool = False,
    table_map: str = "",
    learnings_prompt: str = "",
    sync_conventions: str = "",
    sync_critical_warnings: str = "",
    current_datetime: str | None = None,
    notes_prompt: str = "",
    required_filters: str = "",
    column_value_mappings: str = "",
    custom_rules: str = "",
) -> str:
    """Assemble a SQL-focused system prompt for the SQL agent."""

    sections: list[str] = [
        "You are an expert SQL query agent. Your job is to gather schema "
        "context and build precise, efficient queries to answer data questions.",
    ]

    if current_datetime:
        sections.append(
            f"Current date/time: {current_datetime}. "
            "Use this for relative date calculations (yesterday, last week, last month, etc.)."
        )

    if custom_rules:
        sections.append("")
        sections.append("CUSTOM RULES & BUSINESS LOGIC (MANDATORY — always apply these):")
        sections.append(custom_rules)

    available_context: list[str] = []
    if table_map:
        available_context.append("table map")
    if custom_rules:
        available_context.append("custom rules")
    if learnings_prompt:
        available_context.append("agent learnings")
    if notes_prompt:
        available_context.append("session notes")
    if available_context:
        sections.append("")
        sections.append(
            f"The following context is already included below: "
            f"{', '.join(available_context)}. Do not re-fetch what is already here."
        )

    sections.append("")
    sections.append(
        "PRINCIPLES:\n"
        "- Generate only SELECT / read-only queries unless explicitly asked otherwise.\n"
        "- Use exact table and column names from the schema.\n"
        "- Include LIMIT for potentially large result sets.\n"
        "- Focus on the current question — conversation history is reference only.\n"
        "- Record new data observations with `write_note` or `record_learning`.\n"
        "- After getting results, sanity-check the data before returning it."
    )

    if has_db_index:
        stale_note = ""
        if db_index_stale:
            stale_note = " (WARNING: DB index may be stale — verify with `get_schema_info`)"
        sections.append(f"- DB Index available via `get_db_index`.{stale_note}")

    if has_code_db_sync:
        sections.append("- Code-DB sync available via `get_sync_context`.")

    if has_learnings:
        sections.append("- Agent learnings available via `get_agent_learnings`.")

    if sync_conventions or sync_critical_warnings:
        sections.append("")
        sections.append("CRITICAL DATA FORMAT RULES (from code-DB sync):")
        if sync_conventions:
            sections.append(sync_conventions)
        if sync_critical_warnings:
            sections.append(sync_critical_warnings)

    if required_filters:
        sections.append("")
        sections.append("REQUIRED QUERY FILTERS (from code analysis — ALWAYS apply these):")
        sections.append(required_filters)

    if column_value_mappings:
        sections.append("")
        sections.append("COLUMN VALUE MEANINGS:")
        sections.append(column_value_mappings)

    if table_map:
        sections.append("")
        sections.append(f"DATABASE TABLES: {table_map}")

    if learnings_prompt:
        sections.append("")
        sections.append(learnings_prompt)

    if notes_prompt:
        sections.append("")
        sections.append(notes_prompt)

    if db_type:
        hints = DIALECT_HINTS.get(db_type)
        if hints:
            sections.append("")
            sections.append(f"SQL DIALECT ({db_type}):")
            sections.append(hints)

    return "\n".join(sections)
