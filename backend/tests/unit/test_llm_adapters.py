"""Tests for LLM adapter error classification and response formatting."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.base import LLMResponse, Message, ToolCall
from app.llm.errors import (
    LLMAuthError,
    LLMBillingError,
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    LLMTokenLimitError,
)


def _msg(role="user", content="Hello"):
    return Message(role=role, content=content)


class TestOpenAIClassifier:
    def test_rate_limit(self):
        import openai

        from app.llm.openai_adapter import _classify_openai_error

        exc = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(headers={}, status_code=429),
            body={},
        )
        result = _classify_openai_error(exc)
        assert isinstance(result, LLMRateLimitError)

    def test_auth_error(self):
        import openai

        from app.llm.openai_adapter import _classify_openai_error

        exc = openai.AuthenticationError(
            message="bad key",
            response=MagicMock(headers={}, status_code=401),
            body={},
        )
        assert isinstance(_classify_openai_error(exc), LLMAuthError)

    def test_bad_request_token_limit(self):
        import openai

        from app.llm.openai_adapter import _classify_openai_error

        exc = openai.BadRequestError(
            message="maximum context length exceeded, token limit",
            response=MagicMock(headers={}, status_code=400),
            body={},
        )
        assert isinstance(_classify_openai_error(exc), LLMTokenLimitError)

    def test_bad_request_content_filter(self):
        import openai

        from app.llm.openai_adapter import _classify_openai_error

        exc = openai.BadRequestError(
            message="content_policy violation",
            response=MagicMock(headers={}, status_code=400),
            body={},
        )
        from app.llm.errors import LLMContentFilterError

        assert isinstance(_classify_openai_error(exc), LLMContentFilterError)

    def test_timeout(self):
        import openai

        from app.llm.openai_adapter import _classify_openai_error

        exc = openai.APITimeoutError(request=MagicMock())
        assert isinstance(_classify_openai_error(exc), LLMTimeoutError)

    def test_connection_error(self):
        import openai

        from app.llm.openai_adapter import _classify_openai_error

        exc = openai.APIConnectionError(request=MagicMock())
        assert isinstance(_classify_openai_error(exc), LLMConnectionError)

    def test_internal_server(self):
        import openai

        from app.llm.openai_adapter import _classify_openai_error

        exc = openai.InternalServerError(
            message="oops",
            response=MagicMock(headers={}, status_code=500),
            body={},
        )
        assert isinstance(_classify_openai_error(exc), LLMServerError)

    def test_unknown_passes_through(self):
        from app.llm.openai_adapter import _classify_openai_error

        exc = ValueError("unknown")
        assert _classify_openai_error(exc) is exc

    def test_402_billing(self):
        import openai

        from app.llm.openai_adapter import _classify_openai_error

        exc = openai.APIStatusError(
            message="Payment Required",
            response=MagicMock(headers={}, status_code=402),
            body={},
        )
        result = _classify_openai_error(exc)
        assert isinstance(result, LLMBillingError)
        assert not result.is_retryable

    def test_os_error(self):
        from app.llm.openai_adapter import _classify_openai_error

        exc = OSError("network")
        assert isinstance(_classify_openai_error(exc), LLMConnectionError)


class TestAnthropicClassifier:
    def test_rate_limit(self):
        import anthropic

        from app.llm.anthropic_adapter import _classify_anthropic_error

        exc = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(headers={}, status_code=429),
            body={},
        )
        assert isinstance(_classify_anthropic_error(exc), LLMRateLimitError)

    def test_auth_error(self):
        import anthropic

        from app.llm.anthropic_adapter import _classify_anthropic_error

        exc = anthropic.AuthenticationError(
            message="bad key",
            response=MagicMock(headers={}, status_code=401),
            body={},
        )
        assert isinstance(_classify_anthropic_error(exc), LLMAuthError)

    def test_bad_request_token(self):
        import anthropic

        from app.llm.anthropic_adapter import _classify_anthropic_error

        exc = anthropic.BadRequestError(
            message="prompt is too long token limit",
            response=MagicMock(headers={}, status_code=400),
            body={},
        )
        assert isinstance(_classify_anthropic_error(exc), LLMTokenLimitError)

    def test_timeout(self):
        import anthropic

        from app.llm.anthropic_adapter import _classify_anthropic_error

        exc = anthropic.APITimeoutError(request=MagicMock())
        assert isinstance(_classify_anthropic_error(exc), LLMTimeoutError)

    def test_402_billing(self):
        import anthropic

        from app.llm.anthropic_adapter import _classify_anthropic_error

        exc = anthropic.APIStatusError(
            message="Payment Required",
            response=MagicMock(headers={}, status_code=402),
            body={},
        )
        result = _classify_anthropic_error(exc)
        assert isinstance(result, LLMBillingError)
        assert not result.is_retryable

    def test_connection(self):
        import anthropic

        from app.llm.anthropic_adapter import _classify_anthropic_error

        exc = anthropic.APIConnectionError(request=MagicMock())
        assert isinstance(_classify_anthropic_error(exc), LLMConnectionError)


class TestOpenRouterClassifier:
    def test_429(self):
        import httpx

        from app.llm.openrouter_adapter import (
            _classify_openrouter_error,
        )

        resp = MagicMock(
            status_code=429,
            headers={},
            text="rate limit",
        )
        exc = httpx.HTTPStatusError("err", request=MagicMock(), response=resp)
        assert isinstance(_classify_openrouter_error(exc), LLMRateLimitError)

    def test_401(self):
        import httpx

        from app.llm.openrouter_adapter import (
            _classify_openrouter_error,
        )

        resp = MagicMock(
            status_code=401,
            headers={},
            text="unauthorized",
        )
        exc = httpx.HTTPStatusError("err", request=MagicMock(), response=resp)
        assert isinstance(_classify_openrouter_error(exc), LLMAuthError)

    def test_400_token_limit(self):
        import httpx

        from app.llm.openrouter_adapter import (
            _classify_openrouter_error,
        )

        resp = MagicMock(
            status_code=400,
            headers={},
            text="context length exceeded",
        )
        exc = httpx.HTTPStatusError("err", request=MagicMock(), response=resp)
        assert isinstance(_classify_openrouter_error(exc), LLMTokenLimitError)

    def test_500(self):
        import httpx

        from app.llm.openrouter_adapter import (
            _classify_openrouter_error,
        )

        resp = MagicMock(
            status_code=500,
            headers={},
            text="server error",
        )
        exc = httpx.HTTPStatusError("err", request=MagicMock(), response=resp)
        assert isinstance(_classify_openrouter_error(exc), LLMServerError)

    def test_timeout(self):
        import httpx

        from app.llm.openrouter_adapter import (
            _classify_openrouter_error,
        )

        exc = httpx.ReadTimeout("timeout")
        assert isinstance(_classify_openrouter_error(exc), LLMTimeoutError)

    def test_402_billing(self):
        import httpx

        from app.llm.openrouter_adapter import (
            _classify_openrouter_error,
        )

        resp = MagicMock(
            status_code=402,
            headers={},
            text="payment required",
        )
        exc = httpx.HTTPStatusError("err", request=MagicMock(), response=resp)
        result = _classify_openrouter_error(exc)
        assert isinstance(result, LLMBillingError)
        assert not result.is_retryable

    def test_connect_error(self):
        import httpx

        from app.llm.openrouter_adapter import (
            _classify_openrouter_error,
        )

        exc = httpx.ConnectError("dns fail")
        assert isinstance(_classify_openrouter_error(exc), LLMConnectionError)


class TestOpenAIAdapterComplete:
    @pytest.fixture
    def adapter(self):
        with patch("app.llm.openai_adapter.settings") as mock_s:
            mock_s.openai_api_key = "test-key"
            from app.llm.openai_adapter import OpenAIAdapter

            return OpenAIAdapter()

    async def test_complete_text(self, adapter):
        mock_msg = MagicMock()
        mock_msg.content = "Hello response"
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_choice.finish_reason = "stop"
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 5
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage = mock_usage
        mock_resp.model = "gpt-4o"

        adapter._client.chat.completions.create = AsyncMock(return_value=mock_resp)
        resp = await adapter.complete([_msg()])
        assert isinstance(resp, LLMResponse)
        assert resp.content == "Hello response"
        assert resp.usage["prompt_tokens"] == 10

    async def test_complete_with_tool_calls(self, adapter):
        tc = MagicMock()
        tc.id = "tc-1"
        tc.function.name = "get_data"
        tc.function.arguments = '{"query": "SELECT 1"}'
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.tool_calls = [tc]
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_choice.finish_reason = "tool_calls"
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage = MagicMock(prompt_tokens=5, completion_tokens=3)
        mock_resp.model = "gpt-4o"

        adapter._client.chat.completions.create = AsyncMock(return_value=mock_resp)
        resp = await adapter.complete([_msg()])
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_data"

    async def test_complete_raises_on_error(self, adapter):
        import openai

        adapter._client.chat.completions.create = AsyncMock(
            side_effect=openai.RateLimitError(
                message="rate limited",
                response=MagicMock(headers={}, status_code=429),
                body={},
            )
        )
        with pytest.raises(LLMRateLimitError):
            await adapter.complete([_msg()])


class TestAnthropicAdapterComplete:
    @pytest.fixture
    def adapter(self):
        with patch("app.llm.anthropic_adapter.settings") as mock_s:
            mock_s.anthropic_api_key = "test-key"
            from app.llm.anthropic_adapter import AnthropicAdapter

            return AnthropicAdapter()

    async def test_complete_text(self, adapter):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hi"
        mock_usage = MagicMock()
        mock_usage.input_tokens = 8
        mock_usage.output_tokens = 4
        mock_resp = MagicMock()
        mock_resp.content = [text_block]
        mock_resp.usage = mock_usage
        mock_resp.model = "claude-sonnet-4-20250514"
        mock_resp.stop_reason = "end_turn"

        adapter._client.messages.create = AsyncMock(return_value=mock_resp)
        resp = await adapter.complete([_msg()])
        assert resp.content == "Hi"
        assert resp.usage["prompt_tokens"] == 8

    async def test_complete_tool_use(self, adapter):
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tu-1"
        tool_block.name = "query_database"
        tool_block.input = {"sql": "SELECT 1"}
        mock_resp = MagicMock()
        mock_resp.content = [tool_block]
        mock_resp.usage = MagicMock(input_tokens=5, output_tokens=10)
        mock_resp.model = "claude-sonnet-4-20250514"
        mock_resp.stop_reason = "tool_use"

        adapter._client.messages.create = AsyncMock(return_value=mock_resp)
        resp = await adapter.complete([_msg()])
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].arguments == {"sql": "SELECT 1"}

    async def test_format_messages_system(self, adapter):
        msgs = [
            _msg("system", "You are helpful"),
            _msg("user", "Hello"),
        ]
        system, formatted = adapter._format_messages(msgs)
        assert system == "You are helpful"
        assert len(formatted) == 1
        assert formatted[0]["role"] == "user"

    async def test_format_messages_tool(self, adapter):
        msgs = [
            Message(
                role="tool",
                content='{"result": 42}',
                tool_call_id="tc-1",
            ),
        ]
        _, formatted = adapter._format_messages(msgs)
        assert formatted[0]["role"] == "user"
        assert formatted[0]["content"][0]["type"] == "tool_result"


class TestOpenRouterAdapterComplete:
    @pytest.fixture
    def adapter(self):
        with patch("app.llm.openrouter_adapter.settings") as s:
            s.openrouter_api_key = "test-key"
            from app.llm.openrouter_adapter import OpenRouterAdapter

            return OpenRouterAdapter()

    async def test_complete_text(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Reply", "role": "assistant"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 7,
                "completion_tokens": 3,
            },
            "model": "openai/gpt-4o",
        }
        mock_resp.raise_for_status = MagicMock()

        adapter._client.post = AsyncMock(return_value=mock_resp)
        resp = await adapter.complete([_msg()])
        assert resp.content == "Reply"
        assert resp.usage["prompt_tokens"] == 7

    async def test_complete_with_tool_calls(self, adapter):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "tc-1",
                                "function": {
                                    "name": "query",
                                    "arguments": '{"q":"hi"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 8,
            },
            "model": "openai/gpt-4o",
        }
        mock_resp.raise_for_status = MagicMock()

        adapter._client.post = AsyncMock(return_value=mock_resp)
        resp = await adapter.complete([_msg()])
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "query"

    async def test_format_messages_with_tool_calls(self, adapter):
        msgs = [
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        name="fn",
                        arguments={"key": "val"},
                    )
                ],
            ),
        ]
        formatted = adapter._format_messages(msgs)
        assert formatted[0]["tool_calls"][0]["id"] == "tc-1"


class TestLLMErrorUserMessage:
    def test_base_error_user_message(self):
        err = LLMError("something broke")
        assert "AI service" in err.user_message

    def test_base_error_retry_after(self):
        err = LLMError("fail", retry_after=10.0)
        assert err.retry_after_seconds == 10.0
