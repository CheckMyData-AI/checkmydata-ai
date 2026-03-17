"""Integration tests for POST /api/repos/check-access."""

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
class TestRepoCheckAccess:
    async def test_check_public_https_repo(self, auth_client):
        """Successful access check with mocked git ls-remote."""
        mock_result = {
            "accessible": True,
            "branches": ["develop", "main"],
            "default_branch": "main",
            "error": None,
        }
        with patch(
            "app.api.routes.repos._repo_analyzer.list_remote_refs",
            return_value=mock_result,
        ):
            resp = await auth_client.post(
                "/api/repos/check-access",
                json={"repo_url": "https://github.com/org/repo.git"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accessible"] is True
        assert "main" in data["branches"]
        assert data["default_branch"] == "main"

    async def test_check_access_denied(self, auth_client):
        """Access denied returns structured error."""
        mock_result = {
            "accessible": False,
            "branches": [],
            "default_branch": None,
            "error": "Permission denied (publickey).",
        }
        with patch(
            "app.api.routes.repos._repo_analyzer.list_remote_refs",
            return_value=mock_result,
        ):
            resp = await auth_client.post(
                "/api/repos/check-access",
                json={"repo_url": "git@github.com:org/private.git"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accessible"] is False
        assert "Permission denied" in data["error"]

    async def test_check_with_nonexistent_ssh_key(self, auth_client):
        """Using a non-existent SSH key ID returns error."""
        resp = await auth_client.post(
            "/api/repos/check-access",
            json={
                "repo_url": "git@github.com:org/repo.git",
                "ssh_key_id": "nonexistent-key-id",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accessible"] is False
        assert "not found" in data["error"].lower()

    async def test_check_no_url_returns_validation_error(self, auth_client):
        """Missing repo_url triggers a validation error."""
        resp = await auth_client.post(
            "/api/repos/check-access",
            json={},
        )
        assert resp.status_code == 422

    async def test_check_without_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = await client.post(
            "/api/repos/check-access",
            json={"repo_url": "https://github.com/org/repo.git"},
        )
        assert resp.status_code == 401

    async def test_check_returns_empty_branches(self, auth_client):
        """Empty repo returns accessible=True with no branches."""
        mock_result = {
            "accessible": True,
            "branches": [],
            "default_branch": None,
            "error": None,
        }
        with patch(
            "app.api.routes.repos._repo_analyzer.list_remote_refs",
            return_value=mock_result,
        ):
            resp = await auth_client.post(
                "/api/repos/check-access",
                json={"repo_url": "https://github.com/org/empty.git"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accessible"] is True
        assert data["branches"] == []
        assert data["default_branch"] is None

    async def test_check_many_branches(self, auth_client):
        """Response includes all branches from the remote."""
        branches = [f"feature/{i}" for i in range(20)] + ["main", "master"]
        mock_result = {
            "accessible": True,
            "branches": sorted(branches),
            "default_branch": "main",
            "error": None,
        }
        with patch(
            "app.api.routes.repos._repo_analyzer.list_remote_refs",
            return_value=mock_result,
        ):
            resp = await auth_client.post(
                "/api/repos/check-access",
                json={"repo_url": "git@github.com:org/big.git"},
            )
        data = resp.json()
        assert data["accessible"] is True
        assert len(data["branches"]) == 22
        assert data["default_branch"] == "main"
