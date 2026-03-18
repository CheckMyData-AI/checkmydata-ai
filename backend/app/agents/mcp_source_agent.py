"""MCPSourceAgent — interacts with external MCP servers to answer questions.

This agent dynamically discovers tools from a connected MCP server and
uses an LLM loop to decide which tools to call, similar to how
SQLAgent handles database queries.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.prompts.mcp_prompt import build_mcp_source_system_prompt
from app.config import settings
from app.connectors.mcp_client import MCPClientAdapter
from app.llm.base import LLMResponse, Message, Tool, ToolParameter
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)


@dataclass
class MCPSourceResult(AgentResult):
    """Result from an MCP source query."""

    answer: str = ""
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    raw_results: list[dict[str, Any]] = field(default_factory=list)


class MCPSourceAgent(BaseAgent):
    """Agent that queries external MCP servers via MCPClientAdapter."""

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        adapter: MCPClientAdapter | None = None,
    ) -> None:
        self._llm = llm_router or LLMRouter()
        self._adapter = adapter

    @property
    def name(self) -> str:
        return "mcp_source"

    def set_adapter(self, adapter: MCPClientAdapter) -> None:
        self._adapter = adapter

    def _build_llm_tools(self) -> list[Tool]:
        """Convert discovered MCP tool schemas into LLM Tool objects."""
        if not self._adapter:
            return []

        tools: list[Tool] = []
        for schema in self._adapter.get_tool_schemas():
            params: list[ToolParameter] = []
            input_schema = schema.get("input_schema", {})
            properties = input_schema.get("properties", {})
            required_names = set(input_schema.get("required", []))

            for pname, pinfo in properties.items():
                params.append(
                    ToolParameter(
                        name=pname,
                        type=pinfo.get("type", "string"),
                        description=pinfo.get("description", ""),
                        required=pname in required_names,
                    )
                )

            tools.append(
                Tool(
                    name=schema["name"],
                    description=schema.get("description", ""),
                    parameters=params,
                )
            )

        return tools

    def _build_tool_description_text(self) -> str:
        """Build a human-readable list of available tools for the system prompt."""
        if not self._adapter:
            return ""

        lines: list[str] = []
        for schema in self._adapter.get_tool_schemas():
            desc = schema.get("description", "No description")
            input_schema = schema.get("input_schema", {})
            props = input_schema.get("properties", {})
            param_list = ", ".join(f"{k}: {v.get('type', '?')}" for k, v in props.items())
            lines.append(f"- **{schema['name']}**({param_list}): {desc}")

        return "\n".join(lines) if lines else "No tools available."

    async def run(  # type: ignore[override]
        self,
        context: AgentContext,
        *,
        question: str | None = None,
        source_name: str = "MCP Source",
        **_kwargs: Any,
    ) -> MCPSourceResult:
        if not self._adapter:
            return MCPSourceResult(
                status="error",
                error="No MCP adapter configured",
                answer="Cannot query MCP source: no adapter connected.",
            )

        user_question = question or context.user_question
        tools = self._build_llm_tools()

        if not tools:
            return MCPSourceResult(
                status="no_result",
                answer="The MCP source has no tools available.",
            )

        system_prompt = build_mcp_source_system_prompt(
            source_name=source_name,
            tool_descriptions=self._build_tool_description_text(),
        )

        messages: list[Message] = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_question),
        ]

        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        tool_calls_made: list[dict[str, Any]] = []
        raw_results: list[dict[str, Any]] = []

        for _iteration in range(settings.max_mcp_iterations):
            llm_resp: LLMResponse = await self._llm.complete(
                messages=messages,
                tools=tools,
                preferred_provider=context.preferred_provider,
                model=context.model,
            )
            self.accum_usage(total_usage, llm_resp.usage)

            if not llm_resp.tool_calls:
                return MCPSourceResult(
                    status="success",
                    answer=llm_resp.content or "",
                    token_usage=total_usage,
                    tool_calls_made=tool_calls_made,
                    raw_results=raw_results,
                )

            messages.append(
                Message(
                    role="assistant",
                    content=llm_resp.content or "",
                    tool_calls=llm_resp.tool_calls,
                )
            )

            for tc in llm_resp.tool_calls:
                result_text = await self._adapter.call_tool(tc.name, tc.arguments)

                tool_calls_made.append(
                    {
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "result_preview": result_text[:500],
                    }
                )

                try:
                    parsed = json.loads(result_text)
                    raw_results.append({"tool": tc.name, "data": parsed})
                except (json.JSONDecodeError, TypeError):
                    raw_results.append({"tool": tc.name, "data": result_text[:1000]})

                messages.append(
                    Message(
                        role="tool",
                        content=result_text,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )

        return MCPSourceResult(
            status="success",
            answer="Reached maximum iterations for MCP tool calls.",
            token_usage=total_usage,
            tool_calls_made=tool_calls_made,
            raw_results=raw_results,
        )
