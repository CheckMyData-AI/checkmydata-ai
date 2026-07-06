"""System prompt builder for the OrchestratorAgent.

The orchestrator drives a unified tool-calling loop: it gathers data via
sub-agent tools and synthesizes the final answer (it is not a pure router).
"""

from __future__ import annotations


def build_orchestrator_system_prompt(
    *,
    project_name: str | None = None,
    db_type: str | None = None,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    has_mcp_sources: bool = False,
    has_repo: bool = False,
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
            "  • cohort_window — correlate release dates with post-release "
            "metrics (retention/revenue at 7/14 days). Use top-level keys: "
            "release_dates (list of {tag,date}), event_date_column, "
            "value_column (revenue) or id_column (retention), windows "
            "(e.g. [7,14]), metric. "
            "(A params_json wrapper object is also accepted for back-compat.)\n"
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

    if has_repo:
        sections.append(
            "- **analyze_git**: A local clone of the project's Git repository is "
            "available (read-only). Delegate questions about commit history, "
            "diffs, blame, releases/tags, authorship, file churn, and "
            "commit-trailer review signals (co-authors, reviewers, sign-offs, "
            "merge commits) here."
        )
        sections.append(
            "- **get_release_timeline**: Return a structured list of releases "
            "(tags) with dates and commit SHAs. Use this as the first stage when "
            "correlating releases with database metrics (e.g. release → SQL → "
            "cohort_window → synthesis for 7/14-day retention/revenue)."
        )
        sections.append(
            "- **write_code_note**: Persist a durable code finding to project "
            "memory (e.g. 'function X caches IP lookups in Redis'). Use after "
            "investigating the codebase so the insight is reused in future runs."
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
        "CURRENT TURN FOCUS:\n"
        "- The conversation history is READ-ONLY reference. Every question in it "
        "has ALREADY been answered — none of it is pending or unfinished work.\n"
        "- Your only task is the single latest user message. Never re-run, repeat, "
        "or reproduce a query/tool/task from an earlier turn to re-answer it.\n"
        "- If the latest message is a follow-up, reuse data already present in the "
        "conversation instead of re-querying.\n"
        "- This is a normal back-and-forth chat: respond to just the latest message "
        "and then wait for the next one."
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
        "- Explain your reasoning and summarize results clearly.\n"
        "- LANGUAGE: Reason and think internally in English, but write your FINAL "
        "answer to the user in the SAME language as the user's most recent message "
        "(e.g. a Russian question gets a Russian answer)."
    )

    return "\n".join(sections)


# ------------------------------------------------------------------
# Minimal direct-response prompt (no tools, no schema)
# ------------------------------------------------------------------


# C1: the direct-response LLM emits this sentinel (and nothing else) when a
# question routed "direct" actually needs fresh data — the orchestrator then
# re-routes it through the tool loop instead of answering without data.
NEEDS_DATA_SENTINEL = "__NEEDS_DATA__"


def build_direct_response_prompt(
    *,
    project_name: str | None = None,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    has_mcp_sources: bool = False,
    has_repo: bool = False,
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
    if has_repo:
        caps.append("analyze the project's Git history (commits, diffs, releases)")
    if not caps:
        caps.append("have general conversations")

    cap_str = ", ".join(caps)

    has_data_source = has_connection or has_knowledge_base or has_mcp_sources or has_repo
    escape_instruction = ""
    if has_data_source:
        # C1: re-route escape. Only answer directly for conversational/meta
        # questions or follow-ups about already-shown results. If answering
        # ACCURATELY needs fresh data, do not guess — emit the sentinel and the
        # system fetches the data via tools.
        escape_instruction = (
            "ONLY answer directly when the message is conversational/meta (greetings, "
            "thanks, clarifications) or a follow-up about results already shown. If "
            "answering accurately would require fresh data from your sources "
            f"({cap_str}), do NOT guess or fabricate — reply with EXACTLY "
            f"{NEEDS_DATA_SENTINEL} and nothing else; the system will then fetch the "
            "data with tools.\n"
        )

    return (
        f"You are a friendly AI data assistant{project_label}.\n"
        f"Your capabilities include: {cap_str}.\n"
        "Respond to the user's message naturally and concisely. "
        "Do not call any tools.\n"
        f"{escape_instruction}"
        "LANGUAGE: Reason internally in English, but write your reply in the "
        "SAME language as the user's most recent message."
    )
