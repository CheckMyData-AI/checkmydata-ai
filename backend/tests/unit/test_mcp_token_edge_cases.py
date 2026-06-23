"""End-to-end edge-case tests for per-user MCP tokens.

These tests exercise the full ``McpKeyService`` against a real (in-memory)
SQLite database so we catch SQL/ORM bugs, expiry boundary behavior, and the
log signal each path emits — things a pure-mock test can't reach.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.mcp_api_key import McpApiKey  # noqa: F401 — register the mapper
from app.models.user import User
from app.services.mcp_key_service import (
    TOKEN_PREFIX,
    IssuedKey,
    McpKeyService,
    _hash_token,
)


@pytest.fixture
async def db_session() -> AsyncSession:
    """Per-test in-memory SQLite session that drops the schema after use."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    session = sm()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


async def _seed_user(session: AsyncSession, user_id: str = "user-1") -> User:
    user = User(
        id=user_id,
        email=f"{user_id}@test.local",
        display_name=user_id,
        is_active=True,
        password_hash=None,
        auth_provider="local",
    )
    session.add(user)
    await session.commit()
    return user


class TestRealDbBehavior:
    @pytest.mark.asyncio
    async def test_issue_persists_hash_not_plaintext(self, db_session):
        await _seed_user(db_session)
        svc = McpKeyService()
        issued: IssuedKey = await svc.issue(db_session, user_id="user-1", name="laptop")

        # Re-read straight from the DB and confirm the secret is never persisted.
        from sqlalchemy import select

        row = (
            await db_session.execute(select(McpApiKey).where(McpApiKey.id == issued.record.id))
        ).scalar_one()
        assert row.token_hash == _hash_token(issued.plaintext)
        assert row.token_hash != issued.plaintext
        # The stored prefix must NEVER contain the high-entropy tail.
        assert row.token_prefix == issued.plaintext[:12]
        assert len(row.token_prefix) == 12

    @pytest.mark.asyncio
    async def test_lookup_roundtrip_returns_live_record(self, db_session):
        await _seed_user(db_session)
        svc = McpKeyService()
        issued = await svc.issue(db_session, user_id="user-1", name="laptop")

        found = await svc.lookup_by_token(db_session, issued.plaintext)
        assert found is not None
        assert found.id == issued.record.id
        assert found.last_used_at is not None

    @pytest.mark.asyncio
    async def test_expired_token_is_rejected_at_boundary(self, db_session):
        """A token whose ``expires_at`` is in the past must not resolve."""
        await _seed_user(db_session)
        svc = McpKeyService()
        issued = await svc.issue(db_session, user_id="user-1", name="short")
        # Force expiry in the past — simulates clock advancing past expires_at.
        issued.record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()

        found = await svc.lookup_by_token(db_session, issued.plaintext)
        assert found is None

    @pytest.mark.asyncio
    async def test_lookup_valid_expiring_token_from_cold_session(self):
        """Regression: on SQLite a ``DateTime(timezone=True)`` column reads
        back *naive* in a fresh session (cold identity map). ``lookup_by_token``
        compared it against an aware ``datetime.now(UTC)``, raising
        ``TypeError`` and breaking auth for every valid *expiring* token after
        a process restart. A valid future-dated token must resolve, not crash.
        """
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        svc = McpKeyService()
        try:
            async with sm() as s1:
                await _seed_user(s1)
                issued = await svc.issue(s1, user_id="user-1", name="laptop", expires_in_days=30)
                plaintext = issued.plaintext
            # Fresh session ⇒ cold identity map ⇒ naive read-back from SQLite.
            async with sm() as s2:
                found = await svc.lookup_by_token(s2, plaintext)
            assert found is not None
            assert found.expires_at is not None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_lookup_expired_token_from_cold_session_returns_none(self):
        """The same naive read-back must still reject a genuinely expired token
        (return ``None``) rather than raising."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        svc = McpKeyService()
        try:
            async with sm() as s1:
                await _seed_user(s1)
                issued = await svc.issue(s1, user_id="user-1", name="x")
                issued.record.expires_at = datetime.now(UTC) - timedelta(days=1)
                await s1.commit()
                plaintext = issued.plaintext
            async with sm() as s2:
                found = await svc.lookup_by_token(s2, plaintext)
            assert found is None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_revoked_token_is_rejected_even_if_not_expired(self, db_session):
        await _seed_user(db_session)
        svc = McpKeyService()
        issued = await svc.issue(db_session, user_id="user-1", name="rev")
        ok = await svc.revoke(db_session, issued.record.id, "user-1")
        assert ok is True

        found = await svc.lookup_by_token(db_session, issued.plaintext)
        assert found is None

    @pytest.mark.asyncio
    async def test_revoke_is_idempotent(self, db_session):
        """Revoking twice must return False the second time, not crash."""
        await _seed_user(db_session)
        svc = McpKeyService()
        issued = await svc.issue(db_session, user_id="user-1", name="x")
        assert await svc.revoke(db_session, issued.record.id, "user-1") is True
        assert await svc.revoke(db_session, issued.record.id, "user-1") is False

    @pytest.mark.asyncio
    async def test_user_a_cannot_revoke_user_b_token(self, db_session):
        await _seed_user(db_session, "alice")
        await _seed_user(db_session, "mallory")
        svc = McpKeyService()
        alice_key = await svc.issue(db_session, user_id="alice", name="laptop")
        ok = await svc.revoke(db_session, alice_key.record.id, "mallory")
        assert ok is False
        # And alice's token still works after the failed cross-tenant revoke.
        found = await svc.lookup_by_token(db_session, alice_key.plaintext)
        assert found is not None

    @pytest.mark.asyncio
    async def test_list_for_user_scopes_to_owner(self, db_session):
        await _seed_user(db_session, "alice")
        await _seed_user(db_session, "bob")
        svc = McpKeyService()
        await svc.issue(db_session, user_id="alice", name="a1")
        await svc.issue(db_session, user_id="alice", name="a2")
        await svc.issue(db_session, user_id="bob", name="b1")

        alice_keys = await svc.list_for_user(db_session, "alice")
        bob_keys = await svc.list_for_user(db_session, "bob")
        assert {k.name for k in alice_keys} == {"a1", "a2"}
        assert {k.name for k in bob_keys} == {"b1"}
        # Default ordering newest-first so the UI can show recent tokens up top.
        assert alice_keys[0].created_at >= alice_keys[-1].created_at

    @pytest.mark.asyncio
    async def test_lookup_wrong_prefix_does_not_touch_db(self, db_session, caplog):
        svc = McpKeyService()
        # No prefix → early return; never executes a query.
        assert await svc.lookup_by_token(db_session, "not-a-token") is None
        assert await svc.lookup_by_token(db_session, "") is None
        assert await svc.lookup_by_token(db_session, "Bearer abc") is None

    @pytest.mark.asyncio
    async def test_two_tokens_have_distinct_secrets_and_hashes(self, db_session):
        """Catches any RNG misuse — collisions would break unique constraint."""
        await _seed_user(db_session)
        svc = McpKeyService()
        a = await svc.issue(db_session, user_id="user-1", name="a")
        b = await svc.issue(db_session, user_id="user-1", name="b")
        assert a.plaintext != b.plaintext
        assert a.record.token_hash != b.record.token_hash


class TestLoggingSignals:
    """The user asked for explicit success/failure log signals for debugging.

    These tests pin the messages so a future refactor that drops the signal
    is caught immediately."""

    @pytest.mark.asyncio
    async def test_issue_logs_success(self, db_session, caplog):
        await _seed_user(db_session)
        svc = McpKeyService()
        with caplog.at_level(logging.INFO, logger="app.services.mcp_key_service"):
            await svc.issue(db_session, user_id="user-1", name="logged")
        assert any("MCP key issued for user user-1" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_revoke_logs_success(self, db_session, caplog):
        await _seed_user(db_session)
        svc = McpKeyService()
        issued = await svc.issue(db_session, user_id="user-1", name="rev")
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="app.services.mcp_key_service"):
            await svc.revoke(db_session, issued.record.id, "user-1")
        assert any("MCP key revoked" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_expired_lookup_logs_warning(self, db_session, caplog):
        await _seed_user(db_session)
        svc = McpKeyService()
        issued = await svc.issue(db_session, user_id="user-1", name="x")
        issued.record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="app.services.mcp_key_service"):
            await svc.lookup_by_token(db_session, issued.plaintext)
        assert any("expired at" in r.message for r in caplog.records)


class TestAuthIntegrationLogging:
    """The MCP auth path emits its own log signals — independent from the
    key service — so an ops engineer can grep `MCP auth:` to debug rejected
    clients."""

    @pytest.mark.asyncio
    async def test_personal_token_success_logged(self, db_session, caplog, monkeypatch):
        await _seed_user(db_session, "u-success")
        svc = McpKeyService()
        issued = await svc.issue(db_session, user_id="u-success", name="ok")

        # Patch the auth module's session factory to use our test session so
        # the lookup goes through the same backing DB the test seeded.
        from app.mcp_server import auth as auth_mod

        class _Ctx:  # noqa: N801
            async def __aenter__(self):  # noqa: N805
                return db_session

            async def __aexit__(self, *_):  # noqa: N805
                return None

        monkeypatch.setattr(auth_mod, "async_session_factory", lambda: _Ctx())

        with caplog.at_level(logging.INFO, logger="app.mcp_server.auth"):
            resolved = await auth_mod.authenticate(api_key=issued.plaintext)
        assert resolved["user_id"] == "u-success"
        assert any("resolved to user u-success" in r.message for r in caplog.records)
        # The full secret must NEVER appear in the log line.
        for record in caplog.records:
            assert issued.plaintext not in record.getMessage()

    @pytest.mark.asyncio
    async def test_unknown_personal_token_logs_warning_and_raises(
        self, db_session, caplog, monkeypatch
    ):
        from app.mcp_server import auth as auth_mod

        class _Ctx:  # noqa: N801
            async def __aenter__(self):  # noqa: N805
                return db_session

            async def __aexit__(self, *_):  # noqa: N805
                return None

        monkeypatch.setattr(auth_mod, "async_session_factory", lambda: _Ctx())

        with caplog.at_level(logging.WARNING, logger="app.mcp_server.auth"):
            with pytest.raises(auth_mod.MCPAuthError, match="invalid|revoked|expired"):
                await auth_mod.authenticate(api_key=TOKEN_PREFIX + "definitely-not-real")
        assert any("personal token lookup failed" in r.message for r in caplog.records)


class TestWithPrincipalLogging:
    @pytest.mark.asyncio
    async def test_tool_wrapper_logs_start_and_finish(self, caplog, monkeypatch):
        from app.mcp_server import server as srv

        async def fake_authenticate(*a, **kw):
            return {"user_id": "test-user", "email": ""}

        monkeypatch.setattr(srv.auth, "authenticate", fake_authenticate)

        async def fake_tool(_principal):
            return '{"ok": true}'

        with caplog.at_level(logging.INFO, logger="app.mcp_server.server"):
            result = await srv._with_principal(fake_tool)
        assert result == '{"ok": true}'
        starts = [r for r in caplog.records if "starting" in r.message]
        oks = [r for r in caplog.records if " ok " in r.message]
        assert starts and oks

    @pytest.mark.asyncio
    async def test_tool_wrapper_logs_and_swallows_crash(self, caplog, monkeypatch):
        from mcp.server.fastmcp.exceptions import ToolError

        from app.mcp_server import server as srv

        async def fake_authenticate(*a, **kw):
            return {"user_id": "test-user", "email": ""}

        monkeypatch.setattr(srv.auth, "authenticate", fake_authenticate)

        async def crashing_tool(_principal):
            raise RuntimeError("boom")

        with caplog.at_level(logging.ERROR, logger="app.mcp_server.server"):
            with pytest.raises(ToolError, match="Internal tool error"):
                await srv._with_principal(crashing_tool)

        assert any("crashed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_tool_wrapper_logs_auth_failure(self, caplog, monkeypatch):
        from mcp.server.fastmcp.exceptions import ToolError

        from app.mcp_server import server as srv

        async def fake_authenticate(*a, **kw):
            raise srv.auth.MCPAuthError("nope")

        monkeypatch.setattr(srv.auth, "authenticate", fake_authenticate)

        async def never_runs(_principal):
            raise AssertionError("must not be called when auth fails")

        with caplog.at_level(logging.WARNING, logger="app.mcp_server.server"):
            with pytest.raises(ToolError, match="nope"):
                await srv._with_principal(never_runs)

        assert any("rejected" in r.message for r in caplog.records)
