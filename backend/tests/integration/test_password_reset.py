"""Integration tests for the forgot/reset-password flow (SCN-013)."""

import uuid

import pytest

import app.api.routes.auth as auth_routes
from tests.integration.conftest import register_user


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@test.com"


@pytest.mark.asyncio
class TestForgotPassword:
    async def test_generic_ok_for_existing_email(self, client, monkeypatch):
        """A real account gets a reset email but the response stays generic."""
        captured: dict = {}

        async def _capture(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(auth_routes._email_svc, "send_password_reset_email", _capture)

        email = _email()
        await register_user(client, email)

        resp = await client.post("/api/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert captured.get("token"), "a reset token should have been emailed"
        assert captured.get("email") == email

    async def test_generic_ok_for_nonexistent_email_no_leak(self, client, monkeypatch):
        """A missing account returns the SAME generic ok and sends no email
        (no account-existence leak)."""
        captured: dict = {}

        async def _capture(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(auth_routes._email_svc, "send_password_reset_email", _capture)

        resp = await client.post("/api/auth/forgot-password", json={"email": _email()})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert captured == {}, "no email should be sent for an unknown address"

    async def test_generic_ok_for_google_only_account(self, client, db_session, monkeypatch):
        """Google-only (passwordless) accounts get the generic ok and no email."""
        from sqlalchemy import update

        from app.models.user import User

        captured: dict = {}

        async def _capture(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(auth_routes._email_svc, "send_password_reset_email", _capture)

        email = _email()
        reg = await register_user(client, email)
        # Turn the account passwordless (as if provisioned via Google).
        await db_session.execute(
            update(User)
            .where(User.id == reg["user_id"])
            .values(password_hash=None, auth_provider="google")
        )
        await db_session.commit()

        resp = await client.post("/api/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert captured == {}, "no reset email for a passwordless account"

    async def test_invalid_email_rejected(self, client):
        resp = await client.post("/api/auth/forgot-password", json={"email": "not-an-email"})
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestResetPassword:
    async def _request_token(self, client, monkeypatch, email: str) -> str:
        captured: dict = {}

        async def _capture(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(auth_routes._email_svc, "send_password_reset_email", _capture)
        resp = await client.post("/api/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200
        assert captured.get("token")
        return captured["token"]

    async def test_valid_reset_lets_user_login_with_new_password(self, client, monkeypatch):
        email = _email()
        await register_user(client, email)  # registers with password "testpass123"
        token = await self._request_token(client, monkeypatch, email)

        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "brandnew999"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Old password no longer works; new one does.
        old = await client.post("/api/auth/login", json={"email": email, "password": "testpass123"})
        assert old.status_code == 401
        new = await client.post("/api/auth/login", json={"email": email, "password": "brandnew999"})
        assert new.status_code == 200
        assert new.json()["user"]["email"] == email

    async def test_token_is_single_use(self, client, monkeypatch):
        email = _email()
        await register_user(client, email)
        token = await self._request_token(client, monkeypatch, email)

        first = await client.post(
            "/api/auth/reset-password", json={"token": token, "new_password": "firstnew99"}
        )
        assert first.status_code == 200
        second = await client.post(
            "/api/auth/reset-password", json={"token": token, "new_password": "secondnew99"}
        )
        assert second.status_code == 400

    async def test_invalid_token_returns_400(self, client):
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": "not-a-real-token", "new_password": "brandnew999"},
        )
        assert resp.status_code == 400

    async def test_expired_token_returns_400(self, client, db_session, monkeypatch):
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import update

        from app.models.user import User

        email = _email()
        await register_user(client, email)
        token = await self._request_token(client, monkeypatch, email)

        # The route shares this exact db_session (conftest overrides get_db), so we can
        # push the expiry into the past and prove the API rejects the stale token.
        await db_session.execute(
            update(User)
            .where(User.email == email)
            .values(password_reset_expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db_session.commit()

        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "brandnew999"},
        )
        assert resp.status_code == 400

    async def test_short_password_rejected(self, client, monkeypatch):
        email = _email()
        await register_user(client, email)
        token = await self._request_token(client, monkeypatch, email)
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "short"},
        )
        assert resp.status_code == 422
