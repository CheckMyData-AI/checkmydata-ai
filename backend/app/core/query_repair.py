"""LLM-driven query repair — fixes broken queries using enriched context."""

from __future__ import annotations

import logging

from app.agents.tools.sql_tools import EXECUTE_QUERY_TOOL
from app.llm.base import Message
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

REPAIR_SYSTEM_PROMPT = """\
You are a SQL debugging expert. A query was generated to answer a user's question but it failed.

Your job:
1. Analyze what went wrong
2. Identify the root cause from the error and schema information
3. Generate a CORRECTED query using the EXACT column and table names from the schema
4. Call the `execute_query` tool with the fixed query

CRITICAL: Use ONLY the exact column and table names shown in the schema. Do NOT guess names.

{repair_context}
"""


class QueryRepairer:
    """Uses an LLM to repair a failed database query."""

    def __init__(self, llm_router: LLMRouter):
        self._llm = llm_router

    async def repair(
        self,
        repair_context: str,
        db_type: str,
        chat_history: list[Message] | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> dict:
        """Attempt to repair a failed query.

        Returns dict with 'query', 'explanation', and optionally 'error'.
        Same format as ``QueryBuilder.build_query()``.
        """
        system_prompt = REPAIR_SYSTEM_PROMPT.format(
            repair_context=repair_context,
        )

        messages: list[Message] = [
            Message(role="system", content=system_prompt),
        ]
        if chat_history:
            messages.extend(chat_history[-6:])
        messages.append(
            Message(
                role="user",
                content=(
                    f"Fix the failed query for the {db_type} database. "
                    "Use the EXACT names from the schema provided above."
                ),
            ),
        )

        try:
            response = await self._llm.complete(
                messages=messages,
                tools=[EXECUTE_QUERY_TOOL],
                preferred_provider=preferred_provider,
                model=model,
            )
        except Exception as exc:
            logger.error("LLM repair call failed: %s", exc)
            return {
                "query": "",
                "explanation": "",
                "error": f"LLM repair failed: {exc}",
            }

        if response.tool_calls:
            for tc in response.tool_calls:
                if tc.name == "execute_query":
                    return {
                        "query": tc.arguments.get("query", ""),
                        "explanation": tc.arguments.get("explanation", ""),
                    }

        return {
            "query": "",
            "explanation": response.content,
            "error": "LLM repair did not produce a query tool call.",
        }
