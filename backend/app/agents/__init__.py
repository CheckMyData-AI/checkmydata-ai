"""Multi-agent framework for CheckMyData.ai.

Provides specialised agents (SQL, Visualization, Knowledge) coordinated
by an OrchestratorAgent that routes user requests to the right specialist.
"""

from app.agents.base import AgentContext, AgentResult, BaseAgent

__all__ = ["AgentContext", "AgentResult", "BaseAgent"]
