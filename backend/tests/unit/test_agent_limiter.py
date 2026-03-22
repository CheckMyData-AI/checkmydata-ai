"""Unit tests for AgentLimiter."""

from types import SimpleNamespace

import pytest

from app.core.agent_limiter import AgentLimiter


@pytest.fixture
def limiter(monkeypatch: pytest.MonkeyPatch) -> AgentLimiter:
    monkeypatch.setattr(
        "app.core.agent_limiter.settings",
        SimpleNamespace(max_concurrent_agent_calls=2, max_agent_calls_per_hour=5),
    )
    return AgentLimiter()


def test_acquire_succeeds_under_limit(limiter: AgentLimiter) -> None:
    assert limiter.acquire("user-a") is None
    assert limiter.acquire("user-a") is None


def test_acquire_blocks_when_concurrent_limit_reached(limiter: AgentLimiter) -> None:
    assert limiter.acquire("user-b") is None
    assert limiter.acquire("user-b") is None
    err = limiter.acquire("user-b")
    assert err is not None
    assert "concurrent" in err.lower()
    assert "2" in err


def test_release_frees_slot(limiter: AgentLimiter) -> None:
    assert limiter.acquire("user-c") is None
    assert limiter.acquire("user-c") is None
    limiter.release("user-c")
    assert limiter.acquire("user-c") is None


def test_hourly_limit_blocks(limiter: AgentLimiter) -> None:
    for _ in range(5):
        assert limiter.acquire("user-d") is None
        limiter.release("user-d")
    err = limiter.acquire("user-d")
    assert err is not None
    assert "hour" in err.lower()
    assert "5" in err


def test_release_does_not_go_negative(limiter: AgentLimiter) -> None:
    limiter.release("user-e")
    limiter.release("user-e")
    assert limiter._concurrent["user-e"] == 0
