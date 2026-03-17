"""Tests for CheckpointService CRUD operations."""

import json

from app.models.indexing_checkpoint import IndexingCheckpoint
from app.services.checkpoint_service import (
    CheckpointService,
    _safe_json_loads_list,
    _safe_json_loads_set,
)


class TestCheckpointService:
    def _make_cp(self, **overrides) -> IndexingCheckpoint:
        defaults = dict(
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

    def test_get_completed_steps_empty(self):
        cp = self._make_cp()
        assert CheckpointService.get_completed_steps(cp) == set()

    def test_get_completed_steps_with_data(self):
        cp = self._make_cp(completed_steps='["clone_or_pull", "detect_changes"]')
        assert CheckpointService.get_completed_steps(cp) == {"clone_or_pull", "detect_changes"}

    def test_get_processed_doc_paths(self):
        cp = self._make_cp(processed_doc_paths='["a.py", "b.py"]')
        assert CheckpointService.get_processed_doc_paths(cp) == {"a.py", "b.py"}

    def test_get_changed_files(self):
        cp = self._make_cp(changed_files_json='["x.py"]')
        assert CheckpointService.get_changed_files(cp) == ["x.py"]

    def test_get_deleted_files(self):
        cp = self._make_cp(deleted_files_json='["old.py"]')
        assert CheckpointService.get_deleted_files(cp) == ["old.py"]

    def test_make_helper_provides_valid_defaults(self):
        cp = self._make_cp()
        assert cp.status == "running"
        assert json.loads(cp.completed_steps) == []
        assert json.loads(cp.processed_doc_paths) == []
        assert cp.total_docs == 0
        assert cp.error_detail is None
        assert cp.failed_step is None


class TestSafeJsonHelpers:
    def test_safe_json_loads_list_valid(self):
        assert _safe_json_loads_list('["a", "b"]') == ["a", "b"]

    def test_safe_json_loads_list_empty(self):
        assert _safe_json_loads_list("[]") == []

    def test_safe_json_loads_list_corrupted(self):
        assert _safe_json_loads_list("{corrupted") == []

    def test_safe_json_loads_list_non_list_json(self):
        assert _safe_json_loads_list('{"key": "val"}') == []

    def test_safe_json_loads_list_none_input(self):
        assert _safe_json_loads_list(None) == []

    def test_safe_json_loads_set_valid(self):
        assert _safe_json_loads_set('["a", "b", "a"]') == {"a", "b"}

    def test_safe_json_loads_set_corrupted(self):
        assert _safe_json_loads_set("not json") == set()

    def test_completed_steps_corrupted_returns_empty(self):
        cp = IndexingCheckpoint(
            project_id="p",
            workflow_id="w",
            head_sha="h",
            status="running",
            completed_steps="CORRUPTED",
            changed_files_json="[]",
            deleted_files_json="[]",
            profile_json="{}",
            knowledge_json="{}",
            processed_doc_paths="[]",
            total_docs=0,
        )
        assert CheckpointService.get_completed_steps(cp) == set()

    def test_processed_doc_paths_corrupted_returns_empty(self):
        cp = IndexingCheckpoint(
            project_id="p",
            workflow_id="w",
            head_sha="h",
            status="running",
            completed_steps="[]",
            changed_files_json="[]",
            deleted_files_json="[]",
            profile_json="{}",
            knowledge_json="{}",
            processed_doc_paths="CORRUPTED",
            total_docs=0,
        )
        assert CheckpointService.get_processed_doc_paths(cp) == set()
