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

        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = None
        _FAKE_DB.execute = AsyncMock(return_value=exec_result)

        with (
            patch("app.api.routes.projects._svc") as mock_svc,
            patch("app.api.routes.projects._membership_svc") as mock_msvc,
        ):
            mock_svc.create = AsyncMock(return_value=mock_project)
            mock_msvc.add_member = AsyncMock()
            resp = client.post("/api/projects", json={"name": "Test"})
            assert resp.status_code == 200
            assert resp.json()["name"] == "Test"
        _FAKE_DB.execute = AsyncMock()

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
        mock_conn.source_type = "database"
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
        mock_conn.mcp_server_command = None
        mock_conn.mcp_server_url = None
        mock_conn.mcp_transport_type = None

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


class TestIndexDbStatusStaleReset:
    """Tests for auto-resetting stale 'running' indexing status."""

    def test_stale_running_status_resets_to_failed(self, client):
        mock_conn = MagicMock()
        mock_conn.project_id = "proj-1"

        with (
            patch("app.api.routes.connections._svc") as mock_svc,
            patch("app.api.routes.connections._membership_svc") as mock_msvc,
            patch("app.api.routes.connections._db_index_svc") as mock_idx_svc,
            patch("app.api.routes.connections._db_index_tasks", {}),
        ):
            mock_svc.get = AsyncMock(return_value=mock_conn)
            mock_msvc.require_role = AsyncMock(return_value="viewer")
            mock_idx_svc.get_status = AsyncMock(
                return_value={
                    "is_indexed": True,
                    "indexing_status": "running",
                    "total_tables": 10,
                    "active_tables": 5,
                }
            )
            mock_idx_svc.set_indexing_status = AsyncMock()

            resp = client.get("/api/connections/conn-1/index-db/status")

            assert resp.status_code == 200
            data = resp.json()
            assert data["is_indexing"] is False
            assert data["indexing_status"] == "failed"
            mock_idx_svc.set_indexing_status.assert_called_once()

    def test_active_task_keeps_running_status(self, client):
        mock_conn = MagicMock()
        mock_conn.project_id = "proj-1"

        running_task = MagicMock()
        running_task.done.return_value = False

        with (
            patch("app.api.routes.connections._svc") as mock_svc,
            patch("app.api.routes.connections._membership_svc") as mock_msvc,
            patch("app.api.routes.connections._db_index_svc") as mock_idx_svc,
            patch(
                "app.api.routes.connections._db_index_tasks",
                {"conn-1": running_task},
            ),
        ):
            mock_svc.get = AsyncMock(return_value=mock_conn)
            mock_msvc.require_role = AsyncMock(return_value="viewer")
            mock_idx_svc.get_status = AsyncMock(
                return_value={
                    "is_indexed": True,
                    "indexing_status": "running",
                    "total_tables": 10,
                    "active_tables": 5,
                }
            )

            resp = client.get("/api/connections/conn-1/index-db/status")

            assert resp.status_code == 200
            data = resp.json()
            assert data["is_indexing"] is True
            assert data["indexing_status"] == "running"

    def test_idle_status_returns_not_indexing(self, client):
        mock_conn = MagicMock()
        mock_conn.project_id = "proj-1"

        with (
            patch("app.api.routes.connections._svc") as mock_svc,
            patch("app.api.routes.connections._membership_svc") as mock_msvc,
            patch("app.api.routes.connections._db_index_svc") as mock_idx_svc,
            patch("app.api.routes.connections._db_index_tasks", {}),
        ):
            mock_svc.get = AsyncMock(return_value=mock_conn)
            mock_msvc.require_role = AsyncMock(return_value="viewer")
            mock_idx_svc.get_status = AsyncMock(
                return_value={
                    "is_indexed": True,
                    "indexing_status": "idle",
                    "total_tables": 10,
                    "active_tables": 5,
                }
            )

            resp = client.get("/api/connections/conn-1/index-db/status")

            assert resp.status_code == 200
            data = resp.json()
            assert data["is_indexing"] is False
            assert data["indexing_status"] == "idle"


class TestSyncStatusStaleReset:
    """Tests for auto-resetting stale 'running' sync status."""

    def test_stale_sync_running_resets_to_failed(self, client):
        mock_conn = MagicMock()
        mock_conn.project_id = "proj-1"

        with (
            patch("app.api.routes.connections._svc") as mock_svc,
            patch("app.api.routes.connections._membership_svc") as mock_msvc,
            patch("app.api.routes.connections._sync_svc") as mock_sync_svc,
            patch("app.api.routes.connections._sync_tasks", {}),
        ):
            mock_svc.get = AsyncMock(return_value=mock_conn)
            mock_msvc.require_role = AsyncMock(return_value="viewer")
            mock_sync_svc.get_status = AsyncMock(
                return_value={
                    "is_synced": False,
                    "sync_status": "running",
                    "total_tables": 10,
                    "synced_tables": 0,
                }
            )
            mock_sync_svc.set_sync_status = AsyncMock()

            resp = client.get("/api/connections/conn-1/sync/status")

            assert resp.status_code == 200
            data = resp.json()
            assert data["is_syncing"] is False
            assert data["sync_status"] == "failed"
            mock_sync_svc.set_sync_status.assert_called_once()

    def test_active_sync_task_keeps_running(self, client):
        mock_conn = MagicMock()
        mock_conn.project_id = "proj-1"

        running_task = MagicMock()
        running_task.done.return_value = False

        with (
            patch("app.api.routes.connections._svc") as mock_svc,
            patch("app.api.routes.connections._membership_svc") as mock_msvc,
            patch("app.api.routes.connections._sync_svc") as mock_sync_svc,
            patch(
                "app.api.routes.connections._sync_tasks",
                {"conn-1": running_task},
            ),
        ):
            mock_svc.get = AsyncMock(return_value=mock_conn)
            mock_msvc.require_role = AsyncMock(return_value="viewer")
            mock_sync_svc.get_status = AsyncMock(
                return_value={
                    "is_synced": False,
                    "sync_status": "running",
                }
            )

            resp = client.get("/api/connections/conn-1/sync/status")

            assert resp.status_code == 200
            data = resp.json()
            assert data["is_syncing"] is True


class TestDbIndexBackgroundPipelineFailure:
    """Tests that pipeline.run() returning failure sets correct final status."""

    @pytest.mark.asyncio
    async def test_pipeline_failure_sets_failed_status(self):
        from app.api.routes.connections import _run_db_index_background

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(
            return_value={
                "status": "failed",
                "error": "LLM timeout",
            }
        )

        with (
            patch("app.models.base.async_session_factory", return_value=mock_session),
            patch("app.api.routes.connections._db_index_svc") as mock_idx_svc,
            patch("app.config.settings") as mock_settings,
            patch("app.knowledge.db_index_pipeline.DbIndexPipeline", return_value=mock_pipeline),
        ):
            mock_settings.db_index_batch_size = 5
            mock_idx_svc.set_indexing_status = AsyncMock()

            config = MagicMock()
            await _run_db_index_background("conn-1", config, "proj-1")

            mock_idx_svc.set_indexing_status.assert_called_once_with(
                mock_session, "conn-1", "failed"
            )

    @pytest.mark.asyncio
    async def test_pipeline_success_sets_idle_status(self):
        from app.api.routes.connections import _run_db_index_background

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(
            return_value={
                "status": "completed",
                "tables_indexed": 10,
            }
        )

        with (
            patch("app.models.base.async_session_factory", return_value=mock_session),
            patch("app.api.routes.connections._db_index_svc") as mock_idx_svc,
            patch("app.config.settings") as mock_settings,
            patch("app.knowledge.db_index_pipeline.DbIndexPipeline", return_value=mock_pipeline),
        ):
            mock_settings.db_index_batch_size = 5
            mock_idx_svc.set_indexing_status = AsyncMock()

            config = MagicMock()
            await _run_db_index_background("conn-1", config, "proj-1")

            mock_idx_svc.set_indexing_status.assert_called_once_with(
                mock_session, "conn-1", "completed"
            )


class TestSyncBackgroundPipelineFailure:
    """Tests that _run_sync_background handles pipeline failures correctly."""

    @pytest.mark.asyncio
    async def test_pipeline_failure_is_logged(self):
        from app.api.routes.connections import _run_sync_background

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(
            return_value={
                "status": "failed",
                "error": "No DB index — index database first",
            }
        )

        with (
            patch("app.models.base.async_session_factory", return_value=mock_session),
            patch("app.api.routes.connections._sync_svc") as mock_sync_svc,
            patch(
                "app.knowledge.code_db_sync_pipeline.CodeDbSyncPipeline",
                return_value=mock_pipeline,
            ),
            patch("app.api.routes.connections._sync_tasks", {}),
            patch("app.api.routes.connections.logger") as mock_logger,
        ):
            mock_sync_svc.set_sync_status = AsyncMock()
            await _run_sync_background("conn-1", "proj-1")

            mock_logger.error.assert_called_once()
            assert "failure" in mock_logger.error.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_pipeline_success_is_logged_as_info(self):
        from app.api.routes.connections import _run_sync_background

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(
            return_value={
                "status": "completed",
                "total_tables": 10,
                "synced": 8,
            }
        )

        with (
            patch("app.models.base.async_session_factory", return_value=mock_session),
            patch("app.api.routes.connections._sync_svc") as mock_sync_svc,
            patch(
                "app.knowledge.code_db_sync_pipeline.CodeDbSyncPipeline",
                return_value=mock_pipeline,
            ),
            patch("app.api.routes.connections._sync_tasks", {}),
            patch("app.api.routes.connections.logger") as mock_logger,
        ):
            mock_sync_svc.set_sync_status = AsyncMock()
            await _run_sync_background("conn-1", "proj-1")

            mock_logger.info.assert_called_once()
            mock_logger.error.assert_not_called()
            mock_sync_svc.set_sync_status.assert_called_once_with(
                mock_session, "conn-1", "completed"
            )


class TestStartupStaleReset:
    """Tests for _reset_stale_indexing_statuses startup hook."""

    @pytest.mark.asyncio
    async def test_resets_stale_running_statuses(self):
        from app.main import _reset_stale_indexing_statuses

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_tx = AsyncMock()
        mock_tx.__aenter__ = AsyncMock(return_value=mock_tx)
        mock_tx.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_tx)

        idx_result = MagicMock(rowcount=2)
        sync_result = MagicMock(rowcount=1)
        mock_session.execute = AsyncMock(side_effect=[idx_result, sync_result])

        with patch("app.main.async_session_factory", return_value=mock_session):
            await _reset_stale_indexing_statuses()

        assert mock_session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_no_commit_when_no_stale(self):
        from app.main import _reset_stale_indexing_statuses

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_tx = AsyncMock()
        mock_tx.__aenter__ = AsyncMock(return_value=mock_tx)
        mock_tx.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_tx)

        idx_result = MagicMock(rowcount=0)
        sync_result = MagicMock(rowcount=0)
        mock_session.execute = AsyncMock(side_effect=[idx_result, sync_result])

        with patch("app.main.async_session_factory", return_value=mock_session):
            await _reset_stale_indexing_statuses()

        mock_session.commit.assert_not_called()


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

    def test_export_xlsx(self, client):
        resp = client.post(
            "/api/visualizations/export",
            json={
                "columns": ["name", "count"],
                "rows": [["Alice", 10]],
                "format": "xlsx",
            },
        )
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]

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


class TestActiveTasksEndpoint:
    def test_active_tasks_empty(self, client):
        resp = client.get("/api/tasks/active")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_active_tasks_returns_running_workflows(self, client):
        from app.core.workflow_tracker import tracker

        tracker._active_workflows["wf-1"] = {
            "workflow_id": "wf-1",
            "pipeline": "index_repo",
            "started_at": 1710000000.0,
            "extra": {"project_id": "p1"},
        }
        try:
            resp = client.get("/api/tasks/active")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["workflow_id"] == "wf-1"
            assert data[0]["pipeline"] == "index_repo"
        finally:
            tracker._active_workflows.pop("wf-1", None)
