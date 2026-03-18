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

GET_ENTITY_INFO_TOOL = Tool(
    name="get_entity_info",
    description=(
        "Look up structured information about ORM entities, database tables, "
        "columns, relationships, enums, and service functions extracted from "
        "the project's codebase. Use scope='list' to list all known entities, "
        "scope='detail' with an entity_name for full column/relationship info, "
        "scope='table_map' for table usage statistics, or scope='enums' to "
        "list all extracted enum/constant definitions."
    ),
    parameters=[
        ToolParameter(
            name="scope",
            type="string",
            description="Level of detail to return",
            enum=["list", "detail", "table_map", "enums"],
        ),
        ToolParameter(
            name="entity_name",
            type="string",
            description="Entity/model name (required when scope is 'detail')",
            required=False,
        ),
    ],
)

GET_DB_INDEX_TOOL = Tool(
    name="get_db_index",
    description=(
        "Get the pre-analyzed database index with business descriptions, "
        "data patterns, relevance scores, and query hints for every table. "
        "Use scope='overview' for a summary of all tables, or "
        "scope='table_detail' with a table_name for deep per-table analysis "
        "including sample data and column notes."
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


GET_SYNC_CONTEXT_TOOL = Tool(
    name="get_sync_context",
    description=(
        "Get code-database synchronization notes: data format conventions, "
        "conversion warnings (e.g. money stored in cents vs dollars), "
        "column-level notes, and query recommendations derived from "
        "analyzing the codebase. Call this BEFORE writing queries to "
        "prevent data-interpretation errors."
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


GET_QUERY_CONTEXT_TOOL = Tool(
    name="get_query_context",
    description=(
        "Get a unified, query-ready context bundle for a specific question. "
        "Returns relevant table schemas, column types, foreign keys, "
        "distinct enum/status values, data format warnings (money in cents, "
        "date formats), applicable business rules, and code-level query patterns "
        "— all merged into a single compact response. "
        "Use this as the FIRST and PRIMARY tool before writing any SQL query."
    ),
    parameters=[
        ToolParameter(
            name="question",
            type="string",
            description="The user's data question to build context for",
        ),
        ToolParameter(
            name="table_names",
            type="string",
            description=(
                "Comma-separated table names to include. "
                "If omitted, tables are auto-detected from the question."
            ),
            required=False,
        ),
    ],
)


GET_AGENT_LEARNINGS_TOOL = Tool(
    name="get_agent_learnings",
    description=(
        "Get lessons the agent has learned from previous queries on this database. "
        "Returns table preferences, column usage notes, data format warnings, "
        "and query patterns discovered through experience. Call this before writing "
        "queries to avoid repeating past mistakes."
    ),
    parameters=[
        ToolParameter(
            name="scope",
            type="string",
            description="Level of detail: all=full memory, table=lessons for a specific table",
            enum=["all", "table"],
        ),
        ToolParameter(
            name="table_name",
            type="string",
            description="Filter lessons by table (required when scope is 'table')",
            required=False,
        ),
    ],
)

RECORD_LEARNING_TOOL = Tool(
    name="record_learning",
    description=(
        "Record a lesson learned from the current query interaction. "
        "Use when you discover something about the data that should be "
        "remembered for future queries — e.g., which table has correct data, "
        "column format quirks, or required filter conditions."
    ),
    parameters=[
        ToolParameter(
            name="category",
            type="string",
            description="Type of lesson",
            enum=[
                "table_preference",
                "column_usage",
                "data_format",
                "query_pattern",
                "schema_gotcha",
                "performance_hint",
            ],
        ),
        ToolParameter(
            name="subject",
            type="string",
            description="Table or column this learning is about",
        ),
        ToolParameter(
            name="lesson",
            type="string",
            description="Clear, actionable lesson text that will help future queries",
        ),
    ],
)

MANAGE_CUSTOM_RULES_TOOL = Tool(
    name="manage_custom_rules",
    description=(
        "Create, update, or delete a custom rule for this project. "
        "Use when the user asks to remember, save, or create a guideline "
        "about how to query the database, column conventions, metric formulas, "
        "or data-handling rules. Call `get_custom_rules` first to see existing "
        "rules before updating or deleting."
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


def get_available_tools(
    *,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    has_db_index: bool = False,
    has_code_db_sync: bool = False,
    has_learnings: bool = False,
) -> list[Tool]:
    """Return the subset of tools available given the current context."""
    tools: list[Tool] = []
    if has_connection:
        tools.append(EXECUTE_QUERY_TOOL)
        if has_db_index:
            tools.append(GET_QUERY_CONTEXT_TOOL)
            tools.append(GET_DB_INDEX_TOOL)
        tools.append(GET_SCHEMA_INFO_TOOL)
        tools.append(GET_CUSTOM_RULES_TOOL)
        tools.append(MANAGE_CUSTOM_RULES_TOOL)
        tools.append(RECORD_LEARNING_TOOL)
        if has_learnings:
            tools.append(GET_AGENT_LEARNINGS_TOOL)
        if has_code_db_sync:
            tools.append(GET_SYNC_CONTEXT_TOOL)
    if has_knowledge_base:
        tools.append(SEARCH_KNOWLEDGE_TOOL)
        tools.append(GET_ENTITY_INFO_TOOL)
    return tools
