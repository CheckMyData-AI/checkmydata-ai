"""Tests for :class:`KnowledgeFreshnessService`."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.git_tracker import GitFreshness
from app.services.knowledge_freshness_service import (
    KnowledgeFreshness,
    KnowledgeFreshnessService,
)


class TestKnowledgeFreshness:
    def test_summary_none_when_clean(self):
        snap = KnowledgeFreshness(warnings=[])
        assert snap.to_summary() is None

    def test_summary_single_warning(self):
        snap = KnowledgeFreshness(warnings=["abc"])
        assert snap.to_summary() == "abc"

    def test_summary_multiple_warnings(self):
        snap = KnowledgeFreshness(warnings=["a", "b"])
        text = snap.to_summary()
        assert text is not None
        assert text.startswith("Knowledge freshness")
        assert "a" in text and "b" in text


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_no_connection_no_repo_returns_clean(self):
        svc = KnowledgeFreshnessService()
        snap = await svc.evaluate(
            session=AsyncMock(),
            project_id="p1",
            connection_id=None,
            repo_clone_dir=None,
        )
        assert snap.warnings == []

    @pytest.mark.asyncio
    async def test_db_index_stale_warning(self):
        svc = KnowledgeFreshnessService()
        with (
            patch("app.services.db_index_service.DbIndexService") as mock_db_cls,
            patch("app.services.code_db_sync_service.CodeDbSyncService") as mock_sync_cls,
        ):
            mock_db = mock_db_cls.return_value
            mock_db.get_index_age = AsyncMock(return_value=timedelta(hours=72))
            mock_sync = mock_sync_cls.return_value
            mock_sync.get_sync_status = AsyncMock(return_value="completed")

            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id="c1",
            )

        assert snap.db_index_stale is True
        assert any("Database index is" in w for w in snap.warnings)

    @pytest.mark.asyncio
    async def test_sync_stale_warning(self):
        svc = KnowledgeFreshnessService()
        with (
            patch("app.services.db_index_service.DbIndexService") as mock_db_cls,
            patch("app.services.code_db_sync_service.CodeDbSyncService") as mock_sync_cls,
        ):
            mock_db = mock_db_cls.return_value
            mock_db.get_index_age = AsyncMock(return_value=timedelta(hours=1))
            mock_sync = mock_sync_cls.return_value
            mock_sync.get_sync_status = AsyncMock(return_value="stale")

            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id="c1",
            )

        assert snap.sync_stale is True
        assert any("Code-database sync" in w for w in snap.warnings)

    @pytest.mark.asyncio
    async def test_db_check_failure_does_not_raise(self):
        svc = KnowledgeFreshnessService()
        mock_session = MagicMock()
        with patch("app.services.db_index_service.DbIndexService") as mock_db_cls:
            mock_db = mock_db_cls.return_value
            mock_db.get_index_age = AsyncMock(side_effect=RuntimeError("boom"))
            snap = await svc.evaluate(
                session=mock_session,
                project_id="p1",
                connection_id="c1",
            )
        # Failure is swallowed; returns whatever warnings accumulated.
        assert isinstance(snap, KnowledgeFreshness)

    @pytest.mark.asyncio
    async def test_code_graph_empty_warns_when_flag_on(self, monkeypatch):
        """M6: empty code graph emits a warning when code_graph_enabled is set."""
        from app import config as cfg_mod

        monkeypatch.setattr(cfg_mod.settings, "code_graph_enabled", True)
        svc = KnowledgeFreshnessService()
        with patch("app.services.code_graph_service.CodeGraphService") as mock_cg_cls:
            mock_cg = mock_cg_cls.return_value
            mock_cg.count = AsyncMock(return_value=(0, 0))
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
            )

        assert snap.code_graph_symbol_count == 0
        assert snap.code_graph_stale is True
        assert any("Code graph is empty" in w for w in snap.warnings)

    @pytest.mark.asyncio
    async def test_code_graph_silent_when_flag_off(self, monkeypatch):
        """No warning emitted when code_graph_enabled is False."""
        from app import config as cfg_mod

        monkeypatch.setattr(cfg_mod.settings, "code_graph_enabled", False)
        svc = KnowledgeFreshnessService()
        snap = await svc.evaluate(
            session=AsyncMock(),
            project_id="p1",
            connection_id=None,
        )
        assert snap.code_graph_stale is False
        assert not any("Code graph" in w for w in snap.warnings)

    @pytest.mark.asyncio
    async def test_git_classify_error_does_not_raise(self, tmp_path):
        """classify_freshness_async raising must not surface an error to the caller."""
        svc = KnowledgeFreshnessService()
        with patch("app.knowledge.git_tracker.GitTracker") as mock_tracker_cls:
            tracker = mock_tracker_cls.return_value
            tracker.get_last_indexed_sha = AsyncMock(return_value="oldsha")
            tracker.classify_freshness_async = AsyncMock(
                side_effect=RuntimeError("git classify failed")
            )
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
                repo_clone_dir=tmp_path,
            )
        assert snap.git_behind_commits is None
        assert not any("-1 commit" in w for w in snap.warnings)
        # Error is swallowed; no git warning should appear.
        assert isinstance(snap, KnowledgeFreshness)

    @pytest.mark.asyncio
    async def test_git_behind_reported_via_classify(self, tmp_path):
        """BEHIND state sets git_behind_commits and emits a 'BEHIND' warning."""
        svc = KnowledgeFreshnessService()
        with patch("app.knowledge.git_tracker.GitTracker") as mock_tracker_cls:
            mock_tracker_cls.return_value = _make_tracker_mock(
                last_sha="oldsha",
                freshness_result=(GitFreshness.BEHIND, 0, 3),
            )
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
                repo_clone_dir=tmp_path,
            )
        assert snap.git_behind_commits == 3
        assert any("3 commit(s) BEHIND" in w for w in snap.warnings)

    @pytest.mark.asyncio
    async def test_code_graph_populated_no_warning(self, monkeypatch):
        from app import config as cfg_mod

        monkeypatch.setattr(cfg_mod.settings, "code_graph_enabled", True)
        svc = KnowledgeFreshnessService()
        with patch("app.services.code_graph_service.CodeGraphService") as mock_cg_cls:
            mock_cg = mock_cg_cls.return_value
            mock_cg.count = AsyncMock(return_value=(123, 456))
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
            )

        assert snap.code_graph_symbol_count == 123
        assert snap.code_graph_stale is False


class TestCodeGraphGate:
    """SYNC-L8: empty-graph warning must be gated on lineage/clustering consumers."""

    @pytest.mark.asyncio
    async def test_no_codegraph_warning_when_only_code_graph_enabled(self, monkeypatch):
        """code_graph_enabled=True but both consumers off → no warning (false alarm)."""
        from app import config as cfg_mod

        monkeypatch.setattr(cfg_mod.settings, "code_graph_enabled", True)
        monkeypatch.setattr(cfg_mod.settings, "lineage_enabled", False)
        monkeypatch.setattr(cfg_mod.settings, "clustering_enabled", False)
        svc = KnowledgeFreshnessService()
        with patch("app.services.code_graph_service.CodeGraphService") as mock_cg_cls:
            mock_cg = mock_cg_cls.return_value
            mock_cg.count = AsyncMock(return_value=(0, 0))
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
            )

        assert snap.code_graph_stale is False
        assert not any("code_graph" in str(getattr(d, "category", "")) for d in snap.details)
        assert not any("Code graph is empty" in w for w in snap.warnings)

    @pytest.mark.asyncio
    async def test_codegraph_warning_when_lineage_enabled(self, monkeypatch):
        """lineage_enabled=True + empty graph → warning fires."""
        from app import config as cfg_mod

        monkeypatch.setattr(cfg_mod.settings, "code_graph_enabled", True)
        monkeypatch.setattr(cfg_mod.settings, "lineage_enabled", True)
        monkeypatch.setattr(cfg_mod.settings, "clustering_enabled", False)
        svc = KnowledgeFreshnessService()
        with patch("app.services.code_graph_service.CodeGraphService") as mock_cg_cls:
            mock_cg = mock_cg_cls.return_value
            mock_cg.count = AsyncMock(return_value=(0, 0))
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
            )

        assert snap.code_graph_stale is True
        assert snap.code_graph_symbol_count == 0
        assert any("Code graph is empty" in w for w in snap.warnings)

    @pytest.mark.asyncio
    async def test_codegraph_warning_when_clustering_enabled(self, monkeypatch):
        """clustering_enabled=True + empty graph → warning fires."""
        from app import config as cfg_mod

        monkeypatch.setattr(cfg_mod.settings, "code_graph_enabled", True)
        monkeypatch.setattr(cfg_mod.settings, "lineage_enabled", False)
        monkeypatch.setattr(cfg_mod.settings, "clustering_enabled", True)
        svc = KnowledgeFreshnessService()
        with patch("app.services.code_graph_service.CodeGraphService") as mock_cg_cls:
            mock_cg = mock_cg_cls.return_value
            mock_cg.count = AsyncMock(return_value=(0, 0))
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
            )

        assert snap.code_graph_stale is True
        assert snap.code_graph_symbol_count == 0
        assert any("Code graph is empty" in w for w in snap.warnings)


def _make_tracker_mock(
    last_sha: str | None,
    freshness_result: tuple[GitFreshness, int, int] | None = None,
) -> MagicMock:
    """Build a GitTracker mock that uses classify_freshness_async."""
    tracker = MagicMock()
    tracker.get_last_indexed_sha = AsyncMock(return_value=last_sha)
    if freshness_result is not None:
        tracker.classify_freshness_async = AsyncMock(return_value=freshness_result)
    return tracker


class TestGitFreshnessPerState:
    """T2: knowledge_freshness_service distinguishes FRESH/AHEAD/BEHIND/DIVERGED.

    Each test mocks ``GitTracker.classify_freshness_async`` to return a
    specific ``(GitFreshness, ahead, behind)`` tuple and asserts the service
    emits the correct distinct warning text (or no warning for FRESH).
    """

    @pytest.mark.asyncio
    async def test_fresh_emits_no_git_warning(self, tmp_path: Path) -> None:
        """FRESH state → no git warning; snapshot is clean."""
        svc = KnowledgeFreshnessService()
        with patch("app.knowledge.git_tracker.GitTracker") as mock_cls:
            mock_cls.return_value = _make_tracker_mock(
                last_sha="abc123",
                freshness_result=(GitFreshness.FRESH, 0, 0),
            )
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
                repo_clone_dir=tmp_path,
            )

        git_warnings = [
            w
            for w in snap.warnings
            if "commit" in w.lower()
            or "ahead" in w.lower()
            or "behind" in w.lower()
            or "diverged" in w.lower()
        ]
        assert git_warnings == [], f"Expected no git warning for FRESH, got: {git_warnings}"
        assert snap.git_behind_commits is None

    @pytest.mark.asyncio
    async def test_ahead_emits_reindex_recommended_warning(self, tmp_path: Path) -> None:
        """AHEAD n → warning mentions clone is n commits AHEAD + re-index recommended."""
        svc = KnowledgeFreshnessService()
        with patch("app.knowledge.git_tracker.GitTracker") as mock_cls:
            mock_cls.return_value = _make_tracker_mock(
                last_sha="abc123",
                freshness_result=(GitFreshness.AHEAD, 5, 0),
            )
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
                repo_clone_dir=tmp_path,
            )

        git_warnings = [w for w in snap.warnings if "ahead" in w.lower()]
        assert git_warnings, "Expected an AHEAD warning"
        warning = git_warnings[0]
        assert "5" in warning, f"Expected commit count 5 in warning: {warning!r}"
        assert "ahead" in warning.lower(), f"Expected 'ahead' in warning: {warning!r}"
        assert "re-index" in warning.lower() or "reindex" in warning.lower(), (
            f"Expected re-index recommendation in warning: {warning!r}"
        )

    @pytest.mark.asyncio
    async def test_behind_emits_pull_warning(self, tmp_path: Path) -> None:
        """BEHIND n → warning mentions n commits BEHIND + pull before trusting."""
        svc = KnowledgeFreshnessService()
        with patch("app.knowledge.git_tracker.GitTracker") as mock_cls:
            mock_cls.return_value = _make_tracker_mock(
                last_sha="abc123",
                freshness_result=(GitFreshness.BEHIND, 0, 7),
            )
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
                repo_clone_dir=tmp_path,
            )

        git_warnings = [w for w in snap.warnings if "behind" in w.lower()]
        assert git_warnings, "Expected a BEHIND warning"
        warning = git_warnings[0]
        assert "7" in warning, f"Expected commit count 7 in warning: {warning!r}"
        assert "behind" in warning.lower(), f"Expected 'behind' in warning: {warning!r}"
        assert "pull" in warning.lower(), f"Expected 'pull' in warning: {warning!r}"

    @pytest.mark.asyncio
    async def test_diverged_emits_explicit_diverged_warning(self, tmp_path: Path) -> None:
        """DIVERGED → explicit warning mentioning diverged with both ahead/behind counts."""
        svc = KnowledgeFreshnessService()
        with patch("app.knowledge.git_tracker.GitTracker") as mock_cls:
            mock_cls.return_value = _make_tracker_mock(
                last_sha="abc123",
                freshness_result=(GitFreshness.DIVERGED, 3, 4),
            )
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
                repo_clone_dir=tmp_path,
            )

        git_warnings = [w for w in snap.warnings if "diverged" in w.lower()]
        assert git_warnings, "Expected a DIVERGED warning"
        warning = git_warnings[0]
        assert "3" in warning, f"Expected ahead count 3 in diverged warning: {warning!r}"
        assert "4" in warning, f"Expected behind count 4 in diverged warning: {warning!r}"

    @pytest.mark.asyncio
    async def test_unindexed_repo_emits_not_indexed_warning(self, tmp_path: Path) -> None:
        """No last_sha → 'not been indexed yet' warning (unchanged behavior)."""
        svc = KnowledgeFreshnessService()
        with patch("app.knowledge.git_tracker.GitTracker") as mock_cls:
            mock_cls.return_value = _make_tracker_mock(last_sha=None)
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
                repo_clone_dir=tmp_path,
            )

        assert any("not been indexed" in w for w in snap.warnings)

    @pytest.mark.asyncio
    async def test_classify_freshness_error_does_not_raise(self, tmp_path: Path) -> None:
        """If classify_freshness_async raises, the service degrades gracefully."""
        svc = KnowledgeFreshnessService()
        with patch("app.knowledge.git_tracker.GitTracker") as mock_cls:
            tracker = MagicMock()
            tracker.get_last_indexed_sha = AsyncMock(return_value="abc123")
            tracker.classify_freshness_async = AsyncMock(side_effect=RuntimeError("git exploded"))
            mock_cls.return_value = tracker
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
                repo_clone_dir=tmp_path,
            )

        assert isinstance(snap, KnowledgeFreshness)  # no exception propagated
