"""Integration tests for /api/rules endpoints."""

import pytest

from app.config import settings
from tests.integration.conftest import auth_headers, register_user


async def _make_auth_client_admin(auth_client, monkeypatch) -> str:
    """Promote the ``auth_client`` fixture user to admin and return its email.

    Global rules (``project_id is None``) require admin privileges
    (F-RULE-01), so CRUD tests that operate on global rules must run as an
    admin user.
    """
    resp = await auth_client.get("/api/auth/me")
    email = resp.json()["email"]
    monkeypatch.setattr(settings, "admin_emails", [email])
    return email


@pytest.mark.asyncio
class TestRulesCrud:
    async def test_create_and_list(self, auth_client, monkeypatch):
        await _make_auth_client_admin(auth_client, monkeypatch)
        resp = await auth_client.post(
            "/api/rules",
            json={
                "name": "Test Rule",
                "content": "Always use UTC timestamps",
            },
        )
        assert resp.status_code == 200
        rule = resp.json()
        assert rule["name"] == "Test Rule"
        assert rule["is_default"] is False
        rule_id = rule["id"]

        resp = await auth_client.get("/api/rules")
        assert resp.status_code == 200
        names = [r["name"] for r in resp.json()]
        assert "Test Rule" in names

        resp = await auth_client.get(f"/api/rules/{rule_id}")
        assert resp.status_code == 200
        assert resp.json()["content"] == "Always use UTC timestamps"

    async def test_update_rule(self, auth_client, monkeypatch):
        await _make_auth_client_admin(auth_client, monkeypatch)
        resp = await auth_client.post(
            "/api/rules",
            json={
                "name": "Updatable",
                "content": "v1",
            },
        )
        rid = resp.json()["id"]

        resp = await auth_client.patch(f"/api/rules/{rid}", json={"content": "v2"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "v2"

    async def test_delete_rule(self, auth_client, monkeypatch):
        await _make_auth_client_admin(auth_client, monkeypatch)
        resp = await auth_client.post(
            "/api/rules",
            json={
                "name": "Deletable",
                "content": "temp",
            },
        )
        rid = resp.json()["id"]

        resp = await auth_client.delete(f"/api/rules/{rid}")
        assert resp.status_code == 200

        resp = await auth_client.get(f"/api/rules/{rid}")
        assert resp.status_code == 404

    async def test_get_not_found(self, auth_client):
        resp = await auth_client.get("/api/rules/nonexistent")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestRulesAccessControl:
    async def test_viewer_can_list_but_not_create_project_rule(self, client):
        owner = await register_user(client)
        viewer = await register_user(client)
        resp = await client.post(
            "/api/projects",
            json={"name": "Rules RBAC"},
            headers=auth_headers(owner["token"]),
        )
        pid = resp.json()["id"]

        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": viewer["email"], "role": "viewer"},
            headers=auth_headers(owner["token"]),
        )
        await client.post(
            f"/api/invites/accept/{resp.json()['id']}",
            headers=auth_headers(viewer["token"]),
        )

        resp = await client.post(
            "/api/rules",
            json={"project_id": pid, "name": "Owner Rule", "content": "content"},
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200
        rule_id = resp.json()["id"]

        resp = await client.get(
            f"/api/rules?project_id={pid}",
            headers=auth_headers(viewer["token"]),
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

        resp = await client.post(
            "/api/rules",
            json={"project_id": pid, "name": "Blocked", "content": "no"},
            headers=auth_headers(viewer["token"]),
        )
        assert resp.status_code == 403

        resp = await client.delete(
            f"/api/rules/{rule_id}",
            headers=auth_headers(viewer["token"]),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestDefaultRuleCreation:
    async def test_project_creation_creates_default_rule(self, client):
        """Creating a project should auto-create a default business metrics rule."""
        user = await register_user(client)
        resp = await client.post(
            "/api/projects",
            json={"name": "Default Rule Test"},
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 200
        pid = resp.json()["id"]

        resp = await client.get(
            f"/api/rules?project_id={pid}",
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 200
        rules = resp.json()
        default_rules = [r for r in rules if r["is_default"] is True]
        assert len(default_rules) == 1
        assert default_rules[0]["name"] == "Business Metrics & Guidelines"
        assert "Revenue" in default_rules[0]["content"]
        assert default_rules[0]["project_id"] == pid

    async def test_default_rule_is_editable(self, client):
        """Users should be able to edit the default rule content."""
        user = await register_user(client)
        resp = await client.post(
            "/api/projects",
            json={"name": "Editable Default"},
            headers=auth_headers(user["token"]),
        )
        pid = resp.json()["id"]

        resp = await client.get(
            f"/api/rules?project_id={pid}",
            headers=auth_headers(user["token"]),
        )
        default_rule = [r for r in resp.json() if r["is_default"]][0]

        resp = await client.patch(
            f"/api/rules/{default_rule['id']}",
            json={"content": "Custom metrics for my project"},
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "Custom metrics for my project"
        assert resp.json()["is_default"] is True

    async def test_default_rule_is_deletable(self, client):
        """Users should be able to delete the default rule."""
        user = await register_user(client)
        resp = await client.post(
            "/api/projects",
            json={"name": "Deletable Default"},
            headers=auth_headers(user["token"]),
        )
        pid = resp.json()["id"]

        resp = await client.get(
            f"/api/rules?project_id={pid}",
            headers=auth_headers(user["token"]),
        )
        default_rule = [r for r in resp.json() if r["is_default"]][0]

        resp = await client.delete(
            f"/api/rules/{default_rule['id']}",
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 200

        resp = await client.get(
            f"/api/rules?project_id={pid}",
            headers=auth_headers(user["token"]),
        )
        default_rules = [r for r in resp.json() if r.get("is_default")]
        assert len(default_rules) == 0

    async def test_is_default_field_in_response(self, client, monkeypatch):
        """All rule responses should include the is_default field."""
        user = await register_user(client)
        monkeypatch.setattr(settings, "admin_emails", [user["email"]])

        resp = await client.post(
            "/api/rules",
            json={"name": "Manual Rule", "content": "manual content"},
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 200
        assert "is_default" in resp.json()
        assert resp.json()["is_default"] is False


@pytest.mark.asyncio
class TestGlobalRuleAdminOnly:
    """F-RULE-01: global-rule create/update/delete require admin privileges."""

    async def test_non_admin_cannot_create_global_rule(self, client):
        user = await register_user(client)
        resp = await client.post(
            "/api/rules",
            json={"name": "Global", "content": "applies everywhere"},
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 403
        assert "global" in resp.json()["detail"].lower()

    async def test_non_admin_cannot_update_global_rule(self, client, monkeypatch):
        # An admin creates the global rule first.
        admin = await register_user(client)
        monkeypatch.setattr(settings, "admin_emails", [admin["email"]])
        resp = await client.post(
            "/api/rules",
            json={"name": "Global", "content": "v1"},
            headers=auth_headers(admin["token"]),
        )
        assert resp.status_code == 200
        rid = resp.json()["id"]

        # A different, non-admin user cannot update it.
        non_admin = await register_user(client)
        monkeypatch.setattr(settings, "admin_emails", [admin["email"]])
        resp = await client.patch(
            f"/api/rules/{rid}",
            json={"content": "hacked"},
            headers=auth_headers(non_admin["token"]),
        )
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_global_rule(self, client, monkeypatch):
        admin = await register_user(client)
        monkeypatch.setattr(settings, "admin_emails", [admin["email"]])
        resp = await client.post(
            "/api/rules",
            json={"name": "Global", "content": "v1"},
            headers=auth_headers(admin["token"]),
        )
        assert resp.status_code == 200
        rid = resp.json()["id"]

        non_admin = await register_user(client)
        monkeypatch.setattr(settings, "admin_emails", [admin["email"]])
        resp = await client.delete(
            f"/api/rules/{rid}",
            headers=auth_headers(non_admin["token"]),
        )
        assert resp.status_code == 403

    async def test_admin_can_create_update_delete_global_rule(self, client, monkeypatch):
        admin = await register_user(client)
        monkeypatch.setattr(settings, "admin_emails", [admin["email"]])

        resp = await client.post(
            "/api/rules",
            json={"name": "Global", "content": "v1"},
            headers=auth_headers(admin["token"]),
        )
        assert resp.status_code == 200
        rid = resp.json()["id"]
        assert resp.json()["project_id"] is None

        resp = await client.patch(
            f"/api/rules/{rid}",
            json={"content": "v2"},
            headers=auth_headers(admin["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "v2"

        resp = await client.delete(
            f"/api/rules/{rid}",
            headers=auth_headers(admin["token"]),
        )
        assert resp.status_code == 200

    async def test_non_admin_editor_can_create_project_rule(self, client, db_session):
        """Project-scoped create by a project editor (owner) still works for non-admins."""
        owner = await register_user(client, db_session=db_session)
        # Ensure this user is NOT an admin (default empty admin_emails).
        assert not settings.is_admin_email(owner["email"])

        resp = await client.post(
            "/api/projects",
            json={"name": "Scoped Rules"},
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200
        pid = resp.json()["id"]

        resp = await client.post(
            "/api/rules",
            json={"project_id": pid, "name": "Project Rule", "content": "scoped"},
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["project_id"] == pid
