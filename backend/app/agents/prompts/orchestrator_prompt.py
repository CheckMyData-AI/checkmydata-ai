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
    has_mcp_sources: bool = False,
    table_map: str = "",
    current_datetime: str | None = None,
    project_overview: str | None = None,
    recent_learnings: str | None = None,
    custom_rules: str = "",
) -> str:
    project_label = f' for the project "{project_name}"' if project_name else ""
    sections: list[str] = [
        f"You are an AI data assistant{project_label}.",
    ]

    if current_datetime:
        sections.append(f"Current date/time: {current_datetime}")

    sections.append("")
    sections.append("You coordinate specialized sub-agents to answer user questions.")

    sections.append("")
    sections.append("AVAILABLE CAPABILITIES:")

    if has_connection and db_type:
        sections.append(
            f"- **query_database**: A {db_type} database is connected. "
            "Delegate data questions here — the SQL agent handles schema "
            "introspection, query generation, validation, and execution."
        )
        sections.append(
            "- **process_data**: Enrich, aggregate, or filter query results in memory. "
            "Operations:\n"
            "  • ip_to_country — convert IP addresses to country codes/names "
            "(requires 'column')\n"
            "  • phone_to_country — convert phone numbers to country via dialing "
            "code prefix E.164 (requires 'column')\n"
            "  • aggregate_data — group rows by columns and compute statistics "
            "(requires 'group_by' and 'aggregations'). Multiple functions per "
            "column allowed, e.g. 'amount:sum,amount:avg,user_id:count_distinct,"
            "*:count'. Supported: count, count_distinct, sum, avg, min, max, "
            "median. Optional: sort_by (column), order (asc/desc)\n"
            "  • filter_data — filter rows by column value (requires 'column', "
            "optional 'op', 'value', 'exclude_empty')\n"
            "  You can chain multiple process_data calls sequentially: first "
            "enrich (e.g. ip_to_country), then filter (e.g. exclude Unknown), "
            "then aggregate. Each call operates on the result of the previous "
            "one. IMPORTANT: call process_data ONE AT A TIME — do NOT issue "
            "multiple process_data calls in parallel."
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

    if has_mcp_sources:
        sections.append(
            "- **query_mcp_source**: External data sources are connected via MCP. "
            "Use this for questions that require data from external APIs or "
            "services not available in the primary database."
        )

    sections.append(
        "- **ask_user**: Ask the user a structured clarification question. "
        "Use when the request is ambiguous, you need to verify assumptions, "
        "or confirm data accuracy before proceeding."
    )

    if not has_connection and not has_knowledge_base:
        sections.append("- No database or knowledge base is connected.")
        sections.append("  You can only have a general conversation.")

    if table_map:
        sections.append("")
        sections.append(f"DATABASE TABLES (for routing context): {table_map}")

    if custom_rules:
        sections.append("")
        sections.append(
            "CUSTOM RULES & BUSINESS LOGIC (apply these when formulating questions for sub-agents):"
        )
        sections.append(custom_rules)
        sections.append("")
        sections.append(
            "RULE FRESHNESS CHECK:\n"
            "After receiving query results, compare them against the custom rules above.\n"
            "If results contain values, patterns, or data structures that contradict "
            "or are missing from the rules:\n"
            "1. Inform the user about the discrepancy (e.g. 'Query results show "
            "status=archived which is not mentioned in the rule').\n"
            "2. Suggest updating the rule via `manage_rules` with action='update'.\n"
            "3. If the user confirms, update the rule with the corrected information."
        )

    if project_overview:
        sections.append("")
        sections.append("PROJECT KNOWLEDGE OVERVIEW:")
        sections.append(project_overview)
        sections.append(
            "\nUse this overview to understand what data is available and how it "
            "should be queried. Route questions to the appropriate sub-agent "
            "based on this context."
        )

    if recent_learnings:
        sections.append("")
        sections.append(recent_learnings)
        sections.append(
            "\nThese learnings reflect verified patterns and corrections from "
            "previous interactions. Use them to improve routing accuracy."
        )

    sections.append("")
    sections.append(
        "PRINCIPLES:\n"
        "- Focus on the latest user message. Conversation history is reference only.\n"
        "- Reuse data already in the conversation — avoid redundant tool calls.\n"
        "- Prefer fewer, comprehensive tool calls over many narrow ones.\n"
        "- Chain `process_data` calls sequentially; other tools can run in parallel.\n"
        "- When the request is ambiguous, use `ask_user` to clarify before proceeding.\n"
        "- The system injects budget status per iteration. When budget is running "
        "low, synthesize your answer from whatever data you have collected so far.\n"
        "- Explain your reasoning and summarize results clearly."
    )

    return "\n".join(sections)


# ------------------------------------------------------------------
# Minimal direct-response prompt (no tools, no schema)
# ------------------------------------------------------------------


def build_direct_response_prompt(
    *,
    project_name: str | None = None,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    has_mcp_sources: bool = False,
) -> str:
    """Build a minimal system prompt for direct conversational responses."""
    project_label = f' for the project "{project_name}"' if project_name else ""

    caps: list[str] = []
    if has_connection:
        caps.append("query connected databases")
    if has_knowledge_base:
        caps.append("search indexed project code and documentation")
    if has_mcp_sources:
        caps.append("query external MCP data sources")
    if not caps:
        caps.append("have general conversations")

    cap_str = ", ".join(caps)

    return (
        f"You are a friendly AI data assistant{project_label}.\n"
        f"Your capabilities include: {cap_str}.\n"
        "Respond to the user's message naturally and concisely. "
        "Do not call any tools."
    )
