"""Integration tests for /api/repos repository management endpoints."""

import pytest


@pytest.mark.asyncio
class TestRepoStatus:
    async def _create_project(self, auth_client, name="Repo Proj") -> str:
        resp = await auth_client.post("/api/projects", json={"name": name})
        return resp.json()["id"]

    async def test_repo_status_no_index(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.get(f"/api/repos/{pid}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_indexed_commit"] is None
        assert data["total_documents"] == 0

    async def test_docs_list_empty(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.get(f"/api/repos/{pid}/docs")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_docs_get_not_found(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.get(f"/api/repos/{pid}/docs/nonexistent")
        assert resp.status_code == 404

    async def test_check_updates_no_repo(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(f"/api/repos/{pid}/check-updates")
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestRepositoryCrud:
    async def _create_project(self, auth_client, name="RepoCrud Proj") -> str:
        resp = await auth_client.post("/api/projects", json={"name": name})
        return resp.json()["id"]

    async def test_add_repository(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            f"/api/repos/{pid}/repositories",
            json={
                "name": "my-repo",
                "repo_url": "git@github.com:test/repo.git",
                "branch": "main",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "my-repo"
        assert data["project_id"] == pid

    async def test_list_repositories(self, auth_client):
        pid = await self._create_project(auth_client)
        await auth_client.post(
            f"/api/repos/{pid}/repositories",
            json={"name": "repo-a", "repo_url": "git@github.com:t/a.git"},
        )
        resp = await auth_client.get(f"/api/repos/{pid}/repositories")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_list_repositories_empty(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.get(f"/api/repos/{pid}/repositories")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_update_repository(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            f"/api/repos/{pid}/repositories",
            json={"name": "before", "repo_url": "git@github.com:t/x.git"},
        )
        rid = resp.json()["id"]
        resp = await auth_client.patch(
            f"/api/repos/repositories/{rid}",
            json={"name": "after"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "after"

    async def test_update_repository_not_found(self, auth_client):
        resp = await auth_client.patch(
            "/api/repos/repositories/nonexistent",
            json={"name": "nope"},
        )
        assert resp.status_code == 404

    async def test_delete_repository(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post(
            f"/api/repos/{pid}/repositories",
            json={"name": "del-me", "repo_url": "git@github.com:t/d.git"},
        )
        rid = resp.json()["id"]
        resp = await auth_client.delete(f"/api/repos/repositories/{rid}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_delete_repository_not_found(self, auth_client):
        resp = await auth_client.delete("/api/repos/repositories/nonexistent")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestReposAuth:
    async def test_repos_require_auth(self, client):
        endpoints = [
            ("GET", "/api/repos/fake/status"),
            ("POST", "/api/repos/fake/index"),
            ("GET", "/api/repos/fake/docs"),
            ("GET", "/api/repos/fake/docs/fake-doc"),
            ("POST", "/api/repos/fake/check-updates"),
            ("POST", "/api/repos/fake/repositories"),
            ("GET", "/api/repos/fake/repositories"),
            ("PATCH", "/api/repos/repositories/fake"),
            ("DELETE", "/api/repos/repositories/fake"),
        ]
        for method, url in endpoints:
            resp = await getattr(client, method.lower())(url)
            assert resp.status_code == 401, f"{method} {url} should require auth"
