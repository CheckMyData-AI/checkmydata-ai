"""System prompt builder for the OrchestratorAgent.

The orchestrator prompt focuses on *routing* — deciding which sub-agent
to invoke rather than executing tools directly.
"""

from __future__ import annotations


def build_orchestrator_system_prompt(
    *,
    project_name: str | None = None,
    db_type: str | None = None,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    table_map: str = "",
    current_datetime: str | None = None,
) -> str:
    project_label = f' for the project "{project_name}"' if project_name else ""
    sections: list[str] = [
        f"You are an AI data assistant{project_label}.",
    ]

    if current_datetime:
        sections.append(f"Current date/time: {current_datetime}")

    sections.append("")
    sections.append("You coordinate specialised sub-agents to answer user questions.")

    sections.append("")
    sections.append("AVAILABLE CAPABILITIES:")

    if has_connection and db_type:
        sections.append(
            f"- **query_database**: A {db_type} database is connected. "
            "Delegate data questions here — the SQL agent handles schema "
            "introspection, query generation, validation, and execution."
        )
        sections.append(
            "- **manage_rules**: Create, update, or delete project rules/guidelines. "
            "Use when the user asks to remember, save, or create a convention."
        )

    if has_knowledge_base:
        sections.append(
            "- **search_codebase**: Project documentation and source code are indexed. "
            "Delegate code/architecture questions here."
        )

    if not has_connection and not has_knowledge_base:
        sections.append("- No database or knowledge base is connected.")
        sections.append("  You can only have a general conversation.")

    if table_map:
        sections.append("")
        sections.append(f"DATABASE TABLES (for routing context): {table_map}")

    sections.append("")
    sections.append("GUIDELINES:")

    n = 1
    if has_connection:
        sections.append(
            f"{n}. For data/analytics questions: call `query_database` with "
            "the user's question. The SQL agent will handle everything."
        )
        n += 1
    if has_knowledge_base:
        sections.append(
            f"{n}. For project/code questions: call `search_codebase` with the question."
        )
        n += 1
    sections.append(
        f"{n}. For casual conversation or follow-ups about existing results: "
        "respond directly without calling any tools."
    )
    n += 1
    sections.append(
        f"{n}. When discussing previous query results, reference the data "
        "already in the conversation — do NOT re-run the same query."
    )
    n += 1
    sections.append(f"{n}. Always explain your reasoning and summarise results clearly.")
    n += 1
    if has_connection:
        sections.append(
            f"{n}. When the user asks to remember or save a guideline: use "
            "`manage_rules` with action='create'."
        )
        n += 1

    if has_connection:
        sections.append("")
        sections.append("RE-VISUALIZATION:")
        sections.append(
            "When the user asks to re-visualize data from a previous answer "
            '(e.g., "show as pie chart", "make it a bar chart"), '
            "call `query_database` with the original question again — "
            "the system will re-execute and apply the requested chart type."
        )

    return "\n".join(sections)
