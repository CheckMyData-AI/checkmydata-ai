"""Tests for the per-session processing lock (R5-5).

These document the exact leak the WS/HTTP/stream handlers must avoid: a lock
entered manually (``__aenter__``) but never exited keeps the session "busy"
(for up to the TTLCache window, ~1h), so every handler that manually enters the
lock MUST release it on every failure path.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.chat_service import SessionBusyError, session_processing_lock


def _sid() -> str:
    return f"sess-{uuid.uuid4().hex[:8]}"


async def test_context_manager_releases_on_exit():
    sid = _sid()
    async with session_processing_lock(sid):
        # While held, a concurrent acquire is rejected immediately.
        with pytest.raises(SessionBusyError):
            async with session_processing_lock(sid):
                pass
    # After the block, the session is free again.
    async with session_processing_lock(sid):
        pass


async def test_manual_enter_without_exit_wedges_session():
    """A manual __aenter__ that never reaches __aexit__ (the WS setup-failure
    leak) keeps the session busy until the lock is explicitly released."""
    sid = _sid()
    cm = session_processing_lock(sid)
    await cm.__aenter__()
    try:
        with pytest.raises(SessionBusyError):
            async with session_processing_lock(sid):
                pass
    finally:
        # Explicit release (what the handler's failure path must do) frees it.
        await cm.__aexit__(None, None, None)

    async with session_processing_lock(sid):
        pass  # acquirable again — no leak
