"""Tests for embedding mismatch detection and reindex path (CODEIDX-C1).

Covers:
- ``_get_embedding_function`` logs a WARNING when ``embedder_max_tokens`` (config)
  disagrees with the model's ``max_seq_length`` (loaded model).
- No warning when they match.
- Startup check swallows all errors and never raises.
- ``queue_embedding_reindex`` deletes each project's Chroma collection and
  enqueues ``run_repo_index`` (force_full=True) for each project_id.
- ``queue_embedding_reindex`` with an empty list is a no-op.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_MODEL = "fake/model-xyz"


def _make_ef_mock(max_seq_length: int) -> MagicMock:
    """Return a mock that looks like SentenceTransformerEmbeddingFunction."""
    ef = MagicMock()
    ef._model = MagicMock()
    ef._model.max_seq_length = max_seq_length
    return ef


# ---------------------------------------------------------------------------
# Mismatch detection in _get_embedding_function
# ---------------------------------------------------------------------------


class TestEmbeddingWindowMismatchWarning:
    """_get_embedding_function warns when configured window ≠ model's seq length."""

    def _call_with_model(
        self,
        model_max_seq: int,
        configured_max: int,
    ) -> tuple[MagicMock | None, list]:
        """Call _get_embedding_function with patched settings + model, collect logs."""
        from app.knowledge.vector_store import _get_embedding_function

        ef_mock = _make_ef_mock(model_max_seq)

        with (
            patch("app.knowledge.vector_store.settings") as mock_settings,
            patch(
                "app.knowledge.vector_store._sentence_transformers_available",
                return_value=True,
            ),
            patch(
                "app.knowledge.vector_store.SentenceTransformerEmbeddingFunction",
                return_value=ef_mock,
            ),
        ):
            mock_settings.chroma_embedding_model = _FAKE_MODEL
            mock_settings.embedder_max_tokens = configured_max

            with patch("app.knowledge.vector_store.logger") as mock_logger:
                result = _get_embedding_function()
                return result, mock_logger.warning.call_args_list

    def test_mismatch_logs_warning(self) -> None:
        """Model window 256, config says 512 → warning logged."""
        _ef, warnings = self._call_with_model(model_max_seq=256, configured_max=512)
        assert len(warnings) == 1, f"Expected 1 warning, got {len(warnings)}: {warnings}"
        msg = str(warnings[0])
        assert "mismatch" in msg.lower() or "stale" in msg.lower() or "reindex" in msg.lower()

    def test_match_no_warning(self) -> None:
        """Model window 512, config says 512 → no mismatch warning."""
        _ef, warnings = self._call_with_model(model_max_seq=512, configured_max=512)
        assert len(warnings) == 0, f"Expected no warnings, got: {warnings}"

    def test_no_model_no_warning(self) -> None:
        """No model configured → returns None, no mismatch warning."""
        from app.knowledge.vector_store import _get_embedding_function

        with patch("app.knowledge.vector_store.settings") as mock_settings:
            mock_settings.chroma_embedding_model = ""
            mock_settings.embedder_max_tokens = 512

            with patch("app.knowledge.vector_store.logger") as mock_logger:
                result = _get_embedding_function()
                assert result is None
                mock_logger.warning.assert_not_called()

    def test_model_load_failure_swallowed(self) -> None:
        """If the model can't be loaded at all, no crash — graceful degradation."""
        from app.knowledge.vector_store import _get_embedding_function

        with (
            patch("app.knowledge.vector_store.settings") as mock_settings,
            patch(
                "app.knowledge.vector_store.SentenceTransformerEmbeddingFunction",
                side_effect=RuntimeError("no network"),
            ),
        ):
            mock_settings.chroma_embedding_model = _FAKE_MODEL
            mock_settings.embedder_max_tokens = 512

            # Must not raise
            result = _get_embedding_function()
            assert result is None

    def test_max_seq_length_missing_no_crash(self) -> None:
        """If _model has no max_seq_length attribute, swallow and do not warn."""
        from app.knowledge.vector_store import _get_embedding_function

        ef_mock = MagicMock()
        # Remove max_seq_length so AttributeError is raised on access
        del ef_mock._model.max_seq_length

        with (
            patch("app.knowledge.vector_store.settings") as mock_settings,
            patch(
                "app.knowledge.vector_store._sentence_transformers_available",
                return_value=True,
            ),
            patch(
                "app.knowledge.vector_store.SentenceTransformerEmbeddingFunction",
                return_value=ef_mock,
            ),
        ):
            mock_settings.chroma_embedding_model = _FAKE_MODEL
            mock_settings.embedder_max_tokens = 512

            with patch("app.knowledge.vector_store.logger"):
                result = _get_embedding_function()
                assert result is ef_mock  # still returns EF even if check fails


# ---------------------------------------------------------------------------
# queue_embedding_reindex
# ---------------------------------------------------------------------------


class TestQueueEmbeddingReindex:
    """queue_embedding_reindex drops collections and enqueues run_repo_index."""

    @pytest.fixture()
    def project_ids(self) -> list[str]:
        return [str(uuid.uuid4()) for _ in range(3)]

    @pytest.mark.asyncio
    async def test_enqueues_run_repo_index_for_each_project(self, project_ids: list[str]) -> None:
        from app.services.embedding_reindex import queue_embedding_reindex

        mock_vs = MagicMock()
        mock_enqueue = AsyncMock(return_value="job-123")

        with (
            patch("app.services.embedding_reindex.VectorStore", return_value=mock_vs),
            patch("app.services.embedding_reindex.enqueue", mock_enqueue),
        ):
            results = await queue_embedding_reindex(project_ids)

        # delete_collection called once per project
        assert mock_vs.delete_collection.call_count == len(project_ids)
        for pid in project_ids:
            mock_vs.delete_collection.assert_any_call(pid)

        # enqueue called once per project with correct args
        assert mock_enqueue.call_count == len(project_ids)
        for pid in project_ids:
            mock_enqueue.assert_any_call(
                "run_repo_index",
                project_id=pid,
                force_full=True,
            )

        assert len(results) == len(project_ids)

    @pytest.mark.asyncio
    async def test_empty_list_is_noop(self) -> None:
        from app.services.embedding_reindex import queue_embedding_reindex

        mock_vs = MagicMock()
        mock_enqueue = AsyncMock()

        with (
            patch("app.services.embedding_reindex.VectorStore", return_value=mock_vs),
            patch("app.services.embedding_reindex.enqueue", mock_enqueue),
        ):
            results = await queue_embedding_reindex([])

        mock_vs.delete_collection.assert_not_called()
        mock_enqueue.assert_not_called()
        assert results == []

    @pytest.mark.asyncio
    async def test_delete_failure_does_not_abort_remaining(self, project_ids: list[str]) -> None:
        """If delete_collection fails for one project, still enqueue the rest."""
        from app.services.embedding_reindex import queue_embedding_reindex

        mock_vs = MagicMock()
        # Fail on the first project's delete
        first_pid = project_ids[0]
        mock_vs.delete_collection.side_effect = lambda pid: (
            (_ for _ in ()).throw(RuntimeError("chroma down")) if pid == first_pid else None
        )
        mock_enqueue = AsyncMock(return_value="job-id")

        with (
            patch("app.services.embedding_reindex.VectorStore", return_value=mock_vs),
            patch("app.services.embedding_reindex.enqueue", mock_enqueue),
        ):
            results = await queue_embedding_reindex(project_ids)

        # All projects attempted for enqueue regardless of delete failure
        assert mock_enqueue.call_count == len(project_ids)
        assert len(results) == len(project_ids)

    @pytest.mark.asyncio
    async def test_returns_job_ids(self, project_ids: list[str]) -> None:
        from app.services.embedding_reindex import queue_embedding_reindex

        mock_vs = MagicMock()
        job_counter = [0]

        async def _fake_enqueue(task_name: str, *, project_id: str, force_full: bool) -> str:
            job_counter[0] += 1
            return f"job-{job_counter[0]}"

        with (
            patch("app.services.embedding_reindex.VectorStore", return_value=mock_vs),
            patch("app.services.embedding_reindex.enqueue", side_effect=_fake_enqueue),
        ):
            results = await queue_embedding_reindex(project_ids)

        assert len(results) == len(project_ids)
        for r in results:
            assert r is not None
