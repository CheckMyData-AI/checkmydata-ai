"""Unit tests for the incremental graph-build guard (R3-3).

An incremental build that produces zero symbols for files that *changed*
(not merely deleted) is almost certainly a parse failure. Persisting it would
treat those files as deletions and purge their known symbols, so the runner
must skip the merge and keep the last-good graph.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.code_graph import CodeGraph
from app.knowledge.pipeline_runner import IndexingPipelineRunner, _PipelineState


def _runner() -> IndexingPipelineRunner:
    # _run_graph_build does not touch any constructor dependency.
    return IndexingPipelineRunner(
        ssh_key_svc=None,
        git_tracker=None,
        repo_analyzer=None,
        doc_store=None,
        doc_generator=None,
        vector_store=None,
        cache_svc=None,
        checkpoint_svc=None,
    )


@pytest.mark.asyncio
async def test_incremental_empty_graph_with_changed_files_skips_merge():
    runner = _runner()
    state = _PipelineState()
    state.parsed_files = {}  # builder will produce an empty graph
    state.changed_files = ["a.py"]
    state.deleted_files = []

    mock_svc = MagicMock()
    mock_svc.save_incremental = AsyncMock()
    mock_svc.save = AsyncMock()
    mock_svc.load_graph = AsyncMock(return_value=CodeGraph(symbols=[], edges=[]))

    with (
        patch("app.knowledge.pipeline_runner.CodeGraphService", return_value=mock_svc),
        patch("app.knowledge.pipeline_runner.tracker") as mock_tracker,
    ):
        mock_tracker.emit = AsyncMock()
        await runner._run_graph_build(state, "wf-1", db=MagicMock(), project_id="p1", is_full=False)

    mock_svc.save_incremental.assert_not_called()
    mock_svc.save.assert_not_called()
    # A "skipped" status must be surfaced.
    statuses = [c.args[2] for c in mock_tracker.emit.await_args_list if len(c.args) >= 3]
    assert "skipped" in statuses


@pytest.mark.asyncio
async def test_incremental_empty_graph_pure_deletion_still_merges():
    """No changed files (only deletions) ⇒ an empty graph is legitimate and
    the merge must run so deleted files are purged."""
    runner = _runner()
    state = _PipelineState()
    state.parsed_files = {}
    state.changed_files = []
    state.deleted_files = ["gone.py"]

    mock_svc = MagicMock()
    mock_svc.save_incremental = AsyncMock(return_value=(0, 0))
    mock_svc.load_graph = AsyncMock(return_value=CodeGraph(symbols=[], edges=[]))

    with (
        patch("app.knowledge.pipeline_runner.CodeGraphService", return_value=mock_svc),
        patch("app.knowledge.pipeline_runner.tracker") as mock_tracker,
    ):
        mock_tracker.emit = AsyncMock()
        await runner._run_graph_build(state, "wf-1", db=MagicMock(), project_id="p1", is_full=False)

    mock_svc.save_incremental.assert_awaited_once()
    args = mock_svc.save_incremental.await_args.args
    # affected_files (4th positional) should contain the deleted file.
    assert "gone.py" in args[3]
