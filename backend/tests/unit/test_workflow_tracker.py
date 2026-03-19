import pytest

from app.core.workflow_tracker import (
    BACKGROUND_PIPELINES,
    WorkflowEvent,
    WorkflowTracker,
    workflow_id_var,
)


class TestWorkflowEvent:
    def test_to_json(self):
        event = WorkflowEvent(
            workflow_id="abc-123",
            step="clone_repo",
            status="completed",
            detail="Cloned OK",
            elapsed_ms=1234.5,
            timestamp=1710000000.0,
            pipeline="index",
        )
        raw = event.to_json()
        assert '"workflow_id": "abc-123"' in raw
        assert '"step": "clone_repo"' in raw
        assert '"status": "completed"' in raw

    def test_default_fields(self):
        event = WorkflowEvent(workflow_id="x", step="s", status="started")
        assert event.detail == ""
        assert event.elapsed_ms is None
        assert event.extra == {}
        assert event.timestamp > 0


class TestWorkflowTracker:
    @pytest.mark.asyncio
    async def test_begin_returns_uuid(self):
        t = WorkflowTracker()
        wf_id = await t.begin("test_pipeline")
        assert len(wf_id) == 36  # UUID format
        assert workflow_id_var.get() == wf_id

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self):
        t = WorkflowTracker()
        queue = t.subscribe()

        wf_id = await t.begin("test")
        event = queue.get_nowait()
        assert event.workflow_id == wf_id
        assert event.step == "pipeline_start"
        assert event.status == "started"

        t.unsubscribe(queue)

    @pytest.mark.asyncio
    async def test_step_context_manager_completed(self):
        t = WorkflowTracker()
        queue = t.subscribe()
        wf_id = "test-wf-id"

        async with t.step(wf_id, "my_step", "doing things"):
            pass

        started = queue.get_nowait()
        assert started.step == "my_step"
        assert started.status == "started"

        completed = queue.get_nowait()
        assert completed.step == "my_step"
        assert completed.status == "completed"
        assert completed.elapsed_ms is not None
        assert completed.elapsed_ms >= 0

        t.unsubscribe(queue)

    @pytest.mark.asyncio
    async def test_step_context_manager_failed(self):
        t = WorkflowTracker()
        queue = t.subscribe()
        wf_id = "test-wf-id"

        with pytest.raises(ValueError, match="boom"):
            async with t.step(wf_id, "bad_step"):
                raise ValueError("boom")

        started = queue.get_nowait()
        assert started.status == "started"

        failed = queue.get_nowait()
        assert failed.status == "failed"
        assert "boom" in failed.detail

        t.unsubscribe(queue)

    @pytest.mark.asyncio
    async def test_end_sets_contextvar_to_none(self):
        t = WorkflowTracker()
        wf_id = await t.begin("test")
        assert workflow_id_var.get() == wf_id

        await t.end(wf_id, "test")
        assert workflow_id_var.get() is None

    @pytest.mark.asyncio
    async def test_unsubscribe_idempotent(self):
        t = WorkflowTracker()
        queue = t.subscribe()
        t.unsubscribe(queue)
        t.unsubscribe(queue)  # should not raise

    @pytest.mark.asyncio
    async def test_full_queue_drops_subscriber(self):
        t = WorkflowTracker()
        queue = t.subscribe()

        # fill the queue to its maximum capacity (1024)
        for _ in range(WorkflowTracker._QUEUE_MAXSIZE):
            queue.put_nowait(WorkflowEvent(workflow_id="x", step="s", status="started"))

        # next broadcast should evict the full queue
        await t.emit("y", "s2", "started")
        assert queue not in t._subscribers

    @pytest.mark.asyncio
    async def test_emit_custom_event(self):
        t = WorkflowTracker()
        queue = t.subscribe()

        await t.emit("wf-1", "custom", "completed", "extra detail", count=42)

        event = queue.get_nowait()
        assert event.step == "custom"
        assert event.status == "completed"
        assert event.detail == "extra detail"
        assert event.extra["count"] == 42

        t.unsubscribe(queue)

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        t = WorkflowTracker()
        q1 = t.subscribe()
        q2 = t.subscribe()

        await t.emit("wf", "step", "started")

        assert not q1.empty()
        assert not q2.empty()

        t.unsubscribe(q1)
        t.unsubscribe(q2)

    @pytest.mark.asyncio
    async def test_active_workflows_tracked_for_background_pipelines(self):
        t = WorkflowTracker()
        for pipeline in BACKGROUND_PIPELINES:
            wf_id = await t.begin(pipeline, {"test": True})
            active = t.get_active()
            assert any(w["workflow_id"] == wf_id for w in active)
            assert any(w["pipeline"] == pipeline for w in active)
            await t.end(wf_id, pipeline)
            active = t.get_active()
            assert not any(w["workflow_id"] == wf_id for w in active)

    @pytest.mark.asyncio
    async def test_active_workflows_not_tracked_for_non_background(self):
        t = WorkflowTracker()
        wf_id = await t.begin("agent", {"question": "test"})
        assert t.get_active() == []
        await t.end(wf_id, "agent")

    @pytest.mark.asyncio
    async def test_get_active_returns_snapshot(self):
        t = WorkflowTracker()
        wf1 = await t.begin("index_repo", {"project_id": "p1"})
        wf2 = await t.begin("db_index", {"connection_id": "c1"})

        active = t.get_active()
        assert len(active) == 2
        ids = {w["workflow_id"] for w in active}
        assert wf1 in ids
        assert wf2 in ids

        await t.end(wf1, "index_repo")
        assert len(t.get_active()) == 1
        assert t.get_active()[0]["workflow_id"] == wf2

        await t.end(wf2, "db_index")
        assert t.get_active() == []

    @pytest.mark.asyncio
    async def test_active_workflow_stores_extra(self):
        t = WorkflowTracker()
        ctx = {"connection_id": "conn-abc", "project_id": "proj-def"}
        wf_id = await t.begin("db_index", ctx)
        active = t.get_active()
        assert active[0]["extra"] == ctx
        await t.end(wf_id, "db_index")

    @pytest.mark.asyncio
    async def test_step_events_carry_pipeline_for_background(self):
        t = WorkflowTracker()
        queue = t.subscribe()
        wf_id = await t.begin("index_repo", {"project_id": "p1"})
        queue.get_nowait()  # consume pipeline_start

        async with t.step(wf_id, "analyze_files", "Analyzing"):
            pass

        started = queue.get_nowait()
        assert started.pipeline == "index_repo"
        completed = queue.get_nowait()
        assert completed.pipeline == "index_repo"

        await t.end(wf_id, "index_repo")
        t.unsubscribe(queue)

    @pytest.mark.asyncio
    async def test_step_events_empty_pipeline_for_non_background(self):
        t = WorkflowTracker()
        queue = t.subscribe()
        wf_id = await t.begin("agent")
        queue.get_nowait()  # consume pipeline_start

        async with t.step(wf_id, "some_step"):
            pass

        started = queue.get_nowait()
        assert started.pipeline == ""

        await t.end(wf_id, "agent")
        t.unsubscribe(queue)

    @pytest.mark.asyncio
    async def test_emit_carries_pipeline_for_background(self):
        t = WorkflowTracker()
        queue = t.subscribe()
        wf_id = await t.begin("db_index", {"connection_id": "c1"})
        queue.get_nowait()

        await t.emit(wf_id, "progress", "started", "50%")
        event = queue.get_nowait()
        assert event.pipeline == "db_index"

        await t.end(wf_id, "db_index")
        t.unsubscribe(queue)
