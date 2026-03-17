"""Integration tests for /api/rules endpoints."""

import pytest

from tests.integration.conftest import auth_headers, register_user


@pytest.mark.asyncio
class TestRulesCrud:
    async def test_create_and_list(self, auth_client):
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

    async def test_update_rule(self, auth_client):
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

    async def test_delete_rule(self, auth_client):
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

    async def test_is_default_field_in_response(self, client):
        """All rule responses should include the is_default field."""
        user = await register_user(client)

        resp = await client.post(
            "/api/rules",
            json={"name": "Manual Rule", "content": "manual content"},
            headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 200
        assert "is_default" in resp.json()
        assert resp.json()["is_default"] is False
