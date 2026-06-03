"""Tests for :class:`KnowledgeFreshnessService`."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    async def test_git_count_error_does_not_report_negative_behind(self, tmp_path):
        """count_commits_ahead returning -1 must not surface a '-1 commits behind'."""
        svc = KnowledgeFreshnessService()
        with patch("app.knowledge.git_tracker.GitTracker") as mock_tracker_cls:
            tracker = mock_tracker_cls.return_value
            tracker.get_last_indexed_sha = AsyncMock(return_value="oldsha")
            tracker.get_head_sha = MagicMock(return_value="newsha")
            tracker.count_commits_ahead = AsyncMock(return_value=-1)
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
                repo_clone_dir=tmp_path,
            )
        assert snap.git_behind_commits is None
        assert not any("-1 commit" in w for w in snap.warnings)
        assert any("may be out of date" in w for w in snap.warnings)

    @pytest.mark.asyncio
    async def test_git_positive_behind_reported(self, tmp_path):
        svc = KnowledgeFreshnessService()
        with patch("app.knowledge.git_tracker.GitTracker") as mock_tracker_cls:
            tracker = mock_tracker_cls.return_value
            tracker.get_last_indexed_sha = AsyncMock(return_value="oldsha")
            tracker.get_head_sha = MagicMock(return_value="newsha")
            tracker.count_commits_ahead = AsyncMock(return_value=3)
            snap = await svc.evaluate(
                session=AsyncMock(),
                project_id="p1",
                connection_id=None,
                repo_clone_dir=tmp_path,
            )
        assert snap.git_behind_commits == 3
        assert any("3 commit(s) behind" in w for w in snap.warnings)

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
