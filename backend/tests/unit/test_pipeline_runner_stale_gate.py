"""Unit tests for IndexingPipelineRunner._maybe_mark_stale — stale-marking gate."""

from unittest.mock import AsyncMock

from app.knowledge.pipeline_runner import IndexingPipelineRunner, _PipelineState


async def test_no_change_does_not_mark_stale():
    runner = IndexingPipelineRunner.__new__(IndexingPipelineRunner)
    runner._mark_db_index_code_stale = AsyncMock()
    runner._mark_sync_stale = AsyncMock()
    state = _PipelineState()
    state.changed_files = []
    state.deleted_files = []

    await runner._maybe_mark_stale(db=None, project_id="p", state=state)
    runner._mark_db_index_code_stale.assert_not_called()
    runner._mark_sync_stale.assert_not_called()


async def test_changed_files_marks_stale():
    runner = IndexingPipelineRunner.__new__(IndexingPipelineRunner)
    runner._mark_db_index_code_stale = AsyncMock()
    runner._mark_sync_stale = AsyncMock()
    state = _PipelineState()
    state.changed_files = ["a.py"]
    state.deleted_files = []

    await runner._maybe_mark_stale(db=None, project_id="p", state=state)
    runner._mark_db_index_code_stale.assert_awaited_once()
    runner._mark_sync_stale.assert_awaited_once()


async def test_deleted_files_marks_stale():
    runner = IndexingPipelineRunner.__new__(IndexingPipelineRunner)
    runner._mark_db_index_code_stale = AsyncMock()
    runner._mark_sync_stale = AsyncMock()
    state = _PipelineState()
    state.changed_files = []
    state.deleted_files = ["b.py"]

    await runner._maybe_mark_stale(db=None, project_id="p", state=state)
    runner._mark_db_index_code_stale.assert_awaited_once()
    runner._mark_sync_stale.assert_awaited_once()
