"""Tests for the R2 / C2 wiring of :class:`UsageSink` into ``LLMRouter``.

The router must:

* accept a ctor-level ``usage_sink`` (kw-only) and a per-call override;
* call ``sink.observe(...)`` exactly once on each successful provider
  response, populated from ``LLMResponse.usage``;
* swallow exceptions raised by ``sink.observe`` (telemetry must never abort
  the user-facing call);
* NOT call ``sink.observe`` when every provider in the fallback chain fails
  (the request raises and there is no usage to record).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.base import LLMResponse, Message
from app.llm.errors import LLMServerError
from app.llm.router import LLMRouter
from app.llm.usage_sink import AccumUsageSink, NullUsageSink


def _success_response() -> LLMResponse:
    return LLMResponse(
        content="ok",
        usage={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        provider="openai",
        model="gpt-4o",
    )


def _mock_provider(response: LLMResponse | Exception) -> MagicMock:
    provider = MagicMock()
    if isinstance(response, Exception):
        provider.complete = AsyncMock(side_effect=response)
    else:
        provider.complete = AsyncMock(return_value=response)
    return provider


@pytest.mark.asyncio
async def test_complete_invokes_sink_on_success() -> None:
    """A per-call ``usage_sink`` observes the response usage on success."""
    router = LLMRouter()
    router._instances["openai"] = _mock_provider(_success_response())
    accum = AccumUsageSink()

    with patch("app.llm.router.settings") as mock_settings:
        mock_settings.default_llm_provider = "openai"
        mock_settings.openai_api_key = "sk-openai"
        mock_settings.anthropic_api_key = ""
        mock_settings.openrouter_api_key = ""
        result = await router.complete(
            messages=[Message(role="user", content="hi")],
            preferred_provider="openai",
            usage_sink=accum,
        )

    assert result.content == "ok"
    assert accum.totals == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }


@pytest.mark.asyncio
async def test_ctor_sink_used_when_no_per_call_override() -> None:
    """When no per-call sink is given, the ctor-level sink is used."""
    accum = AccumUsageSink()
    router = LLMRouter(usage_sink=accum)
    router._instances["openai"] = _mock_provider(_success_response())

    with patch("app.llm.router.settings") as mock_settings:
        mock_settings.default_llm_provider = "openai"
        mock_settings.openai_api_key = "sk-openai"
        mock_settings.anthropic_api_key = ""
        mock_settings.openrouter_api_key = ""
        await router.complete(
            messages=[Message(role="user", content="hi")],
            preferred_provider="openai",
        )

    assert accum.totals["total_tokens"] == 20
    assert accum.totals["prompt_tokens"] == 12
    assert accum.totals["completion_tokens"] == 8


@pytest.mark.asyncio
async def test_per_call_sink_overrides_ctor_sink() -> None:
    """A per-call sink shadows the ctor sink — only the per-call sink observes."""
    ctor_sink = AccumUsageSink()
    per_call_sink = AccumUsageSink()
    router = LLMRouter(usage_sink=ctor_sink)
    router._instances["openai"] = _mock_provider(_success_response())

    with patch("app.llm.router.settings") as mock_settings:
        mock_settings.default_llm_provider = "openai"
        mock_settings.openai_api_key = "sk-openai"
        mock_settings.anthropic_api_key = ""
        mock_settings.openrouter_api_key = ""
        await router.complete(
            messages=[Message(role="user", content="hi")],
            preferred_provider="openai",
            usage_sink=per_call_sink,
        )

    assert per_call_sink.totals["total_tokens"] == 20
    assert ctor_sink.totals["total_tokens"] == 0


@pytest.mark.asyncio
async def test_sink_observe_exception_does_not_fail_call() -> None:
    """``sink.observe`` raising must not abort the user-facing call."""

    class BoomSink:
        observe_called = False

        async def observe(self, **_: object) -> None:
            BoomSink.observe_called = True
            raise RuntimeError("telemetry down")

        def budget_exceeded(self) -> str | None:
            return None

    router = LLMRouter()
    router._instances["openai"] = _mock_provider(_success_response())
    sink = BoomSink()

    with patch("app.llm.router.settings") as mock_settings:
        mock_settings.default_llm_provider = "openai"
        mock_settings.openai_api_key = "sk-openai"
        mock_settings.anthropic_api_key = ""
        mock_settings.openrouter_api_key = ""
        result = await router.complete(
            messages=[Message(role="user", content="hi")],
            preferred_provider="openai",
            usage_sink=sink,
        )

    assert result.content == "ok"
    assert BoomSink.observe_called is True


@pytest.mark.asyncio
async def test_no_observe_when_all_providers_fail() -> None:
    """No ``observe`` call on total chain failure."""

    class CountingSink:
        def __init__(self) -> None:
            self.calls = 0

        async def observe(self, **_: object) -> None:
            self.calls += 1

        def budget_exceeded(self) -> str | None:
            return None

    router = LLMRouter()
    for name in ("openai", "anthropic", "openrouter"):
        router._instances[name] = _mock_provider(LLMServerError(f"{name} down"))
    sink = CountingSink()

    with patch("app.llm.router.settings") as mock_settings:
        mock_settings.default_llm_provider = "openai"
        mock_settings.openai_api_key = "sk-openai"
        mock_settings.anthropic_api_key = "sk-anthropic"
        mock_settings.openrouter_api_key = "sk-openrouter"
        with (
            patch("app.llm.router._MAX_RETRIES_PER_PROVIDER", 1),
            patch("app.llm.router.asyncio.sleep", new=AsyncMock(return_value=None)),
        ):
            from app.llm.errors import LLMAllProvidersFailedError

            with pytest.raises(LLMAllProvidersFailedError):
                await router.complete(
                    messages=[Message(role="user", content="hi")],
                    usage_sink=sink,
                )

    assert sink.calls == 0


@pytest.mark.asyncio
async def test_default_sink_is_null_when_unspecified() -> None:
    """When neither ctor nor per-call sink is given, default is ``NullUsageSink``."""
    router = LLMRouter()
    assert isinstance(router._sink, NullUsageSink)
