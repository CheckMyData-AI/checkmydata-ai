import json
import logging
from collections.abc import AsyncIterator

import openai
from openai import AsyncOpenAI

from app.config import settings
from app.llm.base import BaseLLMProvider, LLMResponse, Message, Tool, ToolCall
from app.llm.errors import (
    LLMAuthError,
    LLMBillingError,
    LLMConnectionError,
    LLMContentFilterError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    LLMTokenLimitError,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o"


# OpenAI error codes that map to our unified hierarchy (T27). Structured
# codes beat string sniffing — we only fall back to message substrings
# when the SDK didn't surface a ``code``.
_OPENAI_CONTENT_FILTER_CODES: frozenset[str] = frozenset(
    {"content_policy_violation", "content_filter"}
)
_OPENAI_TOKEN_LIMIT_CODES: frozenset[str] = frozenset(
    {"context_length_exceeded", "tokens_limit_reached", "max_tokens_exceeded"}
)
_CONTENT_FILTER_FALLBACK_SUBSTRINGS: tuple[str, ...] = (
    "content_policy",
    "content management",
    "content filter",
)
_TOKEN_LIMIT_FALLBACK_SUBSTRINGS: tuple[str, ...] = (
    "maximum context length",
    "max tokens",
    "token limit",
)


def _classify_openai_error(exc: Exception) -> Exception:
    """Map openai SDK exceptions to the unified LLM error hierarchy.

    Prefers structured error codes (``exc.code`` / ``exc.body['error']['code']``)
    over substring matching on the message — codes are stable across SDK
    releases whereas error messages routinely change.
    """
    if isinstance(exc, openai.RateLimitError):
        retry_after = None
        if hasattr(exc, "response") and exc.response is not None:
            raw = exc.response.headers.get("retry-after")
            if raw:
                try:
                    retry_after = float(raw)
                except (ValueError, TypeError):
                    pass
        return LLMRateLimitError(str(exc), cause=exc, retry_after=retry_after)

    if isinstance(exc, openai.AuthenticationError):
        return LLMAuthError(str(exc), cause=exc)

    if isinstance(exc, openai.BadRequestError):
        code = _extract_openai_error_code(exc)
        if code in _OPENAI_CONTENT_FILTER_CODES:
            return LLMContentFilterError(str(exc), cause=exc)
        if code in _OPENAI_TOKEN_LIMIT_CODES:
            return LLMTokenLimitError(str(exc), cause=exc)
        if code:
            return LLMServerError(str(exc), cause=exc)

        # Legacy fallback: OpenAI error codes are usually present but some
        # proxies / older SDK versions strip them. Guard substring checks
        # narrowly so ordinary validation errors don't get misclassified.
        msg = str(exc).lower()
        if any(s in msg for s in _CONTENT_FILTER_FALLBACK_SUBSTRINGS):
            return LLMContentFilterError(str(exc), cause=exc)
        if any(s in msg for s in _TOKEN_LIMIT_FALLBACK_SUBSTRINGS):
            return LLMTokenLimitError(str(exc), cause=exc)
        return LLMServerError(str(exc), cause=exc)

    if isinstance(exc, openai.APITimeoutError):
        return LLMTimeoutError(str(exc), cause=exc)

    if isinstance(exc, openai.APIConnectionError):
        return LLMConnectionError(str(exc), cause=exc)

    if isinstance(exc, openai.InternalServerError):
        return LLMServerError(str(exc), cause=exc)

    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", 0)
        if status == 429:
            return LLMRateLimitError(str(exc), cause=exc)
        if status in (401, 403):
            return LLMAuthError(str(exc), cause=exc)
        if status == 402:
            return LLMBillingError(str(exc), cause=exc)
        if 500 <= status < 600:
            return LLMServerError(str(exc), cause=exc)
        return LLMServerError(str(exc), cause=exc)

    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return LLMConnectionError(str(exc), cause=exc)

    return exc


def _extract_openai_error_code(exc: Exception) -> str | None:
    """Pull a structured error code out of an OpenAI SDK exception."""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            inner = err.get("code")
            if isinstance(inner, str) and inner:
                return inner
    return None


_REQUEST_TIMEOUT = 90.0


class OpenAIAdapter(BaseLLMProvider):
    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=_REQUEST_TIMEOUT,
        )

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

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise _classify_openai_error(exc) from exc

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

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise _classify_openai_error(exc) from exc

        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
