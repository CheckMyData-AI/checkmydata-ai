"""F-LLM-01 — a failed provider silently sent the request to a different vendor.

`LLMRouter` walks a fallback chain, and the messages it retries with are the user's
question, their database schema, and their query results. When the chosen provider fails,
that content goes to the next vendor in the list — with nothing in the logs saying *this
request's data went to OpenAI after Anthropic failed*, and no way for a deployment to say
"never".

That is a data-processing question, not only a reliability one. A deployment that chose
Anthropic deliberately — because that is who its customers were told about — has no
mechanism here to make the choice binding, and no record afterwards that it was crossed.

**The default stays on.** Turning fallback off by default would trade every deployment's
resilience for a guarantee most of them did not ask for, which is the same shape as the
connection-host guard: a control that breaks the normal case gets switched off, and then
it protects nobody. What changes is that crossing a provider boundary is now *loud* and
*refusable*.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.llm.base import LLMResponse
from app.llm.errors import LLMAllProvidersFailedError, LLMError
from app.llm.router import LLMRouter


def _ok(provider: str) -> LLMResponse:
    return LLMResponse(content="hi", provider=provider, model="m", usage={})


@pytest.fixture(autouse=True)
def _all_providers_configured(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "k")
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    monkeypatch.setattr(settings, "llm_allow_provider_fallback", True)


def _router_where(first_fails: bool) -> tuple[LLMRouter, AsyncMock]:
    router = LLMRouter()
    calls: list[str] = []

    async def _call(provider, provider_name, *a, **kw):
        calls.append(provider_name)
        if first_fails and len(calls) == 1:
            raise LLMError("upstream 503", is_retryable=True)
        return _ok(provider_name)

    router._call_with_retry = AsyncMock(side_effect=_call)  # type: ignore[method-assign]
    return router, router._call_with_retry  # type: ignore[return-value]


class TestCrossingAProviderBoundaryIsLoud:
    async def test_a_fallback_says_which_vendor_received_the_data(self, caplog):
        router, _ = _router_where(first_fails=True)

        with caplog.at_level(logging.WARNING):
            await router.complete([], preferred_provider="anthropic")

        crossings = [r.getMessage() for r in caplog.records if "fell back" in r.message]
        assert crossings, "nothing in the log names the vendor that received the request"
        assert "anthropic" in crossings[0]
        assert "openai" in crossings[0]

    async def test_the_happy_path_says_nothing(self, caplog):
        """A line on every successful call is a line nobody reads."""
        router, _ = _router_where(first_fails=False)

        with caplog.at_level(logging.WARNING):
            await router.complete([], preferred_provider="anthropic")

        assert not [r for r in caplog.records if "fell back" in r.message]


class TestFallbackCanBeRefused:
    async def test_the_chosen_provider_is_binding_when_fallback_is_off(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_allow_provider_fallback", False)
        router, call = _router_where(first_fails=True)

        with pytest.raises(LLMAllProvidersFailedError):
            await router.complete([], preferred_provider="anthropic")

        assert call.await_count == 1, "the request was sent to a second vendor anyway"

    async def test_the_default_still_falls_back(self):
        """Resilience is the shipped behaviour; the guarantee is opt-in. Reversing that
        trades every deployment's uptime for a promise most never asked for."""
        router, call = _router_where(first_fails=True)

        response = await router.complete([], preferred_provider="anthropic")

        assert response.provider == "openai"
        assert call.await_count == 2

    async def test_turning_it_off_does_not_break_the_happy_path(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_allow_provider_fallback", False)
        router, call = _router_where(first_fails=False)

        response = await router.complete([], preferred_provider="anthropic")

        assert response.provider == "anthropic"
        assert call.await_count == 1


class TestItAppliesToStreamingToo:
    async def test_the_streaming_path_honours_the_setting(self, monkeypatch):
        """Two fallback loops in one file is how one of them keeps an old rule. The
        streaming entry point walks its own copy, calling `provider.stream` directly
        rather than the retry wrapper the non-streaming path uses."""
        monkeypatch.setattr(settings, "llm_allow_provider_fallback", False)
        router = LLMRouter()
        calls: list[str] = []

        class _Failing:
            def __init__(self, name: str):
                self._name = name

            async def stream(self, **kwargs):
                calls.append(self._name)
                raise LLMError("upstream 503", is_retryable=True)
                yield ""  # pragma: no cover — makes this an async generator

        with patch.object(router, "_get_provider", side_effect=lambda n: _Failing(n)):
            with pytest.raises(LLMAllProvidersFailedError):
                async for _ in router.stream([], preferred_provider="anthropic"):
                    pass

        assert calls == ["anthropic"]
