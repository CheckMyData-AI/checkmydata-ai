"""Integration tests for /api/models endpoint."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
class TestModelsList:
    async def test_list_models_default(self, auth_client):
        with patch(
            "app.api.routes.models._fetch_openrouter_models",
            new_callable=AsyncMock,
            return_value=[
                {"id": "openai/gpt-4o", "name": "GPT-4o", "context_length": 128000},
            ],
        ):
            resp = await auth_client.get("/api/models")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_models_openai(self, auth_client):
        resp = await auth_client.get("/api/models?provider=openai")
        assert resp.status_code == 200
        models = resp.json()
        assert len(models) > 0
        assert any("gpt" in m["id"].lower() for m in models)

    async def test_list_models_anthropic(self, auth_client):
        resp = await auth_client.get("/api/models?provider=anthropic")
        assert resp.status_code == 200
        models = resp.json()
        assert len(models) > 0
        assert any("claude" in m["id"].lower() for m in models)

    async def test_list_models_openrouter(self, auth_client):
        with patch(
            "app.api.routes.models._fetch_openrouter_models",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": "anthropic/claude-3-opus",
                    "name": "Claude 3 Opus",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.015", "completion": "0.075"},
                },
            ],
        ):
            resp = await auth_client.get("/api/models?provider=openrouter")
        assert resp.status_code == 200
        models = resp.json()
        assert len(models) == 1
        assert models[0]["id"] == "anthropic/claude-3-opus"

    async def test_models_requires_auth(self, client):
        resp = await client.get("/api/models")
        assert resp.status_code == 401
