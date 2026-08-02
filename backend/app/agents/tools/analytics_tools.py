"""Meta-tool definition for querying collected analytics sources (spec §2.6).

The orchestrator delegates to :class:`~app.agents.analytics_agent.AnalyticsAgent`
through this tool. It is deliberately *not* the MCP tool: an analytics source has
a first-class connector, a collection schedule and a journal that records exactly
which periods are on file, so the agent behind this tool can say "we have not
collected that week yet" instead of guessing. ``query_mcp_source`` cannot.

:data:`ANALYTICS_SOURCE_TYPES` — "this connection is an analytics vendor" — is
re-exported here for the callers that already read it from this module: tool
availability (:func:`~app.agents.tools.orchestrator_tools.get_orchestrator_tools`),
the project probe
(:meth:`~app.agents.context_loader.ContextLoader.has_analytics_sources`) and the
dispatcher's connection resolution. It is *defined* once, in
:mod:`app.analytics.source_types` — an import-light module the collect service
shares — so the agent side and the collection side can never disagree about
which vendors exist.
"""

from __future__ import annotations

from app.analytics.source_types import ANALYTICS_SOURCE_TYPES
from app.llm.base import Tool, ToolParameter

__all__ = ["ANALYTICS_SOURCE_TYPES", "QUERY_ANALYTICS_SOURCE_TOOL"]


QUERY_ANALYTICS_SOURCE_TOOL = Tool(
    name="query_analytics_source",
    description=(
        "Query a connected analytics/app-store source (Google Analytics, "
        "App Store Connect, Google Play) for traffic, revenue, installs or "
        "subscription data that has been collected into this project. "
        "Answers come from data already collected on a schedule, so the tool "
        "also reports which periods are on file and which are not — a period "
        "that was never collected is reported as missing, never as zero."
    ),
    parameters=[
        ToolParameter(
            name="question",
            type="string",
            description="The analytics question to answer, in natural language",
        ),
        ToolParameter(
            name="connection_id",
            type="string",
            description=(
                "The ID of the analytics connection to query. Omit to use the "
                "project's only (or first) analytics connection."
            ),
            required=False,
        ),
        ToolParameter(
            name="report",
            type="string",
            description=(
                "Optional hint naming the report to read: overview (property-wide "
                "totals), geo (by country), platform (by platform/device), trend "
                "(by acquisition channel) or events (by event name)."
            ),
            required=False,
        ),
        ToolParameter(
            name="date_from",
            type="string",
            description="Optional start of the window, YYYY-MM-DD (inclusive)",
            required=False,
        ),
        ToolParameter(
            name="date_to",
            type="string",
            description="Optional end of the window, YYYY-MM-DD (inclusive)",
            required=False,
        ),
    ],
)
