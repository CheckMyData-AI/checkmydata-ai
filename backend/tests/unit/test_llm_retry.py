"""Unit tests for ``app.llm.retry.llm_call_with_retry``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.errors import LLMAllProvidersFailedError, LLMRateLimitError
from app.llm.retry import llm_call_with_retry


class _FakeResponse:
    def __init__(self, content: str = "ok") -> None:
        self.content = content


@pytest.mark.asyncio
async def test_returns_immediately_on_success():
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=_FakeResponse("hello"))
    out = await llm_call_with_retry(
        llm,
        messages=[],
        tools=None,
        preferred_provider=None,
        model=None,
    )
    assert out.content == "hello"
    llm.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.llm.retry.asyncio.sleep", AsyncMock())
    llm = MagicMock()
    llm.complete = AsyncMock(
        side_effect=[
            LLMRateLimitError("rate"),
            _FakeResponse("recovered"),
        ]
    )
    out = await llm_call_with_retry(
        llm,
        messages=[],
        tools=None,
        preferred_provider=None,
        model=None,
        max_retries=3,
        base_backoff=0.0,
    )
    assert out.content == "recovered"
    assert llm.complete.await_count == 2


@pytest.mark.asyncio
async def test_raises_last_exception_after_max_retries(monkeypatch):
    monkeypatch.setattr("app.llm.retry.asyncio.sleep", AsyncMock())
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=LLMRateLimitError("nope"))
    with pytest.raises(LLMRateLimitError):
        await llm_call_with_retry(
            llm,
            messages=[],
            tools=None,
            preferred_provider=None,
            model=None,
            max_retries=2,
            base_backoff=0.0,
        )
    assert llm.complete.await_count == 2


@pytest.mark.asyncio
async def test_all_providers_failed_is_not_retried():
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=LLMAllProvidersFailedError("all dead"))
    with pytest.raises(LLMAllProvidersFailedError):
        await llm_call_with_retry(
            llm,
            messages=[],
            tools=None,
            preferred_provider=None,
            model=None,
            max_retries=5,
            base_backoff=0.0,
        )
    llm.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_retry_callback_invoked(monkeypatch):
    monkeypatch.setattr("app.llm.retry.asyncio.sleep", AsyncMock())
    callback = AsyncMock()
    llm = MagicMock()
    llm.complete = AsyncMock(
        side_effect=[
            LLMRateLimitError("rate"),
            _FakeResponse("ok"),
        ]
    )
    await llm_call_with_retry(
        llm,
        messages=[],
        tools=None,
        preferred_provider=None,
        model=None,
        on_retry=callback,
        base_backoff=0.0,
    )
    callback.assert_awaited_once()
    args = callback.call_args.args
    assert args[0] == 1
    assert isinstance(args[1], LLMRateLimitError)


@pytest.mark.asyncio
async def test_on_retry_callback_failures_swallowed(monkeypatch):
    monkeypatch.setattr("app.llm.retry.asyncio.sleep", AsyncMock())
    callback = AsyncMock(side_effect=RuntimeError("oops"))
    llm = MagicMock()
    llm.complete = AsyncMock(
        side_effect=[
            LLMRateLimitError("rate"),
            _FakeResponse("ok"),
        ]
    )
    out = await llm_call_with_retry(
        llm,
        messages=[],
        tools=None,
        preferred_provider=None,
        model=None,
        on_retry=callback,
        base_backoff=0.0,
    )
    assert out.content == "ok"
