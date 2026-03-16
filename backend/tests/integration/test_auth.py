"""Integration tests for /api/auth endpoints."""

import uuid
from unittest.mock import patch

import pytest

from tests.integration.conftest import auth_headers, register_user


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@test.com"


FAKE_GOOGLE_PAYLOAD = {
    "sub": "google-uid-123456",
    "email": "googleuser@gmail.com",
    "name": "Google User",
    "email_verified": True,
}


@pytest.mark.asyncio
class TestAuth:
    async def test_register_and_login(self, client):
        email = _email()
        resp = await client.post("/api/auth/register", json={
            "email": email,
            "password": "secret123",
            "display_name": "Tester",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["token"]
        assert data["user"]["email"] == email
        assert data["user"]["display_name"] == "Tester"

        resp = await client.post("/api/auth/login", json={
            "email": email,
            "password": "secret123",
        })
        assert resp.status_code == 200
        assert resp.json()["token"]

    async def test_duplicate_register(self, client):
        email = _email()
        await client.post("/api/auth/register", json={
            "email": email,
            "password": "pass1234",
        })
        resp = await client.post("/api/auth/register", json={
            "email": email,
            "password": "pass1234",
        })
        assert resp.status_code == 409

    async def test_login_wrong_password(self, client):
        email = _email()
        await client.post("/api/auth/register", json={
            "email": email,
            "password": "correct",
        })
        resp = await client.post("/api/auth/login", json={
            "email": email,
            "password": "incorrect",
        })
        assert resp.status_code == 401

    async def test_login_nonexistent(self, client):
        resp = await client.post("/api/auth/login", json={
            "email": _email(),
            "password": "anything",
        })
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

        resp = await client.post("/api/auth/login", json={
            "email": email,
            "password": "anything",
        })
        assert resp.status_code == 401
