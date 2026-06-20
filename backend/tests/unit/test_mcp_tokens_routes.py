"""Tests for the /api/auth/mcp-tokens routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app

_FAKE_USER = {"user_id": "test-user-1", "email": "unit@test.local"}


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def _record(**kwargs):
    rec = MagicMock()
    rec.id = kwargs.get("id", "tok-1")
    rec.user_id = kwargs.get("user_id", "test-user-1")
    rec.name = kwargs.get("name", "laptop")
    rec.token_prefix = kwargs.get("token_prefix", "cmd_mcp_ABCD")
    rec.created_at = kwargs.get("created_at", datetime(2026, 1, 1, tzinfo=UTC))
    rec.last_used_at = kwargs.get("last_used_at")
    rec.expires_at = kwargs.get("expires_at")
    rec.revoked_at = kwargs.get("revoked_at")
    return rec


class TestMcpTokenRoutes:
    def test_create_returns_plaintext_token_once(self, client):
        rec = _record()
        issued = MagicMock()
        issued.record = rec
        issued.plaintext = "cmd_mcp_FULLPLAINTEXT"

        with patch("app.api.routes.mcp_tokens._svc") as mock_svc:
            mock_svc.issue = AsyncMock(return_value=issued)
            resp = client.post(
                "/api/auth/mcp-tokens",
                json={"name": "laptop"},
            )

        assert resp.status_code == 200
        data = resp.json()
        # Plaintext is exposed ONLY in the create response.
        assert data["token"] == "cmd_mcp_FULLPLAINTEXT"
        assert data["token_prefix"] == "cmd_mcp_ABCD"
        assert data["name"] == "laptop"
        assert data["revoked_at"] is None
        # The service was called with the JWT-resolved user, not anything the
        # caller sent in the body.
        mock_svc.issue.assert_awaited_once()
        kwargs = mock_svc.issue.await_args.kwargs
        assert kwargs["user_id"] == "test-user-1"
        assert kwargs["name"] == "laptop"

    def test_create_rejects_empty_name(self, client):
        resp = client.post("/api/auth/mcp-tokens", json={"name": ""})
        # FastAPI / Pydantic validation rejects empty names with 422.
        assert resp.status_code == 422

    def test_create_propagates_service_validation_error_as_400(self, client):
        with patch("app.api.routes.mcp_tokens._svc") as mock_svc:
            mock_svc.issue = AsyncMock(side_effect=ValueError("name is required"))
            resp = client.post("/api/auth/mcp-tokens", json={"name": "ok"})
        assert resp.status_code == 400
        assert "name is required" in resp.json()["detail"]

    def test_list_returns_tokens_without_plaintext(self, client):
        rec = _record(last_used_at=datetime(2026, 2, 1, tzinfo=UTC))
        with patch("app.api.routes.mcp_tokens._svc") as mock_svc:
            mock_svc.list_for_user = AsyncMock(return_value=[rec])
            resp = client.get("/api/auth/mcp-tokens")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        # No plaintext field on list — only the prefix used for identification.
        assert "token" not in data[0]
        assert data[0]["token_prefix"] == "cmd_mcp_ABCD"
        assert data[0]["last_used_at"] == "2026-02-01T00:00:00+00:00"
        mock_svc.list_for_user.assert_awaited_once()
        # The route must scope to the caller — never an arbitrary user id.
        assert mock_svc.list_for_user.await_args.args[1] == "test-user-1"

    def test_revoke_success(self, client):
        with patch("app.api.routes.mcp_tokens._svc") as mock_svc:
            mock_svc.revoke = AsyncMock(return_value=True)
            resp = client.delete("/api/auth/mcp-tokens/tok-1")
        assert resp.status_code == 200
        assert resp.json() == {"revoked": True}
        # Revoke is also scoped to the caller's user id so user A can't
        # revoke user B's tokens.
        args = mock_svc.revoke.await_args.args
        assert args[1] == "tok-1"
        assert args[2] == "test-user-1"

    def test_revoke_unknown_returns_404(self, client):
        with patch("app.api.routes.mcp_tokens._svc") as mock_svc:
            mock_svc.revoke = AsyncMock(return_value=False)
            resp = client.delete("/api/auth/mcp-tokens/missing")
        assert resp.status_code == 404

    def test_revoke_rejects_path_traversal_id(self, client):
        resp = client.delete("/api/auth/mcp-tokens/..%2Fother")
        # validate_safe_id rejects non-alphanumeric ids with 400.
        assert resp.status_code in (400, 404)
