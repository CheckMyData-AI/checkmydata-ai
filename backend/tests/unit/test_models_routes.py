from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.models import _cache, _sort_openrouter_models
from app.main import app

_FAKE_USER = {"user_id": "test-user-1", "email": "unit@test.local"}


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def clear_cache():
    _cache.clear()
    yield
    _cache.clear()


MOCK_OPENROUTER_RESPONSE = {
    "data": [
        {
            "id": "openai/gpt-4o",
            "name": "GPT-4o",
            "context_length": 128000,
            "pricing": {"prompt": "0.000005", "completion": "0.000015"},
        },
        {
            "id": "anthropic/claude-sonnet-4-20250514",
            "name": "Claude Sonnet 4",
            "context_length": 200000,
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        },
        {
            "id": "google/gemini-2.5-pro",
            "name": "Gemini 2.5 Pro",
            "context_length": 1000000,
            "pricing": {"prompt": "0.00000125", "completion": "0.00001"},
        },
        {
            "id": "anthropic/claude-3-5-haiku-20241022",
            "name": "Claude 3.5 Haiku",
            "context_length": 200000,
            "pricing": {"prompt": "0.0000008", "completion": "0.000004"},
        },
        {
            "id": "meta-llama/llama-3-70b",
            "name": "Llama 3 70B",
            "context_length": 8192,
            "pricing": {"prompt": "0.0000008", "completion": "0.0000008"},
        },
    ]
}


class TestSortOpenRouterModels:
    def test_anthropic_first(self):
        models = [
            {"id": "openai/gpt-4o", "name": "GPT-4o"},
            {"id": "anthropic/claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "google/gemini-2.5-pro", "name": "Gemini"},
            {"id": "anthropic/claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku"},
        ]
        sorted_models = _sort_openrouter_models(models)
        assert sorted_models[0]["id"] == "anthropic/claude-3-5-haiku-20241022"
        assert sorted_models[1]["id"] == "anthropic/claude-sonnet-4-20250514"
        assert sorted_models[2]["id"] == "google/gemini-2.5-pro"
        assert sorted_models[3]["id"] == "openai/gpt-4o"

    def test_alphabetical_within_groups(self):
        models = [
            {"id": "z-provider/z-model", "name": "Z"},
            {"id": "a-provider/a-model", "name": "A"},
            {"id": "anthropic/z-model", "name": "AZ"},
            {"id": "anthropic/a-model", "name": "AA"},
        ]
        sorted_models = _sort_openrouter_models(models)
        ids = [m["id"] for m in sorted_models]
        assert ids == [
            "anthropic/a-model",
            "anthropic/z-model",
            "a-provider/a-model",
            "z-provider/z-model",
        ]

    def test_no_anthropic_models(self):
        models = [
            {"id": "openai/gpt-4o", "name": "GPT-4o"},
            {"id": "google/gemini", "name": "Gemini"},
        ]
        sorted_models = _sort_openrouter_models(models)
        assert sorted_models[0]["id"] == "google/gemini"
        assert sorted_models[1]["id"] == "openai/gpt-4o"

    def test_empty_list(self):
        assert _sort_openrouter_models([]) == []


class TestModelsEndpoint:
    def _make_mock_client(self, response_data):
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        instance = AsyncMock()
        instance.get.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        return instance

    def test_openrouter_returns_sorted(self, client):
        instance = self._make_mock_client(MOCK_OPENROUTER_RESPONSE)

        with patch("app.api.routes.models.httpx.AsyncClient", return_value=instance):
            resp = client.get("/api/models?provider=openrouter")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 5
            assert data[0]["id"].startswith("anthropic/")
            assert data[1]["id"].startswith("anthropic/")
            assert data[0]["id"] < data[1]["id"]

    def test_openrouter_uses_cache(self, client):
        instance = self._make_mock_client(MOCK_OPENROUTER_RESPONSE)

        with patch("app.api.routes.models.httpx.AsyncClient", return_value=instance):
            resp1 = client.get("/api/models?provider=openrouter")
            assert resp1.status_code == 200

            resp2 = client.get("/api/models?provider=openrouter")
            assert resp2.status_code == 200

            assert instance.get.call_count == 1

    def test_openai_static_models(self, client):
        resp = client.get("/api/models?provider=openai")
        assert resp.status_code == 200
        data = resp.json()
        ids = [m["id"] for m in data]
        assert "gpt-4o" in ids
        assert "gpt-4o-mini" in ids

    def test_anthropic_static_models(self, client):
        resp = client.get("/api/models?provider=anthropic")
        assert resp.status_code == 200
        data = resp.json()
        ids = [m["id"] for m in data]
        assert "claude-sonnet-4-20250514" in ids

    def test_unknown_provider_returns_422(self, client):
        resp = client.get("/api/models?provider=unknown")
        assert resp.status_code == 422

    def test_default_provider_is_openrouter(self, client):
        instance = self._make_mock_client({"data": []})

        with patch("app.api.routes.models.httpx.AsyncClient", return_value=instance):
            resp = client.get("/api/models")
            assert resp.status_code == 200

    def test_openrouter_fetch_error_falls_back_to_static_catalog(self, client):
        """T05 — when the live API is down and cache is empty, we must
        return a non-empty static catalog instead of an empty list."""
        instance = AsyncMock()
        instance.get.side_effect = Exception("Connection failed")
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.routes.models.httpx.AsyncClient", return_value=instance):
            resp = client.get("/api/models?provider=openrouter")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) > 0
            ids = [m["id"] for m in data]
            # Must contain both well-known anthropic and openai namespaces.
            assert any(i.startswith("anthropic/") for i in ids)
            assert any(i.startswith("openai/") for i in ids)
