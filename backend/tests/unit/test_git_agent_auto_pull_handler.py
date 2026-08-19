"""AUD-0819-13: the auto-pull handler lets cancellation through.

The handler read `except (TimeoutError, Exception)`, which looks like a narrowing
and is not one — `TimeoutError` has been an `Exception` subclass since 3.11, so the
tuple's first member was dead and the clause caught everything either way. The
breadth is deliberate: an optional pull must not fail the answer.

A first attempt at this task also added `except CancelledError: raise`, on the
belief that a cancelled pull was being logged as a failure. **That was wrong, and
this test is what proved it** — the clause was removed and the suite stayed green,
because `asyncio.CancelledError` derives from `BaseException`, so `except
Exception` never caught it. The invariant still deserves pinning: widening the
clause to `BaseException` would silently absorb cancellation, and the first test
below fires if anyone does.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.git_agent import GitAgent


class _Project:
    repo_url = "git@example.com:acme/app.git"
    repo_branch = "main"
    ssh_key_id = None


@asynccontextmanager
async def _fake_session_factory():
    session = MagicMock()
    session.get = AsyncMock(return_value=_Project())
    yield session


def _agent() -> GitAgent:
    agent = GitAgent.__new__(GitAgent)
    agent._repo_analyzer = MagicMock()  # type: ignore[attr-defined]
    return agent


def _pull_raising(exc: type[BaseException] | BaseException):
    """Patch the whole path up to and including the pull, which raises *exc*."""

    async def _wait_for(coro, timeout=None):  # noqa: ARG001
        # Close the coroutine the real call would have awaited, so the mock does
        # not leave an un-awaited `to_thread` behind and warn about it.
        coro.close()
        raise exc

    return (
        patch("app.agents.git_agent.settings.git_agent_auto_pull", True),
        patch("app.models.base.async_session_factory", _fake_session_factory),
        patch("app.agents.git_agent.asyncio.wait_for", new=_wait_for),
    )


async def test_cancellation_propagates_rather_than_reading_as_a_pull_failure():
    a, b, c = _pull_raising(asyncio.CancelledError)
    with a, b, c, pytest.raises(asyncio.CancelledError):
        await _agent()._maybe_auto_pull("proj-1")


async def test_an_ordinary_failure_is_still_swallowed():
    """The breadth is the point: a failed optional pull must not fail the answer."""
    a, b, c = _pull_raising(RuntimeError("remote hung up"))
    with a, b, c:
        await _agent()._maybe_auto_pull("proj-1")  # no raise


async def test_a_timeout_is_still_swallowed():
    a, b, c = _pull_raising(TimeoutError)
    with a, b, c:
        await _agent()._maybe_auto_pull("proj-1")  # no raise


async def test_the_pull_is_skipped_entirely_when_the_flag_is_off():
    with patch("app.agents.git_agent.settings.git_agent_auto_pull", False):
        wf = AsyncMock()
        with patch("app.agents.git_agent.asyncio.wait_for", new=wf):
            await _agent()._maybe_auto_pull("proj-1")
        wf.assert_not_awaited()
