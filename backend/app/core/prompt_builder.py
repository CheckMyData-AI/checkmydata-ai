"""Build dynamic system prompts for the conversational agent.

The prompt is assembled based on what resources are available
(database connection, knowledge base, etc.) so the LLM knows
exactly which tools it can invoke and how to behave.
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


def build_agent_system_prompt(
    *,
    project_name: str | None = None,
    db_type: str | None = None,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    has_db_index: bool = False,
    db_index_stale: bool = False,
    has_code_db_sync: bool = False,
    has_learnings: bool = False,
    table_map: str = "",
    learnings_prompt: str = "",
) -> str:
    """Assemble a role-aware, capability-aware system prompt."""

    project_label = f' for the project "{project_name}"' if project_name else ""
    sections: list[str] = [
        f"You are an AI data assistant{project_label}.",
        "",
        "You can help users by:",
        "- Having general conversations about data and the project",
    ]

    if has_knowledge_base:
        sections.append("- Answering questions about the project's codebase and documentation")

    if has_connection:
        sections.extend(
            [
                "- Querying databases to find and analyse data",
                "- Explaining query results, spotting patterns, and visualising data",
            ]
        )

    sections.append("")
    sections.append("AVAILABLE CAPABILITIES:")

    if has_connection and db_type:
        sections.append(
            f"- Database: A {db_type} database is connected.  Use `execute_query` to run queries."
        )
        sections.append(
            "- Schema: Use `get_schema_info` to explore the database structure "
            "before writing queries."
        )
        sections.append(
            "- Rules: Use `get_custom_rules` to load project-specific guidelines "
            "before building queries."
        )
        sections.append(
            "- Rules Management: Use `manage_custom_rules` to create, update, or "
            "delete project rules when the user asks to remember a guideline, "
            "save a convention, or modify an existing rule. Call `get_custom_rules` "
            "first to see existing rules (with their IDs) before updating or deleting."
        )
        if has_db_index:
            stale_note = ""
            if db_index_stale:
                stale_note = (
                    " WARNING: The DB index is older than the configured TTL. "
                    "Results may be outdated — always verify against `get_schema_info`."
                )
            sections.append(
                "- DB Index: A pre-analyzed database index is available. "
                "Use `get_db_index` to see which tables are active, their "
                "business purpose, relevance scores, and query hints. "
                "NOTE: `get_schema_info` is always live truth; `get_db_index` "
                "is a pre-analyzed snapshot that may lag behind schema changes."
                + stale_note
            )

    if has_connection and has_code_db_sync:
        sections.append(
            "- Code-DB Sync: Synchronized code analysis is available. "
            "Use `get_sync_context` BEFORE writing queries to understand "
            "data format conventions (money in cents vs dollars, date "
            "formats, enum values, soft-delete patterns). This prevents "
            "common data-interpretation errors."
        )

    if has_connection and has_learnings:
        sections.append(
            "- Agent Learnings: You have accumulated lessons from previous "
            "interactions with this database. Use `get_agent_learnings` to "
            "review them before writing queries. Use `record_learning` when "
            "you discover something new about the data that should be "
            "remembered (e.g., which table has correct data, column format "
            "quirks, required filter conditions)."
        )

    if has_knowledge_base:
        sections.append(
            "- Knowledge Base: Project documentation is indexed.  "
            "Use `search_knowledge` to find relevant information."
        )
        sections.append(
            "- Entity Info: Structured entity/model data is available.  "
            "Use `get_entity_info` to look up models, columns, relationships, "
            "enums, and table usage from the codebase."
        )

    if not has_connection and not has_knowledge_base:
        sections.append("- No database or knowledge base is connected.")
        sections.append("  You can only have a general conversation.")

    if table_map:
        sections.append("")
        sections.append(f"DATABASE TABLES: {table_map}")

    if learnings_prompt:
        sections.append("")
        sections.append(learnings_prompt)

    sections.append("")
    sections.append("GUIDELINES:")

    guideline_num = 1
    if has_connection:
        if has_db_index:
            sections.append(
                f"{guideline_num}. For data questions: call `get_query_context` with "
                "the user's question — it returns table schemas, column types, "
                "distinct enum values, conversion warnings, and rules in one "
                "compact bundle. Then write and run the query with `execute_query`."
            )
        else:
            sections.append(
                f"{guideline_num}. For data questions: "
                "check the schema with `get_schema_info`, load rules with "
                "`get_custom_rules`, then build and run a query with `execute_query`."
            )
        guideline_num += 1
    if has_knowledge_base:
        sections.append(
            f"{guideline_num}. For project/code questions: use `search_knowledge` "
            "to find relevant documentation."
        )
        guideline_num += 1
    sections.append(
        f"{guideline_num}. For casual conversation or follow-up discussion: "
        "respond directly without calling any tools."
    )
    guideline_num += 1
    sections.append(
        f"{guideline_num}. When discussing previous query results, reference "
        "the data already present in the conversation — do not re-run the "
        "same query."
    )
    guideline_num += 1
    sections.append(
        f"{guideline_num}. Always explain your reasoning.  If you run a query, "
        "explain what it does and summarise the results clearly."
    )
    guideline_num += 1
    if has_connection:
        sections.append(
            f"{guideline_num}. Only generate SELECT / read-only queries unless "
            "the user explicitly asks for a write operation."
        )
        guideline_num += 1
        sections.append(
            f"{guideline_num}. Include LIMIT (default 100) for potentially large result sets."
        )
        guideline_num += 1
        sections.append(
            f"{guideline_num}. When the user asks to remember, save, or create a "
            "rule/guideline about data handling, column conventions, or query "
            "patterns: use `manage_custom_rules` with action='create'. For "
            "updates/deletions, first call `get_custom_rules` to find the rule ID."
        )
        guideline_num += 1
        sections.append(
            f"{guideline_num}. When you discover something new about the database "
            "(e.g., a table has incorrect data, a column stores values in a "
            "non-obvious format, or a required filter like `deleted_at IS NULL`), "
            "use `record_learning` to save it for future sessions."
        )

    if has_connection:
        sections.append("")
        sections.append("RE-VISUALIZATION:")
        sections.append(
            "When the user asks to re-visualize data from a previous answer "
            '(e.g., "show as pie chart", "make it a bar chart"), '
            "look at the [Context] block in the prior assistant message to find "
            "the SQL query and columns. Re-execute the same query and use the "
            "recommend_visualization tool to suggest the requested chart type."
        )

    if has_connection and db_type:
        hints = DIALECT_HINTS.get(db_type)
        if hints:
            sections.append("")
            sections.append(f"SQL DIALECT HINTS ({db_type}):")
            sections.append(hints)

    return "\n".join(sections)
