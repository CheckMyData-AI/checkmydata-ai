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

    sections.append("")
    sections.append("WORKFLOW:")

    if has_db_index:
        sections.append(
            "1. Call `get_query_context` with the user's question — it returns "
            "table schemas, column types, distinct enum values, conversion "
            "warnings, and rules in one compact bundle."
        )
        sections.append("2. Write and execute the query with `execute_query`.")
    else:
        sections.append(
            "1. Check the schema with `get_schema_info` (overview first, "
            "then table_detail for relevant tables)."
        )
        sections.append("2. Load rules with `get_custom_rules`.")
        sections.append("3. Write and execute the query with `execute_query`.")

    sections.append("")
    sections.append(
        "CURRENT QUESTION FOCUS:\n"
        "Focus on the specific question provided. Conversation history, if any, "
        "is for reference during query repair — do not treat prior queries or "
        "results as new tasks to execute."
    )

    sections.append("")
    sections.append("RULES:")
    sections.append("- Only generate SELECT / read-only queries unless explicitly asked otherwise.")
    sections.append("- Use the EXACT table and column names from the schema.")
    sections.append("- Use Foreign Key relationships for correct JOINs.")
    sections.append("- Include LIMIT (default 100) for potentially large result sets.")
    sections.append("- Explain your query logic briefly in the explanation parameter.")

    if has_db_index:
        stale_note = ""
        if db_index_stale:
            stale_note = (
                " WARNING: The DB index is older than the configured TTL — "
                "verify against `get_schema_info`."
            )
        sections.append(
            f"- DB Index is available (`get_db_index`). "
            f"`get_schema_info` is always live truth; DB index is a snapshot.{stale_note}"
        )

    if has_code_db_sync:
        sections.append(
            "- Code-DB sync is available (`get_sync_context`). "
            "Check it for data format conventions before writing queries."
        )

    if has_learnings:
        sections.append(
            "- Agent learnings are available (`get_agent_learnings`). "
            "Review them before writing queries to avoid repeating mistakes."
        )

    sections.append("- When you discover something new about the data, use `record_learning`.")
    sections.append(
        "- Use `read_notes` to check session notes before writing queries. "
        "Use `write_note` to record observations about data patterns."
    )

    sections.append("")
    sections.append(
        "SELF-IMPROVEMENT PROTOCOL:\n"
        "1. Before writing a query, check session notes for relevant observations.\n"
        "2. After getting results, run a quick sanity check:\n"
        "   - Are numeric values in a reasonable range?\n"
        "   - Do aggregations make sense (sum of parts ≈ total)?\n"
        "   - Are there unexpected NULLs or zeros?\n"
        "3. When you discover something new about the data (column format, "
        "business logic, naming convention), ALWAYS use `write_note` to record it.\n"
        "4. If you find a discrepancy between what the code says and what the "
        "data shows, record it as a note with category 'data_observation'.\n"
        "5. If a previous session note is relevant, apply it and confirm it still holds."
    )

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
