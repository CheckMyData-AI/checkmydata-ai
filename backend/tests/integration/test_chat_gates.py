"""The gates in front of the agent — the ones that cost money or serialize a session.

Coverage of `app/api/routes/chat.py` was 35% on 2026-08-25, and the uncovered lines were
not obscure branches. **Every gate standing between a user and an agent run had no test
at all**, on both entry points:

| Line | Gate | Covered before |
|---|---|---|
| `chat.py:247` | token budget → 429 (`/ask`) | no |
| `chat.py:283` | session already processing → 409 (`/ask`) | no |
| `chat.py:297` | agent concurrency slot → 429 (`/ask`) | no |
| `chat.py:592` | slot released in `finally` | no |
| `chat.py:615` | token budget → 429 (`/ask/stream`) | no |
| `chat.py:649` | session already processing → 409 (`/ask/stream`) | no |
| `chat.py:758` | agent concurrency slot → 429 (`/ask/stream`) | no |

These are the two things a paid product cannot afford to get wrong quietly: the
**budget** stops a user spending past what they bought, and the **slot** stops one user
running unbounded concurrent pipelines on shared capacity. A regression in either is
invisible — no error, no crash, just work that should not have happened — which is
exactly the class of defect a test finds and an operator does not.

The `finally` release is the other half of the slot, and its absence is worse than the
gate's: a slot acquired and never released is a user who is throttled forever with
nothing in flight. `_limiter_acquired` exists so a **denied** acquire is not released —
releasing a slot that was never taken hands out capacity that does not exist.

Each test drives the real route through the real dependency graph and fails the gate at
its own seam, so nothing here depends on the agent running.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.agent_limiter import agent_limiter
from app.services.chat_service import session_processing_lock

# No `pytestmark = pytest.mark.asyncio`: `asyncio_mode = "auto"` is set project-wide,
# and a module-level mark would also land on the two synchronous tests below, where
# pytest-asyncio then looks for a `self` fixture and errors.


async def _project(auth_client) -> str:
    resp = await auth_client.post("/api/projects", json={"name": "Gates"})
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _session(auth_client, project_id: str) -> str:
    resp = await auth_client.post(
        "/api/chat/sessions", json={"project_id": project_id, "title": "gate"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


class TestTokenBudget:
    """`/api/chat/ask` and `/ask/stream` must refuse before any LLM work happens.

    Checked *before* the agent starts on purpose (`chat.py:247`, `:613`): a budget
    enforced after the run has already been paid for.
    """

    @pytest.mark.parametrize("path", ["/api/chat/ask", "/api/chat/ask/stream"])
    async def test_an_exhausted_budget_is_429_and_says_why(self, auth_client, monkeypatch, path):
        pid = await _project(auth_client)
        monkeypatch.setattr(
            "app.api.routes.chat._usage_svc.check_token_budget",
            lambda db, user_id: _returns("Daily token limit reached"),
        )

        resp = await auth_client.post(path, json={"project_id": pid, "message": "hi"})

        assert resp.status_code == 429, resp.text
        assert "token" in resp.text.lower(), (
            "a 429 that does not name the budget is indistinguishable from a rate limit, "
            "and the user cannot tell whether waiting helps"
        )

    async def test_a_budget_with_room_does_not_block(self, auth_client, monkeypatch):
        """The gate must not be the reason a healthy request fails."""
        pid = await _project(auth_client)
        monkeypatch.setattr(
            "app.api.routes.chat._usage_svc.check_token_budget", lambda db, user_id: _returns(None)
        )
        monkeypatch.setattr(
            "app.core.agent_limiter.agent_limiter.acquire",
            lambda user_id: _returns("stopped after the budget gate"),
        )

        resp = await auth_client.post("/api/chat/ask", json={"project_id": pid, "message": "hi"})

        assert resp.status_code == 429
        assert "stopped after the budget gate" in resp.text, (
            "the request passed the budget and was stopped by the next gate, which is "
            "what proves the budget did not block it"
        )


class TestAgentConcurrencySlot:
    """`agent_limiter` bounds `max_concurrent_agent_calls` / `max_agent_calls_per_hour`.

    `/ask` acquired no slot at all until F-CHAT-08 — a user could run unbounded
    concurrent pipelines through it while `/ask/stream` and the WS path were bounded.
    """

    @pytest.mark.parametrize("path", ["/api/chat/ask", "/api/chat/ask/stream"])
    async def test_a_denied_slot_is_429(self, auth_client, monkeypatch, path):
        pid = await _project(auth_client)
        monkeypatch.setattr(
            "app.api.routes.chat._usage_svc.check_token_budget", lambda db, user_id: _returns(None)
        )
        monkeypatch.setattr(
            "app.core.agent_limiter.agent_limiter.acquire",
            lambda user_id: _returns("Too many concurrent agent calls"),
        )

        resp = await auth_client.post(path, json={"project_id": pid, "message": "hi"})

        assert resp.status_code == 429
        assert "concurrent" in resp.text.lower()

    async def test_a_denied_slot_is_not_released(self, auth_client, monkeypatch):
        """Releasing a slot that was never acquired hands out capacity that does not
        exist — the `_limiter_acquired` flag is the whole reason it is a flag."""
        pid = await _project(auth_client)
        released: list[str] = []
        monkeypatch.setattr(
            "app.api.routes.chat._usage_svc.check_token_budget", lambda db, user_id: _returns(None)
        )
        monkeypatch.setattr(
            "app.core.agent_limiter.agent_limiter.acquire",
            lambda user_id: _returns("Too many concurrent agent calls"),
        )
        monkeypatch.setattr(
            "app.core.agent_limiter.agent_limiter.release",
            lambda user_id: _record(released, user_id),
        )

        resp = await auth_client.post("/api/chat/ask", json={"project_id": pid, "message": "hi"})

        assert resp.status_code == 429
        assert released == [], f"released a slot that was refused: {released}"

    async def test_a_slot_taken_is_a_slot_given_back(self, auth_client, monkeypatch):
        """A slot acquired and never released throttles a user forever with nothing in
        flight — worse than the gate being absent, because it is silent and permanent."""
        pid = await _project(auth_client)
        released: list[str] = []
        monkeypatch.setattr(
            "app.api.routes.chat._usage_svc.check_token_budget", lambda db, user_id: _returns(None)
        )
        monkeypatch.setattr(
            "app.core.agent_limiter.agent_limiter.acquire", lambda user_id: _returns(None)
        )
        monkeypatch.setattr(
            "app.core.agent_limiter.agent_limiter.release",
            lambda user_id: _record(released, user_id),
        )
        # Fail the agent run itself: the release lives in a `finally`, so the crash path
        # is the one worth proving.
        # The CLASS attribute, not `chat._agent.run`. Patching the module-level
        # singleton's `run` installs an *instance* attribute, and monkeypatch's undo
        # writes the bound method back as one — where it shadows the class method
        # permanently. Every later test that patches `ConversationalAgent.run` then
        # patches something nothing looks at, and the real agent runs. That is exactly
        # what happened to `test_sse_flow.py` when this file was written the other way.
        monkeypatch.setattr(
            "app.core.agent.ConversationalAgent.run",
            lambda *a, **k: _raises(RuntimeError("agent exploded")),
        )

        await auth_client.post("/api/chat/ask", json={"project_id": pid, "message": "hi"})

        assert len(released) == 1, (
            "the slot was not returned after the run failed; the next request from this "
            "user is throttled against work that is no longer running"
        )


class TestSessionIsSerialized:
    """One session, one request in flight. A second concurrent request gets 409 rather
    than interleaving two agent runs over the same message history."""

    @pytest.mark.parametrize("path", ["/api/chat/ask", "/api/chat/ask/stream"])
    async def test_a_busy_session_is_409(self, auth_client, monkeypatch, path):
        pid = await _project(auth_client)
        sid = await _session(auth_client, pid)
        monkeypatch.setattr(
            "app.api.routes.chat._usage_svc.check_token_budget", lambda db, user_id: _returns(None)
        )

        # Hold the real lock, exactly as an in-flight request would.
        async with session_processing_lock(sid):
            resp = await auth_client.post(
                path, json={"project_id": pid, "session_id": sid, "message": "hi"}
            )

        assert resp.status_code == 409, resp.text
        assert "processing" in resp.text.lower()

    async def test_the_lock_is_released_when_the_request_ends(self, auth_client, monkeypatch):
        """A lock left held turns one crashed request into a session nobody can use
        again — the 409 would then be permanent rather than a moment of contention."""
        pid = await _project(auth_client)
        sid = await _session(auth_client, pid)
        monkeypatch.setattr(
            "app.api.routes.chat._usage_svc.check_token_budget", lambda db, user_id: _returns(None)
        )
        # The CLASS attribute, never `chat._agent.run` — see the note above.
        monkeypatch.setattr(
            "app.core.agent.ConversationalAgent.run",
            lambda *a, **k: _raises(RuntimeError("agent exploded")),
        )

        await auth_client.post(
            "/api/chat/ask", json={"project_id": pid, "session_id": sid, "message": "hi"}
        )

        # If the lock were still held this would raise SessionBusyError.
        async with session_processing_lock(sid):
            pass


class TestTheGatesAreOrdered:
    def test_the_budget_is_checked_before_the_slot_is_taken(self) -> None:
        """Order is the contract. Acquiring a slot for a request that the budget will
        refuse burns shared capacity on work that was never going to run — and the slot
        is per-user, so it throttles the same user twice for one refusal."""
        from pathlib import Path

        source = Path(__file__).resolve().parents[2] / "app" / "api" / "routes" / "chat.py"
        text = source.read_text(encoding="utf-8")
        budget = text.index("budget_error = await _check_token_budget")
        slot = text.index("limit_err = await agent_limiter.acquire")
        assert budget < slot


# --- small awaitable helpers -------------------------------------------------
# The routes `await` these attributes, so a plain lambda is not enough; each of these
# returns a coroutine the route can await.


async def _returns(value):
    return value


async def _record(sink: list, user_id: str) -> None:
    sink.append(user_id)


async def _raises(exc: BaseException):
    raise exc


def test_agent_limiter_is_importable() -> None:
    """The monkeypatch targets above are string paths; a rename would silently patch
    nothing and every test here would pass for the wrong reason."""
    assert hasattr(agent_limiter, "acquire")
    assert hasattr(agent_limiter, "release")
    assert asyncio.iscoroutinefunction(agent_limiter.acquire)
