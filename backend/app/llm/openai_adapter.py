import json
import logging
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.config import settings
from app.llm.base import BaseLLMProvider, LLMResponse, Message, Tool, ToolCall

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o"


class OpenAIAdapter(BaseLLMProvider):
    def __init__(self):
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    @property
    def provider_name(self) -> str:
        return "openai"

    def _format_messages(self, messages: list[Message]) -> list[dict]:
        result = []
        for m in messages:
            msg: dict = {"role": m.role, "content": m.content}
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            if m.name:
                msg["name"] = m.name
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in m.tool_calls
                ]
            result.append(msg)
        return result

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": model or DEFAULT_MODEL,
            "messages": self._format_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = self._tools_to_schema(tools)

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Malformed tool_call arguments: %s", tc.function.arguments)
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            model=response.model,
            finish_reason=choice.finish_reason or "",
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        kwargs: dict = {
            "model": model or DEFAULT_MODEL,
            "messages": self._format_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = self._tools_to_schema(tools)

        response = await self._client.chat.completions.create(**kwargs)
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
