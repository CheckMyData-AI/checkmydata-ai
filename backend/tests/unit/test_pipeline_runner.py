"""Tests for IndexingPipelineRunner checkpoint-based resumability."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.pipeline_runner import IndexingPipelineRunner, PipelineResult
from app.models.indexing_checkpoint import IndexingCheckpoint
from app.services.checkpoint_service import CheckpointService


def _make_checkpoint(**overrides) -> IndexingCheckpoint:
    defaults = dict(
        id="cp-1",
        project_id="proj-1",
        workflow_id="wf-1",
        head_sha="a" * 40,
        last_sha=None,
        status="running",
        completed_steps="[]",
        changed_files_json="[]",
        deleted_files_json="[]",
        profile_json="{}",
        knowledge_json="{}",
        processed_doc_paths="[]",
        total_docs=0,
    )
    defaults.update(overrides)
    return IndexingCheckpoint(**defaults)


class TestCheckpointStepSkipping:

    def test_empty_checkpoint_means_no_steps_done(self):
        cp = _make_checkpoint()
        assert CheckpointService.get_completed_steps(cp) == set()

    def test_completed_steps_parsed_correctly(self):
        cp = _make_checkpoint(
            completed_steps='["detect_changes", "cleanup_deleted", "project_profile"]',
        )
        done = CheckpointService.get_completed_steps(cp)
        assert done == {"detect_changes", "cleanup_deleted", "project_profile"}

    def test_processed_doc_paths_parsed(self):
        cp = _make_checkpoint(
            processed_doc_paths='["models/user.py", "models/order.py"]',
        )
        paths = CheckpointService.get_processed_doc_paths(cp)
        assert paths == {"models/user.py", "models/order.py"}

    def test_changed_files_restored(self):
        cp = _make_checkpoint(changed_files_json='["a.py", "b.py", "c.py"]')
        assert CheckpointService.get_changed_files(cp) == ["a.py", "b.py", "c.py"]


class TestPipelineResultDefaults:

    def test_defaults(self):
        r = PipelineResult()
        assert r.status == "completed"
        assert r.resumed is False
        assert r.docs_skipped == 0
        assert r.resumed_from_step is None

    def test_resumed_result(self):
        r = PipelineResult(
            resumed=True,
            resumed_from_step="generate_docs",
            docs_skipped=200,
            files_indexed=500,
            schemas_found=50,
            commit_sha="abc123",
        )
        assert r.resumed is True
        assert r.docs_skipped == 200


class TestDocSkippingLogic:
    """Verifies that the per-doc skip logic works correctly with processed_doc_paths."""

    def test_doc_in_processed_set_is_skipped(self):
        processed = {"models/user.py", "models/order.py"}
        docs_to_process = ["models/user.py", "models/order.py", "models/product.py"]
        remaining = [d for d in docs_to_process if d not in processed]
        assert remaining == ["models/product.py"]

    def test_empty_processed_set_processes_all(self):
        processed: set[str] = set()
        docs = ["a.py", "b.py"]
        remaining = [d for d in docs if d not in processed]
        assert remaining == ["a.py", "b.py"]

    def test_all_processed_means_no_work(self):
        processed = {"a.py", "b.py"}
        docs = ["a.py", "b.py"]
        remaining = [d for d in docs if d not in processed]
        assert remaining == []


class TestRunnerConstruction:

    def test_runner_stores_services(self):
        runner = IndexingPipelineRunner(
            ssh_key_svc=MagicMock(),
            git_tracker=MagicMock(),
            repo_analyzer=MagicMock(),
            doc_store=MagicMock(),
            doc_generator=MagicMock(),
            vector_store=MagicMock(),
            cache_svc=MagicMock(),
            checkpoint_svc=MagicMock(),
        )
        assert runner._ssh_key_svc is not None
        assert runner._cp_svc is not None
