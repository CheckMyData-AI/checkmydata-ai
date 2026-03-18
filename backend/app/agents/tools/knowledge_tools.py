"""Tool definitions available to the KnowledgeAgent."""

from app.llm.base import Tool, ToolParameter

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


def get_knowledge_tools() -> list[Tool]:
    """Return knowledge-related tools."""
    return [SEARCH_KNOWLEDGE_TOOL, GET_ENTITY_INFO_TOOL]
