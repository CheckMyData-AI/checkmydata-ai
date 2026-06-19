"""Unit tests for PipelineStatusService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pipeline_status_service import PipelineStatusService


@pytest.mark.asyncio
async def test_get_status_any_running_when_checkpoint_running():
    svc = PipelineStatusService()
    session = AsyncMock()

    mock_project = MagicMock()
    mock_project.repo_url = "https://github.com/org/repo"
    mock_project.repo_branch = "main"

    mock_checkpoint = MagicMock()
    mock_checkpoint.status = "running"
    mock_checkpoint.workflow_id = "wf-1"

    with (
        patch(
            "app.services.pipeline_status_service._project_svc.get",
            AsyncMock(return_value=mock_project),
        ),
        patch(
            "app.services.pipeline_status_service._checkpoint_svc.get_active",
            AsyncMock(return_value=mock_checkpoint),
        ),
        patch(
            "app.services.pipeline_status_service._git_tracker.get_last_indexed_record",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.pipeline_status_service._conn_svc.list_by_project",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await svc.get_status(session, "proj-1")

    assert result["any_running"] is True
    assert result["repo"]["is_indexing"] is True
    assert result["repo"]["workflow_id"] == "wf-1"


@pytest.mark.asyncio
async def test_list_synthetic_active_tasks_returns_empty_without_arq():
    svc = PipelineStatusService()
    session = AsyncMock()

    with patch("app.services.pipeline_status_service.task_queue") as mock_tq:
        mock_tq.is_arq_active.return_value = False
        result = await svc.list_synthetic_active_tasks(session, accessible_project_ids={"proj-1"})

    assert result == []
