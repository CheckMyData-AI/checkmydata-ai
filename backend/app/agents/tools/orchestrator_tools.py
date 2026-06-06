"""Meta-tools available to the OrchestratorAgent.

These tools *delegate* to sub-agents — the orchestrator never executes
SQL or RAG queries directly.
"""

from app.llm.base import Tool, ToolParameter

QUERY_DATABASE_TOOL = Tool(
    name="query_database",
    description=(
        "Query the connected database to answer a data question. "
        "Handles SQL generation, validation, and execution internally."
    ),
    parameters=[
        ToolParameter(
            name="question",
            type="string",
            description="The data question to answer",
        ),
    ],
)

SEARCH_CODEBASE_TOOL = Tool(
    name="search_codebase",
    description=(
        "Search the indexed project codebase for information about "
        "code structure, ORM models, architecture, and documentation."
    ),
    parameters=[
        ToolParameter(
            name="question",
            type="string",
            description="The question about the codebase",
        ),
    ],
)

MANAGE_RULES_TOOL = Tool(
    name="manage_rules",
    description=(
        "Create, update, or delete a custom rule for this project. "
        "Use when the user asks to remember, save, or create a guideline "
        "about how to query the database, column conventions, metric formulas, "
        "or data-handling rules."
    ),
    parameters=[
        ToolParameter(
            name="action",
            type="string",
            description="Action to perform on the rule",
            enum=["create", "update", "delete"],
        ),
        ToolParameter(
            name="name",
            type="string",
            description="Short descriptive name for the rule (required for create)",
            required=False,
        ),
        ToolParameter(
            name="content",
            type="string",
            description="The rule content in markdown format (required for create and update)",
            required=False,
        ),
        ToolParameter(
            name="rule_id",
            type="string",
            description="ID of the rule to update or delete (required for update and delete)",
            required=False,
        ),
    ],
)


LIST_RULES_TOOL = Tool(
    name="list_rules",
    description=(
        "List existing custom rules for this project. "
        "Use to discover rule IDs before updating or deleting rules."
    ),
    parameters=[],
)


PROCESS_DATA_TOOL = Tool(
    name="process_data",
    description=(
        "Process and enrich the last query result with derived data. "
        "Available operations:\n"
        "• ip_to_country — convert IP addresses to country codes/names "
        "(requires 'column')\n"
        "• phone_to_country — convert phone numbers to country via dialing "
        "code prefix (requires 'column')\n"
        "• aggregate_data — group rows by columns and compute statistics "
        "(requires 'group_by' and 'aggregations'). Multiple functions per "
        "column allowed, e.g. 'amount:sum,amount:avg,*:count'. Supported "
        "functions: count, count_distinct, sum, avg, min, max, median\n"
        "• filter_data — filter rows by column value "
        "(requires 'column', optional 'op', 'value', 'exclude_empty')\n"
        "• cohort_window — correlate release dates with post-release metrics "
        "(7/14-day retention or revenue). Pass its structured params via "
        "'params_json' (release_dates, event_date_column, value_column or "
        "id_column, windows, metric)\n"
        "• passthrough — forward the rows unchanged (the default when no "
        "operation is given)\n"
        "Use after query_database when you need to transform or enrich raw "
        "data before continuing analysis. You can chain multiple process_data "
        "calls sequentially."
    ),
    parameters=[
        ToolParameter(
            name="operation",
            type="string",
            description="Processing operation to apply (defaults to passthrough if omitted)",
            enum=[
                "ip_to_country",
                "phone_to_country",
                "aggregate_data",
                "filter_data",
                "cohort_window",
                "passthrough",
            ],
            required=False,
        ),
        ToolParameter(
            name="column",
            type="string",
            description=(
                "Column name to process. Required for ip_to_country, "
                "phone_to_country, and filter_data."
            ),
            required=False,
        ),
        ToolParameter(
            name="group_by",
            type="string",
            description=("Comma-separated column names to group by (required for aggregate_data)"),
            required=False,
        ),
        ToolParameter(
            name="aggregations",
            type="string",
            description=(
                "Comma-separated col:func pairs for aggregate_data, e.g. "
                "'amount:sum,amount:avg,*:count'. Multiple functions per "
                "column allowed. Supported: count, count_distinct, sum, "
                "avg, min, max, median. (required for aggregate_data)"
            ),
            required=False,
        ),
        ToolParameter(
            name="sort_by",
            type="string",
            description=(
                "Column name to sort aggregation results by "
                "(optional for aggregate_data, default: group key ascending)"
            ),
            required=False,
        ),
        ToolParameter(
            name="order",
            type="string",
            description="Sort order: 'asc' or 'desc' (default: 'asc')",
            required=False,
        ),
        ToolParameter(
            name="op",
            type="string",
            description=(
                "Filter comparison operator for filter_data: eq, neq, "
                "contains, not_contains, gt, gte, lt, lte, in"
            ),
            required=False,
        ),
        ToolParameter(
            name="value",
            type="string",
            description=(
                "Value to compare against for filter_data. For 'in' op, "
                "comma-separated list of allowed values."
            ),
            required=False,
        ),
        ToolParameter(
            name="exclude_empty",
            type="string",
            description=(
                "Set to 'true' to exclude rows where column is null or empty (for filter_data)"
            ),
            required=False,
        ),
        ToolParameter(
            name="params_json",
            type="string",
            description=(
                "JSON object with structured params for advanced operations "
                "like cohort_window, e.g. "
                '{"release_dates": [{"tag": "v1.2.0", "date": "2026-01-15"}], '
                '"event_date_column": "created_at", "value_column": "amount", '
                '"windows": [7, 14], "metric": "revenue"}.'
            ),
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="What you want to achieve with this processing step",
            required=False,
        ),
    ],
)


ANALYZE_GIT_TOOL = Tool(
    name="analyze_git",
    description=(
        "Analyze the project's live Git repository: commit history, diffs, "
        "blame/authorship, who introduced a change, release tags, and commit "
        "review signals (Reviewed-by / Co-authored-by / merges). Use for "
        "questions about how code evolved, when something changed, or who "
        "changed it. Operates read-only on the local clone."
    ),
    parameters=[
        ToolParameter(
            name="question",
            type="string",
            description="The Git/history question to answer.",
        ),
        ToolParameter(
            name="details",
            type="string",
            description="Optional extra context (paths, time ranges, SHAs of interest).",
            required=False,
        ),
    ],
)

GET_RELEASE_TIMELINE_TOOL = Tool(
    name="get_release_timeline",
    description=(
        "Return the repository's release tags as a structured timeline (tag, "
        "commit SHA, date). Use this before correlating releases with database "
        "metrics (e.g. 7/14-day retention/revenue cohorts after each release)."
    ),
    parameters=[
        ToolParameter(
            name="tag_prefix",
            type="string",
            description="Optional tag prefix filter, e.g. 'v' or 'release-'.",
            required=False,
        ),
        ToolParameter(
            name="max_count",
            type="integer",
            description="Maximum number of releases to return (default 50).",
            required=False,
        ),
    ],
)

WRITE_CODE_NOTE_TOOL = Tool(
    name="write_code_note",
    description=(
        "Persist a durable finding about the codebase so it is remembered and "
        "surfaced in future questions (stored in project insight memory). Use "
        "after studying code/history when you learn an important, lasting fact."
    ),
    parameters=[
        ToolParameter(
            name="subject",
            type="string",
            description="What the note is about, e.g. 'path/to/file.py:function' or a SHA.",
        ),
        ToolParameter(
            name="note",
            type="string",
            description="The concise, factual finding to remember.",
        ),
    ],
)


ASK_USER_TOOL = Tool(
    name="ask_user",
    description=(
        "Ask the user a structured clarification question. Use when you need "
        "to verify data accuracy, confirm assumptions about metrics, or "
        "clarify ambiguous requests before proceeding."
    ),
    parameters=[
        ToolParameter(
            name="question",
            type="string",
            description="The question to ask the user",
        ),
        ToolParameter(
            name="question_type",
            type="string",
            description="Type of question",
            enum=["yes_no", "multiple_choice", "free_text"],
        ),
        ToolParameter(
            name="options",
            type="string",
            description=(
                "Comma-separated options for multiple_choice questions. Not needed for other types."
            ),
            required=False,
        ),
        ToolParameter(
            name="context",
            type="string",
            description="Additional context explaining why this question is being asked",
            required=False,
        ),
    ],
)


def get_orchestrator_tools(
    *,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    has_mcp_sources: bool = False,
    has_repo: bool = False,
) -> list[Tool]:
    """Return the meta-tools available to the orchestrator."""
    tools: list[Tool] = []
    if has_connection:
        tools.append(QUERY_DATABASE_TOOL)
        tools.append(PROCESS_DATA_TOOL)
        tools.append(MANAGE_RULES_TOOL)
        tools.append(LIST_RULES_TOOL)
    if has_knowledge_base:
        tools.append(SEARCH_CODEBASE_TOOL)
    if has_repo:
        tools.append(ANALYZE_GIT_TOOL)
        tools.append(GET_RELEASE_TIMELINE_TOOL)
        tools.append(WRITE_CODE_NOTE_TOOL)
    if has_mcp_sources:
        from app.agents.tools.mcp_tools import QUERY_MCP_SOURCE_TOOL

        tools.append(QUERY_MCP_SOURCE_TOOL)
    tools.append(ASK_USER_TOOL)
    return tools
