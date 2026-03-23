import pytest

from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker


class TestSSEEventGenerator:
    """Tests for the SSE event generation logic (avoids hanging stream tests)."""

    @pytest.mark.asyncio
    async def test_subscriber_receives_formatted_events(self):
        t = WorkflowTracker()
        queue = await t.subscribe()

        await t.emit("wf-1", "clone_repo", "completed", "OK")

        event = queue.get_nowait()
        assert event.workflow_id == "wf-1"
        assert event.step == "clone_repo"

        json_str = event.to_json()
        assert '"workflow_id": "wf-1"' in json_str
        assert '"step": "clone_repo"' in json_str
        assert '"status": "completed"' in json_str

        await t.unsubscribe(queue)

    @pytest.mark.asyncio
    async def test_workflow_id_filter_logic(self):
        """Simulates the SSE endpoint filtering by workflow_id."""
        t = WorkflowTracker()
        queue = await t.subscribe()

        await t.emit("wf-other", "step1", "started")
        await t.emit("wf-target", "step2", "completed", "should match")

        events: list[WorkflowEvent] = []
        while not queue.empty():
            events.append(queue.get_nowait())

        target_filter = "wf-target"
        filtered = [e for e in events if e.workflow_id == target_filter]

        assert len(filtered) == 1
        assert filtered[0].step == "step2"

        await t.unsubscribe(queue)

    @pytest.mark.asyncio
    async def test_sse_format_output(self):
        """Verifies the SSE line format: 'event: step\\ndata: {json}\\n\\n'"""
        event = WorkflowEvent(
            workflow_id="abc",
            step="analyze",
            status="completed",
            detail="Analyzed 10 files",
            elapsed_ms=500.0,
            timestamp=1710000000.0,
        )
        sse_line = f"event: step\ndata: {event.to_json()}\n\n"

        assert sse_line.startswith("event: step\n")
        assert "data: {" in sse_line
        assert sse_line.endswith("\n\n")
        assert '"workflow_id": "abc"' in sse_line

    @pytest.mark.asyncio
    async def test_full_pipeline_event_sequence(self):
        t = WorkflowTracker()
        queue = await t.subscribe()

        wf_id = await t.begin("index_repo")

        async with t.step(wf_id, "clone_or_pull", "cloning"):
            pass

        async with t.step(wf_id, "analyze_files", "analyzing"):
            pass

        await t.end(wf_id, "index_repo")

        events: list[WorkflowEvent] = []
        while not queue.empty():
            events.append(queue.get_nowait())

        steps = [e.step for e in events]
        statuses = [e.status for e in events]

        assert "pipeline_start" in steps
        assert "clone_or_pull" in steps
        assert "analyze_files" in steps
        assert "pipeline_end" in steps

        assert statuses[0] == "started"
        assert statuses[-1] == "completed"

        await t.unsubscribe(queue)
