"""Backward-compatible wrapper around the new OrchestratorAgent.

The ``ConversationalAgent`` class is preserved so that existing imports
(``from app.core.agent import ConversationalAgent, AgentResponse``) and
the chat route (``_agent = ConversationalAgent()``) continue to work
without modification.  Internally everything delegates to
``OrchestratorAgent``.
"""

from __future__ import annotations

import logging

from app.agents.base import AgentContext
from app.agents.orchestrator import AgentResponse, OrchestratorAgent
from app.connectors.base import ConnectionConfig
from app.core.workflow_tracker import WorkflowTracker
from app.core.workflow_tracker import tracker as default_tracker
from app.knowledge.custom_rules import CustomRulesEngine
from app.knowledge.vector_store import VectorStore
from app.llm.base import Message
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

__all__ = ["AgentResponse", "ConversationalAgent"]


class ConversationalAgent:
    """Multi-tool conversational agent — now a thin wrapper over OrchestratorAgent."""

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        vector_store: VectorStore | None = None,
        custom_rules: CustomRulesEngine | None = None,
        workflow_tracker: WorkflowTracker | None = None,
    ) -> None:
        self._tracker = workflow_tracker or default_tracker
        self._orchestrator = OrchestratorAgent(
            llm_router=llm_router,
            vector_store=vector_store,
            custom_rules=custom_rules,
            workflow_tracker=workflow_tracker,
        )

    async def run(
        self,
        question: str,
        project_id: str,
        connection_config: ConnectionConfig | None = None,
        chat_history: list[Message] | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
        sql_provider: str | None = None,
        sql_model: str | None = None,
        project_name: str | None = None,
        user_id: str | None = None,
    ) -> AgentResponse:
        wf_id = await self._tracker.begin(
            "agent",
            {"question": question[:100], "has_connection": connection_config is not None},
        )

        context = AgentContext(
            project_id=project_id,
            connection_config=connection_config,
            user_question=question,
            chat_history=chat_history or [],
            llm_router=self._orchestrator._llm,
            tracker=self._tracker,
            workflow_id=wf_id,
            user_id=user_id,
            preferred_provider=preferred_provider,
            model=model,
            sql_provider=sql_provider,
            sql_model=sql_model,
            project_name=project_name,
        )

        return await self._orchestrator.run(context)
