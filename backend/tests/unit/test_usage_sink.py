"""Tests for app.llm.usage_sink (R2 / C1)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.usage_sink import AccumUsageSink, DbUsageSink, NullUsageSink


@pytest.mark.asyncio
async def test_null_sink_observe_noop() -> None:
    sink = NullUsageSink()
    result = await sink.observe(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        provider="openai",
        model="gpt-4o",
    )
    assert result is None
    assert sink.budget_exceeded() is None


@pytest.mark.asyncio
async def test_accum_sink_adds_totals() -> None:
    sink = AccumUsageSink()
    await sink.observe(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=0,
        provider="openai",
        model="gpt-4o",
    )
    await sink.observe(
        prompt_tokens=3,
        completion_tokens=2,
        total_tokens=0,
        provider="openai",
        model="gpt-4o",
    )
    assert sink.totals == {
        "prompt_tokens": 13,
        "completion_tokens": 7,
        "total_tokens": 20,
    }
    assert sink.budget_exceeded() is None


@pytest.mark.asyncio
async def test_accum_sink_uses_explicit_total_when_nonzero() -> None:
    sink = AccumUsageSink()
    await sink.observe(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=100,
        provider="openai",
        model="gpt-4o",
    )
    assert sink.totals["total_tokens"] == 100


@pytest.mark.asyncio
async def test_db_sink_records_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """DbUsageSink.observe opens a session, calls UsageService.record_usage
    with the right kwargs, and threads through to check_token_budget."""
    fake_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory():  # type: ignore[no-untyped-def]
        yield fake_session

    monkeypatch.setattr(
        "app.llm.usage_sink.async_session_factory",
        fake_factory,
    )

    record_mock = AsyncMock(return_value=MagicMock())
    check_mock = AsyncMock(return_value=None)

    class FakeUsageService:
        def __init__(self) -> None:
            self.record_usage = record_mock
            self.check_token_budget = check_mock

    monkeypatch.setattr("app.llm.usage_sink.UsageService", FakeUsageService)

    sink = DbUsageSink(
        user_id="user-1",
        project_id="proj-1",
        session_id="sess-1",
        message_id="msg-1",
    )
    await sink.observe(
        prompt_tokens=11,
        completion_tokens=22,
        total_tokens=33,
        provider="anthropic",
        model="claude-opus-4",
    )

    record_mock.assert_awaited_once()
    kwargs = record_mock.await_args.kwargs
    assert kwargs["user_id"] == "user-1"
    assert kwargs["project_id"] == "proj-1"
    assert kwargs["session_id"] == "sess-1"
    assert kwargs["message_id"] == "msg-1"
    assert kwargs["provider"] == "anthropic"
    assert kwargs["model"] == "claude-opus-4"
    assert kwargs["prompt_tokens"] == 11
    assert kwargs["completion_tokens"] == 22
    assert kwargs["total_tokens"] == 33
    assert kwargs["estimated_cost_usd"] is None

    check_mock.assert_awaited_once()
    check_args = check_mock.await_args
    # check_token_budget(db, user_id)
    assert check_args.args[1] == "user-1" or check_args.kwargs.get("user_id") == "user-1"

    assert sink.budget_exceeded() is None


@pytest.mark.asyncio
async def test_db_sink_threads_to_accum(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory():  # type: ignore[no-untyped-def]
        yield fake_session

    monkeypatch.setattr("app.llm.usage_sink.async_session_factory", fake_factory)

    class FakeUsageService:
        def __init__(self) -> None:
            self.record_usage = AsyncMock(return_value=MagicMock())
            self.check_token_budget = AsyncMock(return_value=None)

    monkeypatch.setattr("app.llm.usage_sink.UsageService", FakeUsageService)

    accum = AccumUsageSink()
    sink = DbUsageSink(user_id="u", project_id="p", accum=accum)
    await sink.observe(
        prompt_tokens=4,
        completion_tokens=6,
        total_tokens=10,
        provider="openai",
        model="gpt-4o-mini",
    )
    assert accum.totals == {
        "prompt_tokens": 4,
        "completion_tokens": 6,
        "total_tokens": 10,
    }


@pytest.mark.asyncio
async def test_db_sink_budget_exceeded_after_breach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory():  # type: ignore[no-untyped-def]
        yield fake_session

    monkeypatch.setattr("app.llm.usage_sink.async_session_factory", fake_factory)

    class FakeUsageService:
        def __init__(self) -> None:
            self.record_usage = AsyncMock(return_value=MagicMock())
            self.check_token_budget = AsyncMock(
                return_value="Daily limit exceeded — upgrade your plan."
            )

    monkeypatch.setattr("app.llm.usage_sink.UsageService", FakeUsageService)

    sink = DbUsageSink(user_id="u", project_id="p")
    assert sink.budget_exceeded() is None

    await sink.observe(
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        provider="openai",
        model="gpt-4o",
    )

    assert sink.budget_exceeded() == "Daily limit exceeded — upgrade your plan."


@pytest.mark.asyncio
async def test_db_sink_swallows_write_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory():  # type: ignore[no-untyped-def]
        yield fake_session

    monkeypatch.setattr("app.llm.usage_sink.async_session_factory", fake_factory)

    class FakeUsageService:
        def __init__(self) -> None:
            self.record_usage = AsyncMock(side_effect=RuntimeError("DB down"))
            self.check_token_budget = AsyncMock(return_value=None)

    monkeypatch.setattr("app.llm.usage_sink.UsageService", FakeUsageService)

    sink = DbUsageSink(user_id="u", project_id="p")
    # Must not raise
    await sink.observe(
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        provider="openai",
        model="gpt-4o",
    )
    assert sink.budget_exceeded() is None
