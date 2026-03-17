"""Integration tests for /api/projects endpoints."""

import pytest

from tests.integration.conftest import auth_headers, register_user


@pytest.mark.asyncio
class TestProjectCrud:
    async def test_create_and_list(self, auth_client):
        resp = await auth_client.post("/api/projects", json={"name": "Test Project"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Project"
        assert data.get("owner_id") is not None
        project_id = data["id"]

        resp = await auth_client.get("/api/projects")
        assert resp.status_code == 200
        names = [p["name"] for p in resp.json()]
        assert "Test Project" in names

        resp = await auth_client.get(f"/api/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == project_id

    async def test_create_sets_owner_membership(self, auth_client):
        resp = await auth_client.post("/api/projects", json={"name": "Owner Proj"})
        data = resp.json()
        assert data.get("user_role") == "owner"

    async def test_update_project(self, auth_client):
        resp = await auth_client.post("/api/projects", json={"name": "Original"})
        pid = resp.json()["id"]

        resp = await auth_client.patch(f"/api/projects/{pid}", json={"name": "Renamed"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"

    async def test_delete_project(self, auth_client):
        resp = await auth_client.post("/api/projects", json={"name": "Deletable"})
        pid = resp.json()["id"]

        resp = await auth_client.delete(f"/api/projects/{pid}")
        assert resp.status_code == 200

        resp = await auth_client.get(f"/api/projects/{pid}")
        assert resp.status_code in (403, 404)

    async def test_get_not_found(self, auth_client):
        resp = await auth_client.get("/api/projects/nonexistent-id")
        assert resp.status_code in (403, 404)

    async def test_unauthenticated_returns_401(self, client):
        resp = await client.get("/api/projects")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestProjectLlmFields:
    """Test CRUD with the per-purpose LLM model fields."""

    async def test_create_with_llm_fields(self, auth_client):
        resp = await auth_client.post(
            "/api/projects",
            json={
                "name": "LLM Config Project",
                "indexing_llm_provider": "openai",
                "indexing_llm_model": "gpt-4o",
                "agent_llm_provider": "anthropic",
                "agent_llm_model": "claude-3-opus",
                "sql_llm_provider": "openrouter",
                "sql_llm_model": "mistral-large",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["indexing_llm_provider"] == "openai"
        assert data["indexing_llm_model"] == "gpt-4o"
        assert data["agent_llm_provider"] == "anthropic"
        assert data["agent_llm_model"] == "claude-3-opus"
        assert data["sql_llm_provider"] == "openrouter"
        assert data["sql_llm_model"] == "mistral-large"

    async def test_update_llm_fields(self, auth_client):
        resp = await auth_client.post("/api/projects", json={"name": "Update LLM"})
        pid = resp.json()["id"]

        resp = await auth_client.patch(
            f"/api/projects/{pid}",
            json={"agent_llm_provider": "openai", "agent_llm_model": "gpt-4o-mini"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_llm_provider"] == "openai"
        assert data["agent_llm_model"] == "gpt-4o-mini"

    async def test_create_without_llm_fields(self, auth_client):
        resp = await auth_client.post("/api/projects", json={"name": "No LLM"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["indexing_llm_provider"] is None
        assert data["agent_llm_provider"] is None
        assert data["sql_llm_provider"] is None


@pytest.mark.asyncio
class TestProjectAccessControl:
    """Test role-based access control on projects endpoints."""

    async def _setup_project_with_member(self, client, owner_token, role):
        """Create project as owner, register+invite+accept member.

        Returns (project_id, member_token).
        """
        member = await register_user(client)

        resp = await client.post(
            "/api/projects",
            json={"name": "RBAC Proj"},
            headers=auth_headers(owner_token),
        )
        pid = resp.json()["id"]

        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": member["email"], "role": role},
            headers=auth_headers(owner_token),
        )
        invite_id = resp.json()["id"]

        resp = await client.post(
            f"/api/invites/accept/{invite_id}",
            headers=auth_headers(member["token"]),
        )
        assert resp.status_code == 200
        return pid, member["token"]

    async def test_list_only_member_projects(self, client):
        user1 = await register_user(client)
        user2 = await register_user(client)
        await client.post(
            "/api/projects",
            json={"name": "User1 Proj"},
            headers=auth_headers(user1["token"]),
        )
        await client.post(
            "/api/projects",
            json={"name": "User2 Proj"},
            headers=auth_headers(user2["token"]),
        )
        resp = await client.get("/api/projects", headers=auth_headers(user1["token"]))
        names = [p["name"] for p in resp.json()]
        assert "User1 Proj" in names
        assert "User2 Proj" not in names

    async def test_viewer_can_get_but_not_update_or_delete(self, client):
        owner = await register_user(client)
        pid, viewer_token = await self._setup_project_with_member(
            client,
            owner["token"],
            "viewer",
        )

        resp = await client.get(f"/api/projects/{pid}", headers=auth_headers(viewer_token))
        assert resp.status_code == 200

        resp = await client.patch(
            f"/api/projects/{pid}",
            json={"name": "Hacked"},
            headers=auth_headers(viewer_token),
        )
        assert resp.status_code == 403

        resp = await client.delete(f"/api/projects/{pid}", headers=auth_headers(viewer_token))
        assert resp.status_code == 403

    async def test_non_member_gets_403(self, client):
        owner = await register_user(client)
        outsider = await register_user(client)
        resp = await client.post(
            "/api/projects",
            json={"name": "Private"},
            headers=auth_headers(owner["token"]),
        )
        pid = resp.json()["id"]

        resp = await client.get(f"/api/projects/{pid}", headers=auth_headers(outsider["token"]))
        assert resp.status_code == 403
