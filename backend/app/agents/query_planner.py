"""Plan validation helpers and tool schema (formerly ``QueryPlanner``).

The legacy :class:`QueryPlanner` class has been removed; ``AdaptivePlanner`` is the
sole entry point for execution-plan generation. This module retains:

- ``_VALID_TOOLS``: the set of tool names a stage may use.
- ``_validate_plan_structure``: checks tools, dependencies, and cycles.
- ``_CREATE_PLAN_TOOL``: the OpenAI-style tool schema used by ``AdaptivePlanner``
  when asking the LLM to emit a structured plan.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)



# ------------------------------------------------------------------
# Plan validation helpers
# ------------------------------------------------------------------

_VALID_TOOLS = {
    "query_database",
    "search_codebase",
    "analyze_results",
    "process_data",
    "synthesize",
    "query_mcp_source",
}


def _validate_plan_structure(stages: list[dict[str, Any]]) -> list[str]:
    """Return a list of errors (empty = valid)."""
    errors: list[str] = []
    if not stages:
        return ["Plan has no stages"]

    ids = {s.get("stage_id") for s in stages}

    for s in stages:
        sid = s.get("stage_id", "<missing>")
        tool = s.get("tool", "")
        if tool not in _VALID_TOOLS:
            errors.append(f"Stage '{sid}' has invalid tool '{tool}'")
        for dep in s.get("depends_on", []):
            if dep not in ids:
                errors.append(f"Stage '{sid}' depends on unknown stage '{dep}'")

    data_retrieval_tools = {"query_database", "search_codebase", "query_mcp_source"}
    if not any(s.get("tool") in data_retrieval_tools for s in stages):
        errors.append("Plan must include at least one data-retrieval stage")

    # Topological cycle detection (Kahn's algorithm)
    in_deg: dict[str, int] = {s.get("stage_id", ""): 0 for s in stages}
    adj: dict[str, list[str]] = {s.get("stage_id", ""): [] for s in stages}
    for s in stages:
        for dep in s.get("depends_on", []):
            if dep in adj:
                adj[dep].append(s.get("stage_id", ""))
                in_deg[s.get("stage_id", "")] = in_deg.get(s.get("stage_id", ""), 0) + 1

    queue = [n for n, d in in_deg.items() if d == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj.get(node, []):
            in_deg[neighbor] -= 1
            if in_deg[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(stages):
        errors.append("Plan has circular dependencies")

    return errors


# ------------------------------------------------------------------
# Planner tool definition
# ------------------------------------------------------------------

_CREATE_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "create_execution_plan",
        "description": "Create a multi-stage execution plan for a complex query.",
        "parameters": {
            "type": "object",
            "required": ["stages", "complexity_reason"],
            "properties": {
                "stages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["stage_id", "description", "tool"],
                        "properties": {
                            "stage_id": {"type": "string"},
                            "description": {"type": "string"},
                            "tool": {
                                "type": "string",
                                "enum": list(_VALID_TOOLS),
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "input_context": {"type": "string"},
                            "validation": {
                                "type": "object",
                                "properties": {
                                    "expected_columns": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "min_rows": {"type": "integer"},
                                    "max_rows": {"type": "integer"},
                                    "business_rules": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "cross_stage_checks": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                            },
                            "checkpoint": {"type": "boolean"},
                        },
                    },
                },
                "complexity_reason": {"type": "string"},
            },
        },
    },
}


