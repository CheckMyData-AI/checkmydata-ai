"""Meta-tool definition for querying MCP data sources.

Used by the OrchestratorAgent to delegate to MCPSourceAgent.
"""

from app.llm.base import Tool, ToolParameter

QUERY_MCP_SOURCE_TOOL = Tool(
    name="query_mcp_source",
    description=(
        "Query an external data source connected via MCP (Model Context Protocol). "
        "Use this for sources that are NOT natively supported — e.g. Stripe, Jira, "
        "or any other MCP-connected service. Google Analytics, App Store Connect "
        "and Google Play have first-class connectors, so prefer "
        "query_analytics_source for those: it answers from data already collected "
        "into this project and reports which periods are missing."
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
