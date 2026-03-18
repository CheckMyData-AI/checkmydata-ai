"""Base classes and communication protocol for the multi-agent system.

Every agent receives an ``AgentContext`` and returns a typed
``AgentResult`` subclass.  The orchestrator builds the context once and
passes it to whichever sub-agent it delegates to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.connectors.base import ConnectionConfig
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import Message
from app.llm.router import LLMRouter


@dataclass
class AgentContext:
    """Shared context passed from the orchestrator to every sub-agent."""

    project_id: str
    connection_config: ConnectionConfig | None
    user_question: str
    chat_history: list[Message]
    llm_router: LLMRouter
    tracker: WorkflowTracker
    workflow_id: str
    user_id: str | None = None
    preferred_provider: str | None = None
    model: str | None = None
    sql_provider: str | None = None
    sql_model: str | None = None
    project_name: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _empty_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


@dataclass
class AgentResult:
    """Base result returned by every agent."""

    status: str = "success"  # success | error | no_result
    token_usage: dict[str, int] = field(default_factory=_empty_usage)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base for all agents in the system."""

    @abstractmethod
    async def run(self, context: AgentContext, **kwargs: Any) -> AgentResult:
        """Execute the agent's task and return a typed result."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier used in logs and SSE events."""

    @staticmethod
    def accum_usage(total: dict[str, int], usage: dict[str, int] | dict[str, Any] | None) -> None:
        """Merge *usage* counters into *total* in-place."""
        if not usage:
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            total[key] = total.get(key, 0) + int(usage.get(key, 0))
