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

    if has_knowledge_base:
        sections.append(
            "- Knowledge Base: Project documentation is indexed.  "
            "Use `search_knowledge` to find relevant information."
        )

    if not has_connection and not has_knowledge_base:
        sections.append("- No database or knowledge base is connected.")
        sections.append("  You can only have a general conversation.")

    sections.append("")
    sections.append("GUIDELINES:")

    guideline_num = 1
    if has_connection:
        sections.append(
            f"{guideline_num}. For data questions: first check the schema with "
            "`get_schema_info`, then load rules with `get_custom_rules`, then "
            "build and run a query with `execute_query`."
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

    if has_connection and db_type:
        hints = DIALECT_HINTS.get(db_type)
        if hints:
            sections.append("")
            sections.append(f"SQL DIALECT HINTS ({db_type}):")
            sections.append(hints)

    return "\n".join(sections)
