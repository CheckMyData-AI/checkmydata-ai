"""Tool definitions for the conversational agent.

DEPRECATED: This module is preserved for backward compatibility.
Tool definitions have been split into per-agent modules under
``app.agents.tools``.  New code should import directly from there.
"""

from app.agents.tools.knowledge_tools import GET_ENTITY_INFO_TOOL, SEARCH_KNOWLEDGE_TOOL
from app.agents.tools.orchestrator_tools import MANAGE_RULES_TOOL
from app.agents.tools.sql_tools import (
    EXECUTE_QUERY_TOOL,
    GET_AGENT_LEARNINGS_TOOL,
    GET_CUSTOM_RULES_TOOL,
    GET_DB_INDEX_TOOL,
    GET_QUERY_CONTEXT_TOOL,
    GET_SCHEMA_INFO_TOOL,
    GET_SYNC_CONTEXT_TOOL,
    RECORD_LEARNING_TOOL,
)
from app.llm.base import Tool, ToolParameter

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
    """Return the subset of tools available given the current context.

    DEPRECATED: Kept for backward compatibility with existing tests.
    New code should use the per-agent tool functions instead.
    """
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


__all__ = [
    "EXECUTE_QUERY_TOOL",
    "SEARCH_KNOWLEDGE_TOOL",
    "GET_SCHEMA_INFO_TOOL",
    "GET_CUSTOM_RULES_TOOL",
    "GET_ENTITY_INFO_TOOL",
    "GET_DB_INDEX_TOOL",
    "GET_SYNC_CONTEXT_TOOL",
    "GET_QUERY_CONTEXT_TOOL",
    "GET_AGENT_LEARNINGS_TOOL",
    "RECORD_LEARNING_TOOL",
    "MANAGE_CUSTOM_RULES_TOOL",
    "MANAGE_RULES_TOOL",
    "get_available_tools",
]
