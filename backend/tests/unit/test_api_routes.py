from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.main import app

_FAKE_USER = {"user_id": "test-user-1", "email": "unit@test.local"}
_FAKE_DB = AsyncMock()


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    app.dependency_overrides[get_db] = lambda: _FAKE_DB
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestProjectRoutes:
    def test_list_projects(self, client):
        with (
            patch("app.api.routes.projects._svc") as mock_svc,
            patch("app.api.routes.projects._membership_svc") as mock_msvc,
        ):
            mock_msvc.get_accessible_projects = AsyncMock(return_value=[])
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
        mock_project.indexing_llm_provider = None
        mock_project.indexing_llm_model = None
        mock_project.agent_llm_provider = None
        mock_project.agent_llm_model = None
        mock_project.sql_llm_provider = None
        mock_project.sql_llm_model = None
        mock_project.owner_id = "test-user-1"

        with (
            patch("app.api.routes.projects._svc") as mock_svc,
            patch("app.api.routes.projects._membership_svc") as mock_msvc,
        ):
            mock_svc.create = AsyncMock(return_value=mock_project)
            mock_msvc.add_member = AsyncMock()
            resp = client.post("/api/projects", json={"name": "Test"})
            assert resp.status_code == 200
            assert resp.json()["name"] == "Test"

    def test_get_project_not_found(self, client):
        with (
            patch("app.api.routes.projects._svc") as mock_svc,
            patch("app.api.routes.projects._membership_svc") as mock_msvc,
        ):
            mock_msvc.require_role = AsyncMock(return_value="owner")
            mock_svc.get = AsyncMock(return_value=None)
            resp = client.get("/api/projects/nonexistent")
            assert resp.status_code == 404


class TestConnectionRoutes:
    def test_list_connections(self, client):
        with (
            patch("app.api.routes.connections._svc") as mock_svc,
            patch("app.api.routes.connections._membership_svc") as mock_msvc,
        ):
            mock_msvc.require_role = AsyncMock(return_value="viewer")
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
        mock_conn.ssh_user = None
        mock_conn.ssh_key_id = None
        mock_conn.db_host = "127.0.0.1"
        mock_conn.db_port = 3306
        mock_conn.db_name = "mydb"
        mock_conn.db_user = "root"
        mock_conn.is_read_only = True
        mock_conn.is_active = True
        mock_conn.ssh_exec_mode = False
        mock_conn.ssh_command_template = None
        mock_conn.ssh_pre_commands = None

        with (
            patch("app.api.routes.connections._svc") as mock_svc,
            patch("app.api.routes.connections._membership_svc") as mock_msvc,
        ):
            mock_svc.get = AsyncMock(return_value=mock_conn)
            mock_msvc.require_role = AsyncMock(return_value="editor")
            mock_svc.update = AsyncMock(return_value=mock_conn)
            resp = client.patch("/api/connections/conn-1", json={"name": "Updated"})
            assert resp.status_code == 200
            assert resp.json()["name"] == "Updated"

    def test_update_connection_not_found(self, client):
        with (
            patch("app.api.routes.connections._svc") as mock_svc,
            patch("app.api.routes.connections._membership_svc") as mock_msvc,
        ):
            mock_svc.get = AsyncMock(return_value=None)
            mock_msvc.require_role = AsyncMock(return_value="editor")
            mock_svc.update = AsyncMock(return_value=None)
            resp = client.patch("/api/connections/nonexistent", json={"name": "X"})
            assert resp.status_code == 404


class TestChatSessionRoutes:
    def test_list_sessions(self, client):
        with (
            patch("app.api.routes.chat._chat_svc") as mock_svc,
            patch("app.api.routes.chat._membership_svc") as mock_msvc,
        ):
            mock_msvc.require_role = AsyncMock(return_value="viewer")
            mock_svc.list_sessions = AsyncMock(return_value=[])
            resp = client.get("/api/chat/sessions/proj-1")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_delete_session_not_found(self, client):
        with (
            patch("app.api.routes.chat._chat_svc") as mock_svc,
        ):
            mock_svc.get_session = AsyncMock(return_value=None)
            mock_svc.delete_session = AsyncMock(return_value=False)
            resp = client.delete("/api/chat/sessions/nonexistent")
            assert resp.status_code == 404


class TestVisualizationRoutes:
    def test_render(self, client):
        resp = client.post(
            "/api/visualizations/render",
            json={
                "columns": ["name", "count"],
                "rows": [["Alice", 10], ["Bob", 20]],
                "viz_type": "table",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "table"
        assert "columns" in data["data"]
        assert len(data["data"]["rows"]) == 2

    def test_export_csv(self, client):
        resp = client.post(
            "/api/visualizations/export",
            json={
                "columns": ["name", "count"],
                "rows": [["Alice", 10]],
                "format": "csv",
            },
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    def test_export_json(self, client):
        resp = client.post(
            "/api/visualizations/export",
            json={
                "columns": ["name", "count"],
                "rows": [["Alice", 10]],
                "format": "json",
            },
        )
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]

    def test_export_unsupported_format(self, client):
        resp = client.post(
            "/api/visualizations/export",
            json={
                "columns": ["name"],
                "rows": [["Alice"]],
                "format": "pdf",
            },
        )
        assert resp.status_code == 400
