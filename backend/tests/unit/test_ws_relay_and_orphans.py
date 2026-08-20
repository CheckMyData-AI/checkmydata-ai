"""Two WebSocket findings, both with a correct implementation twenty lines away.

`/api/chat/ws/{project}/{connection}` is documented public API (`API.md:206`) that the
product's own UI does not use — it speaks SSE. Both of these were filed this morning with
a user-facing impact the code cannot produce (a tab reload opens no WebSocket; the
reasoning panel is fed by SSE), and both survive for third-party clients of the documented
endpoint with the severity re-argued.

**F-CHAT-03 — the relay gave up after 60 seconds of quiet.** `asyncio.wait_for(queue.get(),
timeout=60)` with `except TimeoutError: logger.debug(...)`, so a step that legitimately
takes longer — a large `ast_parse`, a slow warehouse query — ended the event stream while
the run continued. The client got nothing more and no reason.

The SSE relay in the same file already solves this correctly (`chat.py:1032-1043`): poll
on a short timeout, emit a heartbeat, hold an overall deadline, and **continue** rather
than exit. A gap in events is not the end of a run. This aligns the WS relay with it.

**F-CHAT-02 — every connect wrote a session row**, before the receive loop and
unconditionally, so a client that connects and sends nothing leaves one behind. The
protocol constrains the fix: `session_created` is sent immediately after, so the client
expects an id at connect time and creating lazily would break it. Reusing an existing
*empty* session for the same `(project, connection, user)` bounds the orphans to one per
triple and keeps the contract exactly.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from app.api.routes import chat as chat_route


class TestTheRelayDoesNotGiveUpOnQuiet:
    def test_the_sixty_second_literal_is_gone(self):
        src = inspect.getsource(chat_route.chat_websocket)

        assert "timeout=60)" not in src, (
            "a hardcoded 60 s beside a configured ws_idle_timeout_seconds of 300 is an "
            "unnamed number five times tighter than the tolerance next to it"
        )

    def test_the_timeout_is_configurable(self):
        from app.config import settings

        assert settings.ws_event_relay_timeout_seconds > 0

    async def test_a_gap_in_events_does_not_end_the_stream(self, monkeypatch):
        """The finding itself: the relay must survive a quiet period and still deliver
        what comes after it."""
        from app.config import settings

        monkeypatch.setattr(settings, "ws_event_relay_poll_seconds", 0.01)
        monkeypatch.setattr(settings, "ws_event_relay_timeout_seconds", 5)

        queue: asyncio.Queue = asyncio.Queue()
        sent: list[dict] = []

        class _WS:
            async def send_json(self, payload):
                sent.append(payload)

        relay = asyncio.create_task(chat_route.relay_workflow_events(_WS(), queue))
        await asyncio.sleep(0.05)  # several poll timeouts with nothing in the queue

        from app.core.workflow_tracker import WorkflowEvent

        await queue.put(WorkflowEvent(workflow_id="w", step="pipeline_start", status="started"))
        await queue.put(WorkflowEvent(workflow_id="w", step="pipeline_end", status="completed"))
        await asyncio.wait_for(relay, timeout=2)

        steps = [p.get("step") for p in sent]
        assert "pipeline_end" in steps, f"the relay died during the quiet period: {steps}"

    async def test_the_overall_deadline_still_ends_it(self, monkeypatch):
        """Continuing on a gap must not mean continuing forever — a run that never
        reaches `pipeline_end` has to release the relay."""
        from app.config import settings

        monkeypatch.setattr(settings, "ws_event_relay_poll_seconds", 0.01)
        monkeypatch.setattr(settings, "ws_event_relay_timeout_seconds", 0.05)

        class _WS:
            async def send_json(self, payload):
                pass

        await asyncio.wait_for(chat_route.relay_workflow_events(_WS(), asyncio.Queue()), timeout=2)


class TestConnectingTwiceDoesNotLeaveTwoEmptySessions:
    async def test_an_empty_session_for_the_same_triple_is_reused(self, db_session):
        """Bounded to one orphan per (project, connection, user) instead of one per
        connect. Lazy creation would bound it to zero and break `session_created`, which
        the client is sent an id in at connect time."""
        from app.services.chat_service import ChatService

        svc = ChatService()
        first = await svc.get_or_create_empty_session(
            db_session, "p1", user_id="u1", connection_id="c1"
        )
        second = await svc.get_or_create_empty_session(
            db_session, "p1", user_id="u1", connection_id="c1"
        )

        assert first.id == second.id

    async def test_a_session_with_messages_is_not_reused(self, db_session):
        """Reuse is for *empty* sessions. Handing a client somebody's conversation
        because it happens to share a triple would be a far worse bug than the orphan."""
        from app.models.chat_session import ChatMessage
        from app.services.chat_service import ChatService

        svc = ChatService()
        first = await svc.get_or_create_empty_session(
            db_session, "p1", user_id="u1", connection_id="c1"
        )
        db_session.add(ChatMessage(session_id=first.id, role="user", content="hello"))
        await db_session.commit()

        second = await svc.get_or_create_empty_session(
            db_session, "p1", user_id="u1", connection_id="c1"
        )

        assert second.id != first.id

    async def test_a_different_user_never_shares_a_session(self, db_session):
        from app.services.chat_service import ChatService

        svc = ChatService()
        mine = await svc.get_or_create_empty_session(
            db_session, "p1", user_id="u1", connection_id="c1"
        )
        theirs = await svc.get_or_create_empty_session(
            db_session, "p1", user_id="u2", connection_id="c1"
        )

        assert mine.id != theirs.id

    async def test_a_different_connection_gets_its_own_session(self, db_session):
        from app.services.chat_service import ChatService

        svc = ChatService()
        a = await svc.get_or_create_empty_session(
            db_session, "p1", user_id="u1", connection_id="c1"
        )
        b = await svc.get_or_create_empty_session(
            db_session, "p1", user_id="u1", connection_id="c2"
        )

        assert a.id != b.id

    async def test_the_websocket_route_uses_it(self):
        src = inspect.getsource(chat_route.chat_websocket)

        assert "get_or_create_empty_session" in src, (
            "the helper exists but the route still writes a row per connect"
        )


@pytest.fixture
async def db_session():
    """An in-memory session with the chat tables, independent of the integration suite."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()
