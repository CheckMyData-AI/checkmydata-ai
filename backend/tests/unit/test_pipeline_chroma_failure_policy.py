"""C3 — vision §7 #3 (knowledge fidelity): the indexing pipeline must
distinguish ``Chroma reachable but collection empty`` (data corruption →
repair) from ``Chroma unreachable`` (transient infra → preserve state).

These tests target the C3 decision logic in
``PipelineRunner._run_indexing_workflow`` by reproducing its three branches
with lightweight fakes."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


@dataclass
class _State:
    last_sha: str | None = None
    changed_files: list[str] | None = None
    deleted_files: list[str] | None = None


def _evaluate_guard(
    *,
    force_full: bool,
    state: _State,
    vector_store: MagicMock,
    project_id: str,
    existing_docs: list,
) -> tuple[bool, str | None]:
    """Mirror of the C3 guard logic from pipeline_runner.py — extracted
    for testability. Returns ``(force_full, action)`` where action is one of
    ``None``, ``"repair_embeddings"``, ``"chroma_unreachable_warning"``."""
    if force_full or state.last_sha is None or state.changed_files or state.deleted_files:
        return force_full, None

    action: str | None = None
    try:
        col = vector_store.get_or_create_collection(project_id)
        col_count = col.count()
    except Exception:
        action = "chroma_unreachable_warning"
        col_count = None

    if col_count == 0 and existing_docs:
        action = "repair_embeddings"
        force_full = True

    return force_full, action


class TestC3FailurePolicy:
    def test_normal_empty_state_does_nothing(self):
        """Case 1: Chroma reachable, collection empty AND no docs in DB —
        normal initial state. Don't force_full, don't emit anything."""
        vs = MagicMock()
        vs.get_or_create_collection.return_value.count.return_value = 0

        force_full, action = _evaluate_guard(
            force_full=False,
            state=_State(last_sha="sha-1", changed_files=[], deleted_files=[]),
            vector_store=vs,
            project_id="p1",
            existing_docs=[],  # no docs in DB
        )

        assert force_full is False
        assert action is None

    def test_collection_empty_with_docs_triggers_repair(self):
        """Case 2: Chroma reachable, collection empty BUT docs in DB —
        data corruption. Force full re-index + emit repair_embeddings."""
        vs = MagicMock()
        vs.get_or_create_collection.return_value.count.return_value = 0

        force_full, action = _evaluate_guard(
            force_full=False,
            state=_State(last_sha="sha-1", changed_files=[], deleted_files=[]),
            vector_store=vs,
            project_id="p1",
            existing_docs=[MagicMock(), MagicMock()],
        )

        assert force_full is True
        assert action == "repair_embeddings"

    def test_chroma_unreachable_preserves_state(self):
        """Case 3: Chroma raises — do NOT force_full, do NOT null last_sha.
        Just warn so an operator sees the symptom."""
        vs = MagicMock()
        vs.get_or_create_collection.side_effect = ConnectionError("unreachable")

        state = _State(last_sha="sha-1", changed_files=[], deleted_files=[])
        force_full, action = _evaluate_guard(
            force_full=False,
            state=state,
            vector_store=vs,
            project_id="p1",
            existing_docs=[MagicMock()],
        )

        assert force_full is False
        assert action == "chroma_unreachable_warning"
        assert state.last_sha == "sha-1"

    def test_chroma_count_raises_preserves_state(self):
        """Count() raising must take the unreachable path, not the repair
        path. Defensive against transient flake."""
        vs = MagicMock()
        col = MagicMock()
        col.count.side_effect = TimeoutError("count timeout")
        vs.get_or_create_collection.return_value = col

        state = _State(last_sha="sha-1", changed_files=[], deleted_files=[])
        force_full, action = _evaluate_guard(
            force_full=False,
            state=state,
            vector_store=vs,
            project_id="p1",
            existing_docs=[MagicMock()],
        )

        assert force_full is False
        assert action == "chroma_unreachable_warning"

    def test_guard_skipped_when_force_full_already_set(self):
        vs = MagicMock()
        vs.get_or_create_collection.return_value.count.return_value = 0
        force_full, action = _evaluate_guard(
            force_full=True,
            state=_State(last_sha="sha-1", changed_files=[], deleted_files=[]),
            vector_store=vs,
            project_id="p1",
            existing_docs=[MagicMock()],
        )
        assert force_full is True
        assert action is None  # short-circuit: guard didn't run

    @pytest.mark.parametrize(
        "changed,deleted",
        [
            (["a.py"], []),
            ([], ["b.py"]),
            (["a.py"], ["b.py"]),
        ],
    )
    def test_guard_skipped_when_diff_nonempty(self, changed, deleted):
        """If there's already work to do, the guard doesn't run — Chroma
        health will be assessed downstream during the actual write."""
        vs = MagicMock()
        vs.get_or_create_collection.return_value.count.return_value = 0
        force_full, action = _evaluate_guard(
            force_full=False,
            state=_State(last_sha="sha-1", changed_files=changed, deleted_files=deleted),
            vector_store=vs,
            project_id="p1",
            existing_docs=[MagicMock()],
        )
        assert force_full is False
        assert action is None
