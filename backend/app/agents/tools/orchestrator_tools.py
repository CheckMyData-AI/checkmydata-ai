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
        tools.append(MANAGE_RULES_TOOL)
    if has_knowledge_base:
        tools.append(SEARCH_CODEBASE_TOOL)
    if has_mcp_sources:
        from app.agents.tools.mcp_tools import QUERY_MCP_SOURCE_TOOL

        tools.append(QUERY_MCP_SOURCE_TOOL)
    return tools
