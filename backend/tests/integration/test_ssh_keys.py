"""Integration tests for /api/ssh-keys endpoints."""

import subprocess
import tempfile
from pathlib import Path

import pytest

_DUMMY_KEY: str | None = None


def _generate_test_key() -> str:
    global _DUMMY_KEY
    if _DUMMY_KEY:
        return _DUMMY_KEY
    with tempfile.TemporaryDirectory() as td:
        key_path = Path(td) / "test_key"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path), "-q"],
            check=True,
        )
        _DUMMY_KEY = key_path.read_text()
    return _DUMMY_KEY


@pytest.mark.asyncio
class TestSshKeyCrud:
    async def test_create_and_list(self, auth_client):
        key = _generate_test_key()
        resp = await auth_client.post(
            "/api/ssh-keys",
            json={
                "name": "test-key",
                "private_key": key,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-key"
        assert "ed25519" in data["key_type"]
        assert data["fingerprint"]

        resp = await auth_client.get("/api/ssh-keys")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_get_not_found(self, auth_client):
        resp = await auth_client.get("/api/ssh-keys/missing")
        assert resp.status_code == 404

    async def test_create_invalid_key(self, auth_client):
        resp = await auth_client.post(
            "/api/ssh-keys",
            json={
                "name": "bad",
                "private_key": "not-a-real-key",
            },
        )
        assert resp.status_code == 400
