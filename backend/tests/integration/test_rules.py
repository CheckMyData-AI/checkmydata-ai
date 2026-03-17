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
