"""Meta-tool definition for querying MCP data sources.

Used by the OrchestratorAgent to delegate to MCPSourceAgent.
"""

from app.llm.base import Tool, ToolParameter

QUERY_MCP_SOURCE_TOOL = Tool(
    name="query_mcp_source",
    description=(
        "Query an external data source connected via MCP (Model Context Protocol). "
        "Use when the user asks about data from external services like "
        "Google Analytics, Stripe, Jira, or other MCP-connected sources."
    ),
    parameters=[
        ToolParameter(
            name="question",
            type="string",
            description="The data question to answer using the MCP source",
        ),
        ToolParameter(
            name="connection_id",
            type="string",
            description="The ID of the MCP connection to use",
            required=False,
        ),
    ],
)
