"""Security integration tests for RBAC enforcement and JWT edge cases.

Verifies that every protected endpoint enforces role-based access control
and that JWT validation handles edge cases properly.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from app.config import settings
from tests.integration.conftest import auth_headers, register_user


def _email() -> str:
    return f"sec-{uuid.uuid4().hex[:8]}@test.com"


async def _create_project(client, token: str) -> str:
    resp = await client.post(
        "/api/projects",
        json={"name": f"proj-{uuid.uuid4().hex[:6]}"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    return resp.json()["id"]


async def _create_connection(client, token: str, project_id: str) -> str:
    resp = await client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": f"conn-{uuid.uuid4().hex[:6]}",
            "db_type": "postgres",
            "db_host": "localhost",
            "db_port": 5432,
            "db_name": "test",
            "db_user": "user",
            "db_password": "pass",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    return resp.json()["id"]


async def _invite_user(client, owner_token: str, project_id: str, email: str, role: str) -> str:
    resp = await client.post(
        f"/api/invites/{project_id}/invites",
        json={"email": email, "role": role},
        headers=auth_headers(owner_token),
    )
    assert resp.status_code == 200
    return resp.json()["id"]


async def _setup_project_with_members(client):
    """Create a project with owner, editor, and viewer members."""
    owner = await register_user(client)
    editor_email = _email()
    viewer_email = _email()

    project_id = await _create_project(client, owner["token"])

    await _invite_user(client, owner["token"], project_id, editor_email, "editor")
    await _invite_user(client, owner["token"], project_id, viewer_email, "viewer")

    editor_reg = await register_user(client, editor_email)
    viewer_reg = await register_user(client, viewer_email)

    pending_e = await client.get("/api/invites/pending", headers=auth_headers(editor_reg["token"]))
    for inv in pending_e.json():
        await client.post(
            f"/api/invites/accept/{inv['id']}", headers=auth_headers(editor_reg["token"])
        )

    pending_v = await client.get("/api/invites/pending", headers=auth_headers(viewer_reg["token"]))
    for inv in pending_v.json():
        await client.post(
            f"/api/invites/accept/{inv['id']}", headers=auth_headers(viewer_reg["token"])
        )

    return {
        "project_id": project_id,
        "owner": owner,
        "editor": editor_reg,
        "viewer": viewer_reg,
    }


@pytest.mark.asyncio
class TestRBACProjectOperations:
    """Verify role enforcement on project modification endpoints."""

    async def test_viewer_cannot_update_project(self, client):
        ctx = await _setup_project_with_members(client)
        resp = await client.patch(
            f"/api/projects/{ctx['project_id']}",
            json={"name": "hacked"},
            headers=auth_headers(ctx["viewer"]["token"]),
        )
        assert resp.status_code == 403

    async def test_editor_cannot_delete_project(self, client):
        ctx = await _setup_project_with_members(client)
        resp = await client.delete(
            f"/api/projects/{ctx['project_id']}",
            headers=auth_headers(ctx["editor"]["token"]),
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_delete_project(self, client):
        ctx = await _setup_project_with_members(client)
        resp = await client.delete(
            f"/api/projects/{ctx['project_id']}",
            headers=auth_headers(ctx["viewer"]["token"]),
        )
        assert resp.status_code == 403

    async def test_non_member_cannot_access_project(self, client):
        owner = await register_user(client)
        project_id = await _create_project(client, owner["token"])
        outsider = await register_user(client)
        resp = await client.get(
            f"/api/connections/project/{project_id}",
            headers=auth_headers(outsider["token"]),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestRBACConnectionOperations:
    """Verify role enforcement on connection modification endpoints."""

    async def test_viewer_cannot_create_connection(self, client):
        ctx = await _setup_project_with_members(client)
        resp = await client.post(
            "/api/connections",
            json={
                "project_id": ctx["project_id"],
                "name": "evil-conn",
                "db_type": "postgres",
                "db_host": "evil.host",
                "db_port": 5432,
                "db_name": "stolen",
                "db_user": "x",
                "db_password": "x",
            },
            headers=auth_headers(ctx["viewer"]["token"]),
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_delete_connection(self, client):
        ctx = await _setup_project_with_members(client)
        conn_id = await _create_connection(client, ctx["owner"]["token"], ctx["project_id"])
        resp = await client.delete(
            f"/api/connections/{conn_id}",
            headers=auth_headers(ctx["viewer"]["token"]),
        )
        assert resp.status_code == 403

    async def test_editor_cannot_delete_connection(self, client):
        ctx = await _setup_project_with_members(client)
        conn_id = await _create_connection(client, ctx["owner"]["token"], ctx["project_id"])
        resp = await client.delete(
            f"/api/connections/{conn_id}",
            headers=auth_headers(ctx["editor"]["token"]),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestRBACRuleOperations:
    """Verify role enforcement on rule endpoints."""

    async def test_viewer_cannot_create_rule(self, client):
        ctx = await _setup_project_with_members(client)
        resp = await client.post(
            "/api/rules",
            json={
                "project_id": ctx["project_id"],
                "name": "evil-rule",
                "content": "DROP TABLE users",
            },
            headers=auth_headers(ctx["viewer"]["token"]),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestRBACInviteOperations:
    """Verify only owners can manage invites."""

    async def test_editor_cannot_invite(self, client):
        ctx = await _setup_project_with_members(client)
        resp = await client.post(
            f"/api/invites/{ctx['project_id']}/invites",
            json={"email": _email(), "role": "viewer"},
            headers=auth_headers(ctx["editor"]["token"]),
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_invite(self, client):
        ctx = await _setup_project_with_members(client)
        resp = await client.post(
            f"/api/invites/{ctx['project_id']}/invites",
            json={"email": _email(), "role": "viewer"},
            headers=auth_headers(ctx["viewer"]["token"]),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestJWTEdgeCases:
    """JWT validation edge cases."""

    async def test_expired_token_rejected(self, client):
        reg = await register_user(client)
        expired_payload = {
            "sub": reg["user_id"],
            "email": reg["email"],
            "iat": datetime.now(UTC) - timedelta(hours=48),
            "exp": datetime.now(UTC) - timedelta(hours=24),
        }
        expired_token = jwt.encode(
            expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
        resp = await client.get("/api/projects", headers=auth_headers(expired_token))
        assert resp.status_code == 401

    async def test_tampered_payload_rejected(self, client):
        reg = await register_user(client)
        token = reg["token"]
        parts = token.split(".")
        import base64

        payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
        tampered = payload_bytes.replace(b'"sub"', b'"SUB"')
        parts[1] = base64.urlsafe_b64encode(tampered).decode().rstrip("=")
        tampered_token = ".".join(parts)
        resp = await client.get("/api/projects", headers=auth_headers(tampered_token))
        assert resp.status_code == 401

    async def test_wrong_secret_rejected(self, client):
        reg = await register_user(client)
        payload = {
            "sub": reg["user_id"],
            "email": reg["email"],
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=24),
        }
        bad_token = jwt.encode(payload, "wrong-secret-key-totally-different", algorithm="HS256")
        resp = await client.get("/api/projects", headers=auth_headers(bad_token))
        assert resp.status_code == 401

    async def test_missing_sub_claim_rejected(self, client):
        payload = {
            "email": "test@test.com",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=24),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        resp = await client.get("/api/projects", headers=auth_headers(token))
        assert resp.status_code == 401

    async def test_nonexistent_user_id_rejected(self, client):
        payload = {
            "sub": str(uuid.uuid4()),
            "email": "ghost@test.com",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=24),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        resp = await client.get("/api/projects", headers=auth_headers(token))
        assert resp.status_code == 401

    async def test_bearer_prefix_required(self, client):
        reg = await register_user(client)
        resp = await client.get("/api/projects", headers={"Authorization": reg["token"]})
        assert resp.status_code == 401

    async def test_empty_bearer_token(self, client):
        resp = await client.get("/api/projects", headers={"Authorization": "Bearer "})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestEncryptionSecurity:
    """Verify secrets are never leaked in API responses."""

    async def test_ssh_key_not_in_response(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        resp = await client.post(
            "/api/ssh-keys",
            json={
                "name": "test-key",
                "private_key": (
                    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
                    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmU"
                    "AAAAEbm9uZQAAAAAAAAABAAAAMwAAAA"
                    "tzc2gtZWQyNTUxOQAAACDEdS36JZMt5"
                    "lOQ5oPLFTmGIQEHhXFz5lRx7J7Kjyq"
                    "FPAAAAJhG0W+YRtFvmAAAAAtzc2gtZW"
                    "QyNTUxOQAAACDEdS36JZMt5lOQ5oPL"
                    "FTmGIQEHhXFz5lRx7J7KjyqFPAAAAA"
                    "EBWEw+dCEYLsMSivVGoc7RIQ/0wSV0P"
                    "IU5YsDdPNr2FYcR1Lfolky3mU5Dmg8s"
                    "VOYYhAQeFcXPmVHHsnsqPKoU8AAAADH"
                    "Rlc3RAZXhhbXBsZS5jb20BAgMEBQ==\n"
                    "-----END OPENSSH PRIVATE KEY-----"
                ),
            },
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "private_key" not in data or data.get("private_key") is None
            resp_text = resp.text
            assert "BEGIN OPENSSH PRIVATE KEY" not in resp_text

    async def test_connection_password_not_in_response(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id = await _create_project(client, reg["token"])
        resp = await client.post(
            "/api/connections",
            json={
                "project_id": project_id,
                "name": "secret-conn",
                "db_type": "postgres",
                "db_host": "localhost",
                "db_port": 5432,
                "db_name": "test",
                "db_user": "user",
                "db_password": "SuperSecretPassword123!",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("db_password") != "SuperSecretPassword123!"
        assert "SuperSecretPassword123!" not in resp.text

    async def test_connection_list_hides_passwords(self, client):
        reg = await register_user(client)
        headers = auth_headers(reg["token"])
        project_id = await _create_project(client, reg["token"])
        await _create_connection(client, reg["token"], project_id)
        resp = await client.get(f"/api/connections/project/{project_id}", headers=headers)
        assert resp.status_code == 200
        for conn in resp.json():
            assert conn.get("db_password") != "pass"


@pytest.mark.asyncio
class TestUnauthenticatedAccess:
    """Verify all protected endpoints reject unauthenticated requests."""

    async def test_projects_require_auth(self, client):
        assert (await client.get("/api/projects")).status_code == 401
        assert (await client.post("/api/projects", json={"name": "x"})).status_code == 401

    async def test_connections_require_auth(self, client):
        assert (await client.post("/api/connections", json={})).status_code == 401

    async def test_ssh_keys_require_auth(self, client):
        assert (await client.get("/api/ssh-keys")).status_code == 401
        assert (await client.post("/api/ssh-keys", json={})).status_code == 401

    async def test_chat_requires_auth(self, client):
        assert (
            await client.post("/api/chat/sessions", json={"project_id": "x"})
        ).status_code == 401

    async def test_rules_require_auth(self, client):
        assert (await client.get("/api/rules", params={"project_id": "x"})).status_code == 401

    async def test_notes_require_auth(self, client):
        assert (await client.get("/api/notes", params={"project_id": "x"})).status_code == 401

    async def test_invites_require_auth(self, client):
        assert (await client.get("/api/invites/pending")).status_code == 401

    async def test_schedules_require_auth(self, client):
        assert (await client.get("/api/schedules", params={"project_id": "x"})).status_code == 401

    async def test_notifications_require_auth(self, client):
        assert (await client.get("/api/notifications")).status_code == 401

    async def test_backup_require_auth(self, client):
        assert (await client.post("/api/backup/trigger")).status_code == 401
        assert (await client.get("/api/backup/list")).status_code == 401

    async def test_health_does_not_require_auth(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
