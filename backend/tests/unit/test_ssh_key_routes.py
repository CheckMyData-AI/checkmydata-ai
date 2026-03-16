from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestSshKeyRoutes:
    def test_list_empty(self, client):
        with patch("app.api.routes.ssh_keys._svc") as mock_svc:
            mock_svc.list_all = AsyncMock(return_value=[])
            resp = client.get("/api/ssh-keys")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_list_with_keys(self, client):
        mock_key = MagicMock()
        mock_key.id = "key-1"
        mock_key.name = "prod-server"
        mock_key.fingerprint = "abc123"
        mock_key.key_type = "ssh-ed25519"
        mock_key.created_at = datetime(2026, 1, 1, 0, 0, 0)

        with patch("app.api.routes.ssh_keys._svc") as mock_svc:
            mock_svc.list_all = AsyncMock(return_value=[mock_key])
            resp = client.get("/api/ssh-keys")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["name"] == "prod-server"
            assert data[0]["key_type"] == "ssh-ed25519"

    def test_create_success(self, client):
        mock_key = MagicMock()
        mock_key.id = "key-new"
        mock_key.name = "my-key"
        mock_key.fingerprint = "sha256hash"
        mock_key.key_type = "ssh-rsa"
        mock_key.created_at = datetime(2026, 3, 14, 0, 0, 0)

        with patch("app.api.routes.ssh_keys._svc") as mock_svc:
            mock_svc.create = AsyncMock(return_value=mock_key)
            resp = client.post("/api/ssh-keys", json={
                "name": "my-key",
                "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----",
            })
            assert resp.status_code == 200
            assert resp.json()["name"] == "my-key"

    def test_create_invalid_key(self, client):
        with patch("app.api.routes.ssh_keys._svc") as mock_svc:
            mock_svc.create = AsyncMock(side_effect=ValueError("Invalid SSH key: bad format"))
            resp = client.post("/api/ssh-keys", json={
                "name": "bad-key",
                "private_key": "not a key",
            })
            assert resp.status_code == 400
            assert "Invalid SSH key" in resp.json()["detail"]

    def test_create_duplicate_name(self, client):
        with patch("app.api.routes.ssh_keys._svc") as mock_svc:
            mock_svc.create = AsyncMock(side_effect=Exception("UNIQUE constraint failed"))
            resp = client.post("/api/ssh-keys", json={
                "name": "dupe",
                "private_key": "test",
            })
            assert resp.status_code == 409

    def test_get_not_found(self, client):
        with patch("app.api.routes.ssh_keys._svc") as mock_svc:
            mock_svc.get = AsyncMock(return_value=None)
            resp = client.get("/api/ssh-keys/nonexistent")
            assert resp.status_code == 404

    def test_delete_success(self, client):
        with patch("app.api.routes.ssh_keys._svc") as mock_svc:
            mock_svc.delete = AsyncMock(return_value=True)
            resp = client.delete("/api/ssh-keys/key-1")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}

    def test_delete_not_found(self, client):
        with patch("app.api.routes.ssh_keys._svc") as mock_svc:
            mock_svc.delete = AsyncMock(return_value=False)
            resp = client.delete("/api/ssh-keys/nonexistent")
            assert resp.status_code == 404

    def test_delete_in_use(self, client):
        from app.services.ssh_key_service import SshKeyInUseError
        with patch("app.api.routes.ssh_keys._svc") as mock_svc:
            mock_svc.delete = AsyncMock(
                side_effect=SshKeyInUseError(["project:MyProject"])
            )
            resp = client.delete("/api/ssh-keys/key-1")
            assert resp.status_code == 409
            assert "in use" in resp.json()["detail"]
