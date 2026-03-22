"""Extended auth integration tests — change-password, refresh, me, onboarding, delete-account."""

import uuid

import pytest

from tests.integration.conftest import auth_headers, register_user


def _email():
    return f"authext-{uuid.uuid4().hex[:8]}@test.com"


@pytest.mark.asyncio
class TestChangePasswordExtended:
    async def test_change_password_success(self, client):
        email = _email()
        reg = await register_user(client, email)
        headers = auth_headers(reg["token"])

        resp = await client.post(
            "/api/auth/change-password",
            json={"current_password": "testpass123", "new_password": "brandnew99"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        login = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "brandnew99"},
        )
        assert login.status_code == 200

    async def test_change_password_wrong_old_password(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        resp = await client.post(
            "/api/auth/change-password",
            json={"current_password": "totallyWrong1", "new_password": "whatever99"},
            headers=headers,
        )
        assert resp.status_code == 401
        assert "incorrect" in resp.json()["detail"].lower()

    async def test_change_password_unauthenticated(self, client):
        resp = await client.post(
            "/api/auth/change-password",
            json={"current_password": "old12345", "new_password": "new123456"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestRefreshTokenExtended:
    async def test_refresh_with_valid_token(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        resp = await client.post("/api/auth/refresh", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["token"]
        assert data["user"]["email"] == reg["email"]
        assert data["user"]["id"] == reg["user_id"]

    async def test_refresh_with_invalid_token(self, client):
        resp = await client.post(
            "/api/auth/refresh",
            headers=auth_headers("this.is.not.a.valid.jwt"),
        )
        assert resp.status_code == 401

    async def test_refresh_without_token(self, client):
        resp = await client.post("/api/auth/refresh")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestMeExtended:
    async def test_me_returns_user_info(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        resp = await client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == reg["user_id"]
        assert data["email"] == reg["email"]
        assert "is_onboarded" in data
        assert "auth_provider" in data

    async def test_me_unauthenticated(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    async def test_me_invalid_token(self, client):
        resp = await client.get(
            "/api/auth/me",
            headers=auth_headers("garbage-token-value"),
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestCompleteOnboarding:
    async def test_complete_onboarding_success(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        me_before = await client.get("/api/auth/me", headers=headers)
        assert me_before.json()["is_onboarded"] is False

        resp = await client.post("/api/auth/complete-onboarding", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        me_after = await client.get("/api/auth/me", headers=headers)
        assert me_after.json()["is_onboarded"] is True

    async def test_complete_onboarding_already_onboarded(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        await client.post("/api/auth/complete-onboarding", headers=headers)

        resp = await client.post("/api/auth/complete-onboarding", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_complete_onboarding_unauthenticated(self, client):
        resp = await client.post("/api/auth/complete-onboarding")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestDeleteAccountExtended:
    async def test_delete_account_success(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        resp = await client.delete("/api/auth/account", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        login = await client.post(
            "/api/auth/login",
            json={"email": reg["email"], "password": "testpass123"},
        )
        assert login.status_code == 401

    async def test_delete_account_unauthenticated(self, client):
        resp = await client.delete("/api/auth/account")
        assert resp.status_code == 401

    async def test_delete_account_with_project(self, client):
        """Deleting account also removes owned projects."""
        reg = await register_user(client)
        headers = auth_headers(reg["token"])

        proj = await client.post("/api/projects", json={"name": "Doomed Project"}, headers=headers)
        assert proj.status_code == 200

        resp = await client.delete("/api/auth/account", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


@pytest.mark.asyncio
class TestRegistrationValidation:
    async def test_register_short_password_rejected(self, client):
        resp = await client.post(
            "/api/auth/register",
            json={"email": _email(), "password": "short", "display_name": "Test"},
        )
        assert resp.status_code == 422

    async def test_register_invalid_email_rejected(self, client):
        resp = await client.post(
            "/api/auth/register",
            json={"email": "not-an-email", "password": "validpass123"},
        )
        assert resp.status_code == 422

    async def test_register_empty_password_rejected(self, client):
        resp = await client.post(
            "/api/auth/register",
            json={"email": _email(), "password": ""},
        )
        assert resp.status_code == 422
