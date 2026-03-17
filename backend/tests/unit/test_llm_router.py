import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.base import LLMResponse, Message, ToolCall
from app.llm.router import LLMRouter


class TestLLMRouterFallback:
    @pytest.mark.asyncio
    async def test_primary_succeeds(self):
        router = LLMRouter()
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(return_value=LLMResponse(content="ok"))
        router._instances["openai"] = mock_provider

        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.default_llm_provider = "openai"
            mock_settings.openai_api_key = "sk-openai"
            mock_settings.anthropic_api_key = ""
            mock_settings.openrouter_api_key = ""
            result = await router.complete(
                messages=[Message(role="user", content="hi")],
                preferred_provider="openai",
            )

        assert result.content == "ok"
        mock_provider.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self):
        router = LLMRouter()

        failing = MagicMock()
        failing.complete = AsyncMock(side_effect=RuntimeError("API down"))
        router._instances["openai"] = failing

        working = MagicMock()
        working.complete = AsyncMock(return_value=LLMResponse(content="fallback"))
        router._instances["anthropic"] = working

        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.default_llm_provider = "openai"
            mock_settings.openai_api_key = "sk-openai"
            mock_settings.anthropic_api_key = "sk-anthropic"
            mock_settings.openrouter_api_key = ""
            result = await router.complete(
                messages=[Message(role="user", content="hi")],
                preferred_provider="openai",
            )

        assert result.content == "fallback"
        failing.complete.assert_called_once()
        working.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_providers_fail(self):
        router = LLMRouter()

        for name in ["openai", "anthropic", "openrouter"]:
            provider = MagicMock()
            provider.complete = AsyncMock(side_effect=RuntimeError(f"{name} down"))
            router._instances[name] = provider

        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.default_llm_provider = "openai"
            mock_settings.openai_api_key = "sk-openai"
            mock_settings.anthropic_api_key = "sk-anthropic"
            mock_settings.openrouter_api_key = "sk-openrouter"
            with pytest.raises(RuntimeError, match="All LLM providers failed"):
                await router.complete(
                    messages=[Message(role="user", content="hi")],
                )

    def test_get_fallback_chain(self):
        router = LLMRouter()
        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.openai_api_key = "sk-openai"
            mock_settings.anthropic_api_key = "sk-anthropic"
            mock_settings.openrouter_api_key = "sk-openrouter"
            chain = router._get_fallback_chain("anthropic")
            assert chain[0] == "anthropic"
            assert "openai" in chain
            assert "openrouter" in chain

    def test_get_fallback_chain_default(self):
        router = LLMRouter()
        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.default_llm_provider = "openai"
            mock_settings.openai_api_key = "sk-openai"
            mock_settings.anthropic_api_key = ""
            mock_settings.openrouter_api_key = ""
            chain = router._get_fallback_chain(None)
            assert chain[0] == "openai"
            assert len(chain) == 1

    def test_get_fallback_chain_filters_empty_keys(self):
        router = LLMRouter()
        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.default_llm_provider = "openrouter"
            mock_settings.openai_api_key = ""
            mock_settings.anthropic_api_key = ""
            mock_settings.openrouter_api_key = "sk-or-123"
            chain = router._get_fallback_chain(None)
            assert chain == ["openrouter"]

    def test_get_fallback_chain_keeps_only_configured(self):
        router = LLMRouter()
        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.default_llm_provider = "openai"
            mock_settings.openai_api_key = "sk-openai"
            mock_settings.anthropic_api_key = ""
            mock_settings.openrouter_api_key = "sk-or-123"
            chain = router._get_fallback_chain(None)
            assert chain == ["openai", "openrouter"]

    @pytest.mark.asyncio
    async def test_unknown_provider_raises(self):
        router = LLMRouter()
        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.default_llm_provider = "openai"
            mock_settings.openai_api_key = ""
            mock_settings.anthropic_api_key = ""
            mock_settings.openrouter_api_key = ""
            with pytest.raises(RuntimeError, match="All LLM providers failed"):
                await router.complete(
                    messages=[Message(role="user", content="hi")],
                    preferred_provider="nonexistent_provider",
                )

    @pytest.mark.asyncio
    async def test_no_configured_keys_raises(self):
        router = LLMRouter()
        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.default_llm_provider = "openai"
            mock_settings.openai_api_key = ""
            mock_settings.anthropic_api_key = ""
            mock_settings.openrouter_api_key = ""
            with pytest.raises(RuntimeError, match="All LLM providers failed"):
                await router.complete(
                    messages=[Message(role="user", content="hi")],
                )

    @pytest.mark.asyncio
    async def test_close(self):
        router = LLMRouter()
        mock_provider = MagicMock()
        mock_provider.close = AsyncMock()
        mock_provider.provider_name = "test"
        router._instances["test"] = mock_provider

        await router.close()
        mock_provider.close.assert_called_once()


class TestOpenRouterFormatMessages:
    """OpenRouterAdapter._format_messages serializes tool_calls on assistant messages."""

    def _make_adapter(self):
        with patch("app.llm.openrouter_adapter.settings") as mock_settings:
            mock_settings.openrouter_api_key = "test-key"
            from app.llm.openrouter_adapter import OpenRouterAdapter

            return OpenRouterAdapter()

    def test_plain_message(self):
        adapter = self._make_adapter()
        msgs = [Message(role="user", content="hello")]
        result = adapter._format_messages(msgs)
        assert result == [{"role": "user", "content": "hello"}]

    def test_assistant_with_tool_calls(self):
        adapter = self._make_adapter()
        tool_calls = [
            ToolCall(id="tc-1", name="search_knowledge", arguments={"query": "test"}),
            ToolCall(id="tc-2", name="execute_query", arguments={"query": "SELECT 1"}),
        ]
        msgs = [Message(role="assistant", content="", tool_calls=tool_calls)]
        result = adapter._format_messages(msgs)

        assert len(result) == 1
        assert "tool_calls" in result[0]
        assert len(result[0]["tool_calls"]) == 2

        tc1 = result[0]["tool_calls"][0]
        assert tc1["id"] == "tc-1"
        assert tc1["type"] == "function"
        assert tc1["function"]["name"] == "search_knowledge"
        assert json.loads(tc1["function"]["arguments"]) == {"query": "test"}

    def test_tool_result_message(self):
        adapter = self._make_adapter()
        msgs = [Message(
            role="tool", content="result data",
            tool_call_id="tc-1", name="search_knowledge",
        )]
        result = adapter._format_messages(msgs)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc-1"
        assert result[0]["name"] == "search_knowledge"

    def test_full_conversation_with_tools(self):
        adapter = self._make_adapter()
        tool_calls = [ToolCall(id="tc-1", name="search_knowledge", arguments={"query": "test"})]
        msgs = [
            Message(role="system", content="You are an assistant."),
            Message(role="user", content="What is the project?"),
            Message(role="assistant", content="", tool_calls=tool_calls),
            Message(
                role="tool", content="Project docs...",
                tool_call_id="tc-1", name="search_knowledge",
            ),
        ]
        result = adapter._format_messages(msgs)
        assert len(result) == 4
        assert "tool_calls" in result[2]
        assert result[3]["tool_call_id"] == "tc-1"


class TestOpenAIFormatMessages:
    """OpenAIAdapter._format_messages serializes tool_calls on assistant messages."""

    def _make_adapter(self):
        with patch("app.llm.openai_adapter.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            from app.llm.openai_adapter import OpenAIAdapter

            return OpenAIAdapter()

    def test_plain_message(self):
        adapter = self._make_adapter()
        msgs = [Message(role="user", content="hello")]
        result = adapter._format_messages(msgs)
        assert result == [{"role": "user", "content": "hello"}]

    def test_assistant_with_tool_calls(self):
        adapter = self._make_adapter()
        tool_calls = [
            ToolCall(id="tc-1", name="get_schema_info", arguments={"tables": ["users"]}),
        ]
        msgs = [Message(role="assistant", content="Let me check.", tool_calls=tool_calls)]
        result = adapter._format_messages(msgs)

        assert len(result) == 1
        assert "tool_calls" in result[0]
        tc = result[0]["tool_calls"][0]
        assert tc["id"] == "tc-1"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "get_schema_info"
        assert json.loads(tc["function"]["arguments"]) == {"tables": ["users"]}

    def test_no_tool_calls_omits_field(self):
        adapter = self._make_adapter()
        msgs = [Message(role="assistant", content="Just text.")]
        result = adapter._format_messages(msgs)
        assert "tool_calls" not in result[0]
