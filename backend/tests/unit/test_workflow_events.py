"""Unit tests for cross-process workflow event bridge."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker


@pytest.mark.asyncio
async def test_cross_process_publish_calls_redis():
    tracker = WorkflowTracker()
    tracker.enable_cross_process_publish()

    event = WorkflowEvent(
        workflow_id="wf-test",
        step="pipeline_start",
        status="started",
        pipeline="code_db_sync",
        extra={"project_id": "proj-1"},
    )

    with patch(
        "app.core.workflow_events.publish_workflow_event",
        new_callable=AsyncMock,
    ) as mock_publish:
        await tracker._broadcast(event)

    mock_publish.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_broadcast_external_registers_active_workflow():
    tracker = WorkflowTracker()

    event = WorkflowEvent(
        workflow_id="wf-ext",
        step="pipeline_start",
        status="started",
        pipeline="index_repo",
        extra={"project_id": "proj-1"},
    )

    with patch.object(tracker, "_deliver_local", new_callable=AsyncMock) as mock_deliver:
        await tracker.broadcast_external(event)

    assert "wf-ext" in tracker._active_workflows
    mock_deliver.assert_called_once_with(event)
