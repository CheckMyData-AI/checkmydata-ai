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
