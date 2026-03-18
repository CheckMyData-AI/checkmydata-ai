"""Build dynamic system prompts for the conversational agent.

DEPRECATED: This module is preserved for backward compatibility.
Prompt logic has been split into per-agent modules under
``app.agents.prompts``.  New code should import from there.
"""

from __future__ import annotations

from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt
from app.agents.prompts.sql_prompt import DIALECT_HINTS

__all__ = ["DIALECT_HINTS", "build_agent_system_prompt"]


def build_agent_system_prompt(
    *,
    project_name: str | None = None,
    db_type: str | None = None,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    has_db_index: bool = False,
    db_index_stale: bool = False,
    has_code_db_sync: bool = False,
    has_learnings: bool = False,
    table_map: str = "",
    learnings_prompt: str = "",
) -> str:
    """Assemble a role-aware, capability-aware system prompt.

    DEPRECATED: Delegates to ``build_orchestrator_system_prompt``.
    The ``has_db_index``, ``db_index_stale``, ``has_code_db_sync``,
    ``has_learnings``, and ``learnings_prompt`` arguments are now
    handled inside the SQL agent's prompt builder.
    """
    return build_orchestrator_system_prompt(
        project_name=project_name,
        db_type=db_type,
        has_connection=has_connection,
        has_knowledge_base=has_knowledge_base,
        table_map=table_map,
    )
