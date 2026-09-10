"""DEFAULT_LLM_MODEL is how an operator moves every unpinned call site at once.

Until 2026-09-09 the deployment default lived as a hardcoded constant inside each
adapter (`openrouter_adapter.DEFAULT_MODEL = "openai/gpt-4o"`), so the only ways to
change what the background workload ran on were a code deploy or per-project rows.
Measured on production the day this was written: 8.06M tokens in 30 days rode that
hardcoded default — code↔DB sync, validators, the learning analyzer — at gpt-4o
pricing, while both halves that HAD a knob were already pointed at cheaper models.

The setting threads through ``LLMRouter.complete``/``stream``: a caller that names
no model gets ``settings.default_llm_model``; an explicit model always wins; an
empty setting keeps the adapter's own default, which is what self-hosted installs
that never heard of the knob expect.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings, settings
from app.llm.base import LLMResponse, Message
from app.llm.router import LLMRouter


def _response() -> LLMResponse:
    return LLMResponse(content="ok", provider="openrouter", model="whatever", usage={})


@pytest.fixture()
def router_with_spy():
    router = LLMRouter()
    provider = AsyncMock()
    provider.complete = AsyncMock(return_value=_response())
    with (
        patch.object(router, "_get_provider", return_value=provider),
        patch.object(router, "_get_fallback_chain", return_value=["openrouter"]),
    ):
        yield router, provider


async def _model_sent(provider: AsyncMock) -> str | None:
    call = provider.complete.await_args
    if call.kwargs and "model" in call.kwargs:
        return call.kwargs["model"]
    # complete(messages, tools, model, ...) — positional shape
    return call.args[2] if len(call.args) > 2 else None


class TestTheDefaultThreadsThrough:
    async def test_no_model_resolves_to_the_deployment_default(self, router_with_spy):
        router, provider = router_with_spy
        with patch.object(settings, "default_llm_model", "deepseek/deepseek-v4-flash-0731"):
            await router.complete(messages=[Message(role="user", content="hi")])
        assert await _model_sent(provider) == "deepseek/deepseek-v4-flash-0731"

    async def test_an_explicit_model_always_wins(self, router_with_spy):
        router, provider = router_with_spy
        with patch.object(settings, "default_llm_model", "deepseek/deepseek-v4-flash-0731"):
            await router.complete(
                messages=[Message(role="user", content="hi")],
                model="z-ai/glm-5.2",
            )
        assert await _model_sent(provider) == "z-ai/glm-5.2"

    async def test_an_empty_default_keeps_the_adapter_default(self, router_with_spy):
        """None must reach the adapter, whose own DEFAULT_MODEL then applies —
        the pre-knob behaviour, preserved for installs that never set it."""
        router, provider = router_with_spy
        with patch.object(settings, "default_llm_model", ""):
            await router.complete(messages=[Message(role="user", content="hi")])
        assert await _model_sent(provider) is None


class TestTheBootRefusesAContradiction:
    """A slash-namespaced id is an OpenRouter id; handed to a native adapter it
    404s on the first fallback instead of at start-up — the wrong place to find out."""

    def test_openrouter_id_with_native_provider_is_refused(self):
        with pytest.raises(ValueError, match="OpenRouter id"):
            Settings(
                default_llm_provider="openai",
                default_llm_model="deepseek/deepseek-v4-flash-0731",
                master_encryption_key="x" * 44,
                jwt_secret="s" * 32,
            )

    def test_openrouter_id_with_openrouter_provider_boots(self):
        s = Settings(
            default_llm_provider="openrouter",
            default_llm_model="deepseek/deepseek-v4-flash-0731",
            master_encryption_key="x" * 44,
            jwt_secret="s" * 32,
        )
        assert s.default_llm_model == "deepseek/deepseek-v4-flash-0731"

    def test_bare_model_name_needs_no_openrouter(self):
        s = Settings(
            default_llm_provider="openai",
            default_llm_model="gpt-4o-mini",
            master_encryption_key="x" * 44,
            jwt_secret="s" * 32,
        )
        assert s.default_llm_model == "gpt-4o-mini"
