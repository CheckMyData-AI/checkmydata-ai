"""Integration tests for /api/auth endpoints."""

import uuid
from unittest.mock import patch

import pytest

from tests.integration.conftest import auth_headers, register_user


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@test.com"


FAKE_GOOGLE_PAYLOAD = {
    "sub": "google-uid-123456",
    "email": "testuser@example.com",
    "name": "Google User",
    "email_verified": True,
    "picture": "https://lh3.googleusercontent.com/a/test-photo",
}


@pytest.mark.asyncio
class TestAuth:
    async def test_register_and_login(self, client):
        email = _email()
        resp = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "secret123",
                "display_name": "Tester",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["token"]
        assert data["user"]["email"] == email
        assert data["user"]["display_name"] == "Tester"

        resp = await client.post(
            "/api/auth/login",
            json={
                "email": email,
                "password": "secret123",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["token"]

    async def test_register_normalizes_email(self, client):
        raw_email = f"  User-{uuid.uuid4().hex[:8]}@Test.COM  "
        normalized = raw_email.lower().strip()
        resp = await client.post(
            "/api/auth/register",
            json={"email": raw_email.strip(), "password": "secret123"},
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == normalized

        resp2 = await client.post(
            "/api/auth/login",
            json={"email": raw_email.strip().upper(), "password": "secret123"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["user"]["email"] == normalized

    async def test_duplicate_register(self, client):
        email = _email()
        await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "pass1234",
            },
        )
        resp = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "pass1234",
            },
        )
        assert resp.status_code == 409

    async def test_duplicate_register_case_insensitive(self, client):
        email = _email()
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "pass1234"},
        )
        resp = await client.post(
            "/api/auth/register",
            json={"email": email.upper(), "password": "pass1234"},
        )
        assert resp.status_code == 409

    async def test_login_wrong_password(self, client):
        email = _email()
        resp_reg = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "correct1",
            },
        )
        assert resp_reg.status_code == 200
        resp = await client.post(
            "/api/auth/login",
            json={
                "email": email,
                "password": "wrongone1",
            },
        )
        assert resp.status_code == 401

    async def test_login_nonexistent(self, client):
        resp = await client.post(
            "/api/auth/login",
            json={
                "email": _email(),
                "password": "anything",
            },
        )
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, client):
        resp = await client.get(
            "/api/projects",
            headers=auth_headers("not-a-real-jwt-token"),
        )
        assert resp.status_code == 401

    async def test_missing_auth_header_returns_401(self, client):
        resp = await client.get("/api/projects")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestGoogleAuth:
    async def test_google_login_creates_user(self, client):
        payload = {**FAKE_GOOGLE_PAYLOAD, "email": _email(), "sub": f"gid-{uuid.uuid4().hex[:8]}"}
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            return_value=payload,
        ):
            resp = await client.post("/api/auth/google", json={"credential": "fake-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["token"]
        assert data["user"]["email"] == payload["email"]

    async def test_google_login_returns_same_user_on_repeat(self, client):
        email = _email()
        gid = f"gid-{uuid.uuid4().hex[:8]}"
        payload = {**FAKE_GOOGLE_PAYLOAD, "email": email, "sub": gid}
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            return_value=payload,
        ):
            resp1 = await client.post("/api/auth/google", json={"credential": "fake"})
            resp2 = await client.post("/api/auth/google", json={"credential": "fake"})
        assert resp1.json()["user"]["id"] == resp2.json()["user"]["id"]

    async def test_google_login_invalid_token_returns_401(self, client):
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            side_effect=ValueError("Bad token"),
        ):
            resp = await client.post("/api/auth/google", json={"credential": "bad"})
        assert resp.status_code == 401

    async def test_google_login_links_existing_email_user(self, client):
        email = _email()
        reg = await register_user(client, email)
        original_uid = reg["user_id"]

        payload = {**FAKE_GOOGLE_PAYLOAD, "email": email, "sub": f"gid-{uuid.uuid4().hex[:8]}"}
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            return_value=payload,
        ):
            resp = await client.post("/api/auth/google", json={"credential": "fake"})
        assert resp.status_code == 200
        assert resp.json()["user"]["id"] == original_uid

    async def test_google_only_user_cannot_password_login(self, client):
        email = _email()
        payload = {**FAKE_GOOGLE_PAYLOAD, "email": email, "sub": f"gid-{uuid.uuid4().hex[:8]}"}
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            return_value=payload,
        ):
            await client.post("/api/auth/google", json={"credential": "fake"})

        resp = await client.post(
            "/api/auth/login",
            json={
                "email": email,
                "password": "anything",
            },
        )
        assert resp.status_code == 401

    async def test_google_nonce_mismatch_returns_401(self, client):
        email = _email()
        payload = {
            **FAKE_GOOGLE_PAYLOAD,
            "email": email,
            "sub": f"gid-{uuid.uuid4().hex[:8]}",
            "nonce": "server-nonce-abc",
        }
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            return_value=payload,
        ):
            resp = await client.post(
                "/api/auth/google",
                json={"credential": "fake", "nonce": "wrong-nonce"},
            )
        assert resp.status_code == 401

    async def test_google_nonce_match_succeeds(self, client):
        email = _email()
        nonce = f"nonce-{uuid.uuid4().hex[:8]}"
        payload = {
            **FAKE_GOOGLE_PAYLOAD,
            "email": email,
            "sub": f"gid-{uuid.uuid4().hex[:8]}",
            "nonce": nonce,
        }
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            return_value=payload,
        ):
            resp = await client.post(
                "/api/auth/google",
                json={"credential": "fake", "nonce": nonce},
            )
        assert resp.status_code == 200
        assert resp.json()["token"]

    async def test_google_login_returns_picture_url(self, client):
        email = _email()
        payload = {**FAKE_GOOGLE_PAYLOAD, "email": email, "sub": f"gid-{uuid.uuid4().hex[:8]}"}
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            return_value=payload,
        ):
            resp = await client.post("/api/auth/google", json={"credential": "fake"})
        assert resp.status_code == 200
        assert resp.json()["user"]["picture_url"] == payload["picture"]

    async def test_google_login_unverified_email_rejected(self, client):
        """verify_google_token rejects payloads where email_verified is False."""
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            side_effect=ValueError("Google account email is not verified"),
        ):
            resp = await client.post("/api/auth/google", json={"credential": "fake"})
        assert resp.status_code == 401

    async def test_google_csrf_body_without_cookie_succeeds(self, client):
        """Cross-origin: frontend sends g_csrf_token in body but cookie is absent."""
        email = _email()
        payload = {**FAKE_GOOGLE_PAYLOAD, "email": email, "sub": f"gid-{uuid.uuid4().hex[:8]}"}
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            return_value=payload,
        ):
            resp = await client.post(
                "/api/auth/google",
                json={"credential": "fake", "g_csrf_token": "some-token-from-body"},
            )
        assert resp.status_code == 200

    async def test_google_csrf_mismatch_returns_403(self, client):
        """Same-origin: both cookie and body present but values differ."""
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            return_value={**FAKE_GOOGLE_PAYLOAD, "email": _email(), "sub": f"gid-{uuid.uuid4().hex[:8]}"},
        ):
            resp = await client.post(
                "/api/auth/google",
                json={"credential": "fake", "g_csrf_token": "body-token"},
                cookies={"g_csrf_token": "different-cookie-token"},
            )
        assert resp.status_code == 403

    async def test_google_login_normalizes_email(self, client):
        email_raw = f"  User-{uuid.uuid4().hex[:8]}@EXAMPLE.COM  "
        email_normalized = email_raw.lower().strip()
        payload = {
            **FAKE_GOOGLE_PAYLOAD,
            "email": email_raw,
            "sub": f"gid-{uuid.uuid4().hex[:8]}",
        }
        with patch(
            "app.services.auth_service.AuthService.verify_google_token",
            return_value=payload,
        ):
            resp = await client.post("/api/auth/google", json={"credential": "fake"})
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == email_normalized


@pytest.mark.asyncio
class TestChangePassword:
    async def test_change_password_success(self, client):
        email = _email()
        reg = await register_user(client, email)
        headers = auth_headers(reg["token"])
        resp = await client.post(
            "/api/auth/change-password",
            json={"current_password": "testpass123", "new_password": "newpass1234"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        login_resp = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "newpass1234"},
        )
        assert login_resp.status_code == 200

    async def test_change_password_wrong_current(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        resp = await client.post(
            "/api/auth/change-password",
            json={"current_password": "wrongpassword", "new_password": "newpass1234"},
            headers=headers,
        )
        assert resp.status_code == 401

    async def test_change_password_too_short(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        resp = await client.post(
            "/api/auth/change-password",
            json={"current_password": "testpass123", "new_password": "short"},
            headers=headers,
        )
        assert resp.status_code == 422

    async def test_change_password_requires_auth(self, client):
        resp = await client.post(
            "/api/auth/change-password",
            json={"current_password": "old", "new_password": "newpass1234"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestRefreshToken:
    async def test_refresh_returns_new_token(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        resp = await client.post("/api/auth/refresh", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["token"]
        assert data["user"]["email"] == reg["email"]

    async def test_refresh_requires_auth(self, client):
        resp = await client.post("/api/auth/refresh")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestMe:
    async def test_me_returns_user(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        resp = await client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == reg["user_id"]
        assert data["email"] == reg["email"]

    async def test_me_requires_auth(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    async def test_me_with_invalid_token(self, client):
        resp = await client.get("/api/auth/me", headers=auth_headers("invalid-jwt"))
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestDeleteAccount:
    async def test_delete_account_success(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        resp = await client.delete("/api/auth/account", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        login_resp = await client.post(
            "/api/auth/login",
            json={"email": reg["email"], "password": "testpass123"},
        )
        assert login_resp.status_code == 401

    async def test_delete_account_requires_auth(self, client):
        resp = await client.delete("/api/auth/account")
        assert resp.status_code == 401
