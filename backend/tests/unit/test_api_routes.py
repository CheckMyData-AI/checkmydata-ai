from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestProjectRoutes:
    def test_list_projects(self, client):
        with patch("app.api.routes.projects._svc") as mock_svc:
            mock_svc.list_all = AsyncMock(return_value=[])
            resp = client.get("/api/projects")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_create_project(self, client):
        mock_project = MagicMock()
        mock_project.id = "proj-123"
        mock_project.name = "Test"
        mock_project.description = ""
        mock_project.repo_url = None
        mock_project.repo_branch = "main"
        mock_project.ssh_key_id = None
        mock_project.default_llm_provider = None
        mock_project.default_llm_model = None

        with patch("app.api.routes.projects._svc") as mock_svc:
            mock_svc.create = AsyncMock(return_value=mock_project)
            resp = client.post("/api/projects", json={"name": "Test"})
            assert resp.status_code == 200
            assert resp.json()["name"] == "Test"

    def test_get_project_not_found(self, client):
        with patch("app.api.routes.projects._svc") as mock_svc:
            mock_svc.get = AsyncMock(return_value=None)
            resp = client.get("/api/projects/nonexistent")
            assert resp.status_code == 404


class TestConnectionRoutes:
    def test_list_connections(self, client):
        with patch("app.api.routes.connections._svc") as mock_svc:
            mock_svc.list_by_project = AsyncMock(return_value=[])
            resp = client.get("/api/connections/project/proj-1")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_update_connection(self, client):
        mock_conn = MagicMock()
        mock_conn.id = "conn-1"
        mock_conn.project_id = "proj-1"
        mock_conn.name = "Updated"
        mock_conn.db_type = "mysql"
        mock_conn.ssh_host = None
        mock_conn.ssh_port = 22
        mock_conn.ssh_key_id = None
        mock_conn.db_host = "127.0.0.1"
        mock_conn.db_port = 3306
        mock_conn.db_name = "mydb"
        mock_conn.db_user = "root"
        mock_conn.is_read_only = True
        mock_conn.is_active = True

        with patch("app.api.routes.connections._svc") as mock_svc:
            mock_svc.update = AsyncMock(return_value=mock_conn)
            resp = client.patch("/api/connections/conn-1", json={"name": "Updated"})
            assert resp.status_code == 200
            assert resp.json()["name"] == "Updated"

    def test_update_connection_not_found(self, client):
        with patch("app.api.routes.connections._svc") as mock_svc:
            mock_svc.update = AsyncMock(return_value=None)
            resp = client.patch("/api/connections/nonexistent", json={"name": "X"})
            assert resp.status_code == 404


class TestChatSessionRoutes:
    def test_list_sessions(self, client):
        with patch("app.api.routes.chat._chat_svc") as mock_svc:
            mock_svc.list_sessions = AsyncMock(return_value=[])
            resp = client.get("/api/chat/sessions/proj-1")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_delete_session_not_found(self, client):
        with patch("app.api.routes.chat._chat_svc") as mock_svc:
            mock_svc.delete_session = AsyncMock(return_value=False)
            resp = client.delete("/api/chat/sessions/nonexistent")
            assert resp.status_code == 404


class TestVisualizationRoutes:
    def test_render(self, client):
        resp = client.post("/api/visualizations/render", json={
            "columns": ["name", "count"],
            "rows": [["Alice", 10], ["Bob", 20]],
            "viz_type": "table",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "table"
        assert "columns" in data["data"]
        assert len(data["data"]["rows"]) == 2

    def test_export_csv(self, client):
        resp = client.post("/api/visualizations/export", json={
            "columns": ["name", "count"],
            "rows": [["Alice", 10]],
            "format": "csv",
        })
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    def test_export_json(self, client):
        resp = client.post("/api/visualizations/export", json={
            "columns": ["name", "count"],
            "rows": [["Alice", 10]],
            "format": "json",
        })
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]

    def test_export_unsupported_format(self, client):
        resp = client.post("/api/visualizations/export", json={
            "columns": ["name"],
            "rows": [["Alice"]],
            "format": "pdf",
        })
        assert resp.status_code == 400
