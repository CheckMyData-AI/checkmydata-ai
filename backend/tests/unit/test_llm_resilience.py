"""LLM provider resilience tests.

Covers fallback chains, retry behavior, non-retryable error handling,
streaming partial failures, and all-providers-failed scenarios.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.llm.base import LLMResponse, Message
from app.llm.errors import (
    LLMAllProvidersFailedError,
    LLMAuthError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    LLMTokenLimitError,
)
from app.llm.router import LLMRouter


def _msg() -> list[Message]:
    return [Message(role="user", content="hello")]


def _ok_response(provider: str = "openai") -> LLMResponse:
    return LLMResponse(
        content="ok",
        tool_calls=[],
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        provider=provider,
    )


@pytest.fixture
def router():
    r = LLMRouter()
    r._fallback_order = ["openai", "anthropic", "openrouter"]
    return r


def _patch_chain(router, chain=None):
    """Patch _get_fallback_chain to bypass API-key checks in CI."""
    return patch.object(
        router,
        "_get_fallback_chain",
        return_value=chain or ["openai", "anthropic", "openrouter"],
    )


class TestFallbackChain:
    @pytest.mark.asyncio
    async def test_primary_succeeds_no_fallback(self, router):
        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=_ok_response())
        with (
            _patch_chain(router, ["openai"]),
            patch.object(router, "_get_provider", return_value=mock_provider),
        ):
            resp = await router.complete(_msg())
        assert resp.content == "ok"

    @pytest.mark.asyncio
    async def test_primary_fails_fallback_succeeds(self, router):
        primary_mock = AsyncMock()
        primary_mock.complete = AsyncMock(side_effect=LLMServerError("down"))
        fallback_mock = AsyncMock()
        fallback_mock.complete = AsyncMock(return_value=_ok_response("anthropic"))

        def _get(name):
            if name == "openai":
                return primary_mock
            return fallback_mock

        with (
            _patch_chain(router, ["openai", "anthropic"]),
            patch.object(router, "_get_provider", side_effect=_get),
            patch("app.llm.router._MAX_RETRIES_PER_PROVIDER", 1),
            patch("app.llm.router._BASE_BACKOFF_SECONDS", 0.01),
        ):
            resp = await router.complete(_msg())
        assert resp.provider == "anthropic"

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises(self, router):
        mock = AsyncMock()
        mock.complete = AsyncMock(side_effect=LLMServerError("down"))
        with (
            _patch_chain(router),
            patch.object(router, "_get_provider", return_value=mock),
            patch("app.llm.router._MAX_RETRIES_PER_PROVIDER", 1),
            patch("app.llm.router._BASE_BACKOFF_SECONDS", 0.01),
            pytest.raises(LLMAllProvidersFailedError),
        ):
            await router.complete(_msg())

    @pytest.mark.asyncio
    async def test_auth_error_not_retried_stops_chain(self, router):
        mock = AsyncMock()
        mock.complete = AsyncMock(side_effect=LLMAuthError("bad key"))
        with (
            _patch_chain(router),
            patch.object(router, "_get_provider", return_value=mock),
            pytest.raises(LLMAllProvidersFailedError),
        ):
            await router.complete(_msg())
        assert mock.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_token_limit_not_retried_but_falls_back(self, router):
        """LLMTokenLimitError is not retried on the same provider but
        does fall back to the next provider (which may have a larger
        context window)."""
        mock = AsyncMock()
        mock.complete = AsyncMock(side_effect=LLMTokenLimitError("too big"))
        with (
            _patch_chain(router),
            patch.object(router, "_get_provider", return_value=mock),
            pytest.raises(LLMAllProvidersFailedError),
        ):
            await router.complete(_msg())
        assert mock.complete.call_count == 3


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_rate_limit_retried(self, router):
        mock = AsyncMock()
        mock.complete = AsyncMock(side_effect=[LLMRateLimitError("429"), _ok_response()])
        with (
            _patch_chain(router, ["openai"]),
            patch.object(router, "_get_provider", return_value=mock),
            patch("app.llm.router._BASE_BACKOFF_SECONDS", 0.01),
        ):
            resp = await router.complete(_msg())
        assert resp.content == "ok"
        assert mock.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_retried(self, router):
        mock = AsyncMock()
        mock.complete = AsyncMock(side_effect=[LLMTimeoutError("slow"), _ok_response()])
        with (
            _patch_chain(router, ["openai"]),
            patch.object(router, "_get_provider", return_value=mock),
            patch("app.llm.router._BASE_BACKOFF_SECONDS", 0.01),
        ):
            resp = await router.complete(_msg())
        assert resp.content == "ok"

    @pytest.mark.asyncio
    async def test_connection_error_retried(self, router):
        mock = AsyncMock()
        mock.complete = AsyncMock(side_effect=[LLMConnectionError("network"), _ok_response()])
        with (
            _patch_chain(router, ["openai"]),
            patch.object(router, "_get_provider", return_value=mock),
            patch("app.llm.router._BASE_BACKOFF_SECONDS", 0.01),
        ):
            resp = await router.complete(_msg())
        assert resp.content == "ok"


class TestErrorHierarchy:
    def test_retryable_errors_have_flag(self):
        assert LLMRateLimitError().is_retryable is True
        assert LLMServerError().is_retryable is True
        assert LLMTimeoutError().is_retryable is True
        assert LLMConnectionError().is_retryable is True
        assert LLMAllProvidersFailedError().is_retryable is True

    def test_non_retryable_errors_have_flag(self):
        assert LLMAuthError().is_retryable is False
        assert LLMTokenLimitError().is_retryable is False

    def test_user_messages_are_friendly(self):
        for cls in [
            LLMRateLimitError,
            LLMServerError,
            LLMAuthError,
            LLMTokenLimitError,
            LLMTimeoutError,
            LLMConnectionError,
            LLMAllProvidersFailedError,
        ]:
            err = cls("raw details")
            assert len(err.user_message) > 10
            assert "raw details" not in err.user_message

    def test_retry_after_on_rate_limit(self):
        err = LLMRateLimitError("429", retry_after=10.0)
        assert err.retry_after_seconds == 10.0

    def test_default_retry_after(self):
        assert LLMRateLimitError().retry_after_seconds == 5.0
        assert LLMServerError().retry_after_seconds == 2.0


class TestHealthMarking:
    def test_mark_unhealthy(self, router):
        router.mark_unhealthy("openai")
        assert "openai" in router._unhealthy

    def test_mark_healthy_clears(self, router):
        router.mark_unhealthy("openai")
        router.mark_healthy("openai")
        assert "openai" not in router._unhealthy

    def test_unknown_provider_raises(self, router):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            router._get_provider("nonexistent")
