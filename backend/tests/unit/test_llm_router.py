from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.base import LLMResponse, Message
from app.llm.router import LLMRouter


class TestLLMRouterFallback:
    @pytest.mark.asyncio
    async def test_primary_succeeds(self):
        router = LLMRouter()
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(return_value=LLMResponse(content="ok"))
        router._instances["openai"] = mock_provider

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

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await router.complete(
                messages=[Message(role="user", content="hi")],
            )

    def test_get_fallback_chain(self):
        router = LLMRouter()
        chain = router._get_fallback_chain("anthropic")
        assert chain[0] == "anthropic"
        assert "openai" in chain
        assert "openrouter" in chain

    def test_get_fallback_chain_default(self):
        router = LLMRouter()
        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.default_llm_provider = "openai"
            chain = router._get_fallback_chain(None)
            assert chain[0] == "openai"

    @pytest.mark.asyncio
    async def test_unknown_provider_raises(self):
        router = LLMRouter()
        with pytest.raises(RuntimeError):
            await router.complete(
                messages=[Message(role="user", content="hi")],
                preferred_provider="nonexistent_provider",
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
