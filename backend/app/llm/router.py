import logging
from collections.abc import AsyncIterator

from app.config import settings
from app.core.retry import retry
from app.llm.anthropic_adapter import AnthropicAdapter
from app.llm.base import BaseLLMProvider, LLMResponse, Message, Tool
from app.llm.openai_adapter import OpenAIAdapter
from app.llm.openrouter_adapter import OpenRouterAdapter

logger = logging.getLogger(__name__)

PROVIDER_REGISTRY: dict[str, type[BaseLLMProvider]] = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "openrouter": OpenRouterAdapter,
}


class LLMRouter:
    """Selects LLM provider with automatic fallback on failure."""

    def __init__(self):
        self._instances: dict[str, BaseLLMProvider] = {}
        self._fallback_order = ["openai", "anthropic", "openrouter"]

    def _get_provider(self, name: str) -> BaseLLMProvider:
        if name not in self._instances:
            cls = PROVIDER_REGISTRY.get(name)
            if cls is None:
                raise ValueError(f"Unknown LLM provider: {name}")
            self._instances[name] = cls()
        return self._instances[name]

    def _get_fallback_chain(self, preferred: str | None) -> list[str]:
        primary = preferred or settings.default_llm_provider
        chain = [primary]
        for p in self._fallback_order:
            if p != primary:
                chain.append(p)
        return chain

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        preferred_provider: str | None = None,
    ) -> LLMResponse:
        chain = self._get_fallback_chain(preferred_provider)
        last_error: Exception | None = None

        for provider_name in chain:
            try:
                provider = self._get_provider(provider_name)

                @retry(
                    max_attempts=2,
                    backoff_seconds=1.0,
                    retryable_exceptions=(TimeoutError, ConnectionError, OSError),
                )
                async def _call():
                    return await provider.complete(
                        messages=messages,
                        tools=tools,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )

                return await _call()
            except Exception as e:
                logger.warning("Provider %s failed: %s", provider_name, e)
                last_error = e
                continue

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        preferred_provider: str | None = None,
    ) -> AsyncIterator[str]:
        chain = self._get_fallback_chain(preferred_provider)
        last_error: Exception | None = None

        for provider_name in chain:
            try:
                provider = self._get_provider(provider_name)
                async for token in provider.stream(
                    messages=messages,
                    tools=tools,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    yield token
                return
            except Exception as e:
                logger.warning("Provider %s streaming failed: %s", provider_name, e)
                last_error = e
                continue

        raise RuntimeError(f"All LLM providers failed for streaming. Last error: {last_error}")

    async def close(self):
        """Close all provider instances that support cleanup."""
        for instance in self._instances.values():
            close_fn = getattr(instance, "close", None)
            if close_fn and callable(close_fn):
                try:
                    await close_fn()
                except Exception:
                    logger.warning(
                        "Error closing provider %s",
                        instance.provider_name, exc_info=True,
                    )
