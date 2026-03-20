import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.llm.base import BaseLLMProvider, LLMResponse, Message, Tool, ToolCall
from app.llm.errors import (
    LLMAuthError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    LLMTokenLimitError,
)

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-4o"


def _classify_openrouter_error(exc: Exception) -> Exception:
    """Map httpx / OpenRouter errors to the unified LLM error hierarchy."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        retry_after = None
        raw_ra = exc.response.headers.get("retry-after")
        if raw_ra:
            try:
                retry_after = float(raw_ra)
            except (ValueError, TypeError):
                pass

        body = ""
        try:
            body = exc.response.text.lower()
        except Exception:
            pass

        if status == 429:
            return LLMRateLimitError(str(exc), cause=exc, retry_after=retry_after)
        if status in (401, 403):
            return LLMAuthError(str(exc), cause=exc)
        if status == 400:
            if "context length" in body or "max_tokens" in body or "too many tokens" in body:
                return LLMTokenLimitError(str(exc), cause=exc)
            return LLMServerError(str(exc), cause=exc)
        if 500 <= status < 600:
            return LLMServerError(str(exc), cause=exc)
        return LLMServerError(str(exc), cause=exc)

    if isinstance(exc, httpx.TimeoutException):
        return LLMTimeoutError(str(exc), cause=exc)

    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return LLMConnectionError(str(exc), cause=exc)

    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return LLMConnectionError(str(exc), cause=exc)

    return exc


class OpenRouterAdapter(BaseLLMProvider):
    def __init__(self):
        self._api_key = settings.openrouter_api_key
        self._client = httpx.AsyncClient(
            base_url=OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "HTTP-Referer": "https://checkmydata.ai",
                "X-Title": "CheckMyData.ai",
            },
            timeout=120.0,
        )

    @property
    def provider_name(self) -> str:
        return "openrouter"

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
        payload: dict = {
            "model": model or DEFAULT_MODEL,
            "messages": self._format_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = self._tools_to_schema(tools)

        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
        except Exception as exc:
            raise _classify_openrouter_error(exc) from exc

        data = resp.json()

        choice = data["choices"][0]
        msg = choice["message"]

        tool_calls: list[ToolCall] = []
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Malformed tool_call arguments: %s", tc["function"]["arguments"])
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        arguments=args,
                    )
                )

        usage = data.get("usage", {})
        return LLMResponse(
            content=msg.get("content", "") or "",
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
            model=data.get("model", model or DEFAULT_MODEL),
            finish_reason=choice.get("finish_reason", ""),
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        payload: dict = {
            "model": model or DEFAULT_MODEL,
            "messages": self._format_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = self._tools_to_schema(tools)

        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        delta = chunk["choices"][0].get("delta", {})
                        if content := delta.get("content"):
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except GeneratorExit:
            raise
        except Exception as exc:
            raise _classify_openrouter_error(exc) from exc

    async def close(self):
        await self._client.aclose()
