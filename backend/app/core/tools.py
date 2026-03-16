"""Tool definitions for the conversational agent.

Each tool is declared as a ``Tool`` object compatible with the LLM
provider's function-calling schema.  The agent loop exposes these
to the LLM, which decides when (and whether) to invoke them.
"""

from app.llm.base import Tool, ToolParameter

EXECUTE_QUERY_TOOL = Tool(
    name="execute_query",
    description=(
        "Execute a SQL or MongoDB query against the connected database. "
        "The query goes through validation (schema check, safety guard, "
        "EXPLAIN dry-run) and automatic repair on failure."
    ),
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="The SQL query or MongoDB JSON spec to execute",
        ),
        ToolParameter(
            name="explanation",
            type="string",
            description="Brief explanation of what this query does and why",
        ),
    ],
)

SEARCH_KNOWLEDGE_TOOL = Tool(
    name="search_knowledge",
    description=(
        "Search the project knowledge base (indexed Git repository, "
        "documentation, and codebase) using semantic search.  Returns "
        "the most relevant document chunks."
    ),
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="Natural-language search query",
        ),
        ToolParameter(
            name="max_results",
            type="integer",
            description="Maximum number of results to return (default 5)",
            required=False,
        ),
    ],
)

GET_SCHEMA_INFO_TOOL = Tool(
    name="get_schema_info",
    description=(
        "Retrieve database schema information.  Use scope='overview' for "
        "a list of all tables with column counts and row estimates, or "
        "scope='table_detail' with a table_name for full column "
        "definitions, foreign keys, and indexes."
    ),
    parameters=[
        ToolParameter(
            name="scope",
            type="string",
            description="Level of detail to return",
            enum=["overview", "table_detail"],
        ),
        ToolParameter(
            name="table_name",
            type="string",
            description="Table name (required when scope is 'table_detail')",
            required=False,
        ),
    ],
)

GET_CUSTOM_RULES_TOOL = Tool(
    name="get_custom_rules",
    description=(
        "Load project-specific rules and business-logic guidelines.  "
        "Call this before building queries so that naming conventions, "
        "metric formulas, and data-handling rules are respected."
    ),
    parameters=[],
)


def get_available_tools(
    *,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
) -> list[Tool]:
    """Return the subset of tools available given the current context."""
    tools: list[Tool] = []
    if has_connection:
        tools.append(EXECUTE_QUERY_TOOL)
        tools.append(GET_SCHEMA_INFO_TOOL)
        tools.append(GET_CUSTOM_RULES_TOOL)
    if has_knowledge_base:
        tools.append(SEARCH_KNOWLEDGE_TOOL)
    return tools
