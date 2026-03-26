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
        "Use after query_database when you need to transform or enrich raw "
        "data before continuing analysis. You can chain multiple process_data "
        "calls sequentially."
    ),
    parameters=[
        ToolParameter(
            name="operation",
            type="string",
            description="Processing operation to apply",
            enum=[
                "ip_to_country",
                "phone_to_country",
                "aggregate_data",
                "filter_data",
            ],
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
            name="description",
            type="string",
            description="What you want to achieve with this processing step",
            required=False,
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
            enum=["yes_no", "multiple_choice", "numeric_range", "free_text"],
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
) -> list[Tool]:
    """Return the meta-tools available to the orchestrator."""
    tools: list[Tool] = []
    if has_connection:
        tools.append(QUERY_DATABASE_TOOL)
        tools.append(PROCESS_DATA_TOOL)
        tools.append(MANAGE_RULES_TOOL)
        tools.append(ASK_USER_TOOL)
    if has_knowledge_base:
        tools.append(SEARCH_CODEBASE_TOOL)
    if has_mcp_sources:
        from app.agents.tools.mcp_tools import QUERY_MCP_SOURCE_TOOL

        tools.append(QUERY_MCP_SOURCE_TOOL)
    return tools
