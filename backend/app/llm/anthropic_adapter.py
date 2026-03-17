import json
import logging
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.config import settings
from app.llm.base import BaseLLMProvider, LLMResponse, Message, Tool, ToolCall

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"


class AnthropicAdapter(BaseLLMProvider):
    def __init__(self):
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def _format_messages(self, messages: list[Message]) -> tuple[str, list[dict]]:
        system_prompt = ""
        formatted = []
        for m in messages:
            if m.role == "system":
                system_prompt += m.content + "\n"
            elif m.role == "tool":
                formatted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id,
                                "content": m.content,
                            }
                        ],
                    }
                )
            else:
                formatted.append({"role": m.role, "content": m.content})
        return system_prompt.strip(), formatted

    def _tools_to_anthropic(self, tools: list[Tool]) -> list[dict]:
        result = []
        for tool in tools:
            properties = {}
            required = []
            for p in tool.parameters:
                prop = {"type": p.type, "description": p.description}
                if p.enum:
                    prop["enum"] = p.enum
                properties[p.name] = prop
                if p.required:
                    required.append(p.name)
            result.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                }
            )
        return result

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        system, formatted = self._format_messages(messages)
        kwargs: dict = {
            "model": model or DEFAULT_MODEL,
            "messages": formatted,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._tools_to_anthropic(tools)

        response = await self._client.messages.create(**kwargs)

        content_parts = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                if isinstance(block.input, dict):
                    args = block.input
                else:
                    try:
                        args = json.loads(block.input)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Malformed tool_call arguments: %s", block.input)
                        args = {}
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=args,
                    )
                )

        return LLMResponse(
            content="\n".join(content_parts),
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
            model=response.model,
            finish_reason=response.stop_reason or "",
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        system, formatted = self._format_messages(messages)
        kwargs: dict = {
            "model": model or DEFAULT_MODEL,
            "messages": formatted,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._tools_to_anthropic(tools)

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text
