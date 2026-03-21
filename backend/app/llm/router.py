import asyncio
import logging
from collections.abc import AsyncIterator

from app.config import settings
from app.llm.anthropic_adapter import AnthropicAdapter
from app.llm.base import BaseLLMProvider, LLMResponse, Message, Tool
from app.llm.errors import (
    RETRYABLE_LLM_ERRORS,
    LLMAllProvidersFailedError,
    LLMAuthError,
    LLMError,
    LLMTokenLimitError,
)
from app.llm.openai_adapter import OpenAIAdapter
from app.llm.openrouter_adapter import OpenRouterAdapter

logger = logging.getLogger(__name__)

PROVIDER_REGISTRY: dict[str, type[BaseLLMProvider]] = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "openrouter": OpenRouterAdapter,
}

_MAX_RETRIES_PER_PROVIDER = 3
_BASE_BACKOFF_SECONDS = 2.0
_BACKOFF_MULTIPLIER = 2.0

_NON_RETRYABLE_PER_PROVIDER: tuple[type[LLMError], ...] = (
    LLMAuthError,
    LLMTokenLimitError,
)


_HEALTH_CHECK_INTERVAL = 60.0
_HEALTH_UNHEALTHY_TTL = 120.0


class LLMRouter:
    """Selects LLM provider with automatic retry + fallback on failure."""

    def __init__(self):
        self._instances: dict[str, BaseLLMProvider] = {}
        self._fallback_order = ["openai", "anthropic", "openrouter"]
        self._unhealthy: dict[str, float] = {}
        self._health_task: asyncio.Task | None = None

    def _get_provider(self, name: str) -> BaseLLMProvider:
        if name not in self._instances:
            cls = PROVIDER_REGISTRY.get(name)
            if cls is None:
                raise ValueError(f"Unknown LLM provider: {name}")
            self._instances[name] = cls()
        return self._instances[name]

    def _get_fallback_chain(self, preferred: str | None) -> list[str]:
        import time as _time

        primary = preferred or settings.default_llm_provider
        chain = [primary]
        for p in self._fallback_order:
            if p != primary:
                chain.append(p)
        key_map = {
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
            "openrouter": settings.openrouter_api_key,
        }
        now = _time.monotonic()
        healthy = [
            p
            for p in chain
            if key_map.get(p)
            and (p not in self._unhealthy or now - self._unhealthy[p] > _HEALTH_UNHEALTHY_TTL)
        ]
        if not healthy:
            return [p for p in chain if key_map.get(p)]
        return healthy

    def mark_unhealthy(self, provider: str) -> None:
        import time as _time

        self._unhealthy[provider] = _time.monotonic()
        logger.warning("Provider %s marked unhealthy", provider)

    def mark_healthy(self, provider: str) -> None:
        self._unhealthy.pop(provider, None)

    async def start_health_checks(self) -> None:
        """Start background health check loop (called from app lifespan)."""
        if self._health_task and not self._health_task.done():
            return
        self._health_task = asyncio.create_task(self._health_loop())

    async def stop_health_checks(self) -> None:
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

    async def _health_loop(self) -> None:
        """Ping each provider periodically."""
        while True:
            try:
                await asyncio.sleep(_HEALTH_CHECK_INTERVAL)
                for name in list(self._unhealthy.keys()):
                    try:
                        provider = self._get_provider(name)
                        await provider.complete(
                            messages=[Message(role="user", content="hi")],
                            max_tokens=1,
                        )
                        self.mark_healthy(name)
                        logger.info("Provider %s recovered", name)
                    except Exception:
                        logger.debug("Provider %s still unhealthy", name)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Health check loop error", exc_info=True)

    async def _call_with_retry(
        self,
        provider: BaseLLMProvider,
        provider_name: str,
        messages: list[Message],
        tools: list[Tool] | None,
        model: str | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Call a single provider with per-provider retry + exponential backoff."""
        delay = _BASE_BACKOFF_SECONDS
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES_PER_PROVIDER + 1):
            try:
                resp = await provider.complete(
                    messages=messages,
                    tools=tools,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if not resp.provider:
                    resp.provider = provider_name
                return resp
            except _NON_RETRYABLE_PER_PROVIDER as exc:
                logger.warning(
                    "Provider %s non-retryable error (attempt %d): %s",
                    provider_name,
                    attempt,
                    exc,
                )
                raise
            except RETRYABLE_LLM_ERRORS as exc:
                last_exc = exc
                if attempt >= _MAX_RETRIES_PER_PROVIDER:
                    break
                wait = exc.retry_after_seconds or delay
                logger.warning(
                    "Provider %s retryable error (attempt %d/%d), retrying in %.1fs: %s",
                    provider_name,
                    attempt,
                    _MAX_RETRIES_PER_PROVIDER,
                    wait,
                    exc,
                )
                await asyncio.sleep(wait)
                delay *= _BACKOFF_MULTIPLIER
            except Exception as exc:
                last_exc = exc
                if attempt >= _MAX_RETRIES_PER_PROVIDER:
                    break
                logger.warning(
                    "Provider %s unexpected error (attempt %d/%d), retrying in %.1fs: %s",
                    provider_name,
                    attempt,
                    _MAX_RETRIES_PER_PROVIDER,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                delay *= _BACKOFF_MULTIPLIER

        raise last_exc  # type: ignore[misc]

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
                return await self._call_with_retry(
                    provider,
                    provider_name,
                    messages,
                    tools,
                    model,
                    temperature,
                    max_tokens,
                )
            except LLMError as e:
                logger.warning(
                    "Provider %s exhausted retries: [%s] %s",
                    provider_name,
                    type(e).__name__,
                    e,
                )
                last_error = e
                if not e.is_retryable:
                    break
                continue
            except Exception as e:
                logger.warning("Provider %s failed: %s", provider_name, e)
                last_error = e
                continue

        raise LLMAllProvidersFailedError(
            f"All LLM providers failed. Last error: {last_error}",
            cause=last_error,
        )

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
            tokens_yielded = False
            try:
                provider = self._get_provider(provider_name)
                async for token in provider.stream(
                    messages=messages,
                    tools=tools,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    tokens_yielded = True
                    yield token
                return
            except LLMError as e:
                if tokens_yielded:
                    logger.error(
                        "Provider %s streaming failed after yielding tokens; "
                        "cannot retry safely: [%s] %s",
                        provider_name,
                        type(e).__name__,
                        e,
                    )
                    raise
                logger.warning(
                    "Provider %s streaming failed before tokens: [%s] %s",
                    provider_name,
                    type(e).__name__,
                    e,
                )
                last_error = e
                if not e.is_retryable:
                    break
                continue
            except Exception as e:
                if tokens_yielded:
                    logger.error(
                        "Provider %s streaming failed after yielding tokens; "
                        "cannot retry safely: %s",
                        provider_name,
                        e,
                    )
                    raise
                logger.warning(
                    "Provider %s streaming failed before tokens: %s",
                    provider_name,
                    e,
                )
                last_error = e
                continue

        raise LLMAllProvidersFailedError(
            f"All LLM providers failed for streaming. Last error: {last_error}",
            cause=last_error,
        )

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
                        instance.provider_name,
                        exc_info=True,
                    )
