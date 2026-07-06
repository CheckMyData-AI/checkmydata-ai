"""Tests for KnowledgeFreshnessService and KnowledgeFreshness dataclass."""

from app.services.knowledge_freshness_service import KnowledgeFreshness


class TestKnowledgeFreshnessDataclass:
    """Test KnowledgeFreshness dataclass construction and properties."""

    def test_default_construction(self):
        """KnowledgeFreshness() with no args has warnings == [] and overall_stale is False."""
        freshness = KnowledgeFreshness()
        assert freshness.warnings == []
        assert freshness.overall_stale is False

    def test_sync_failed_flag(self):
        """A failed sync sets sync_failed=True."""
        freshness = KnowledgeFreshness(sync_status="failed", sync_failed=True)
        assert freshness.sync_status == "failed"
        assert freshness.sync_failed is True

    def test_sync_stale_flag(self):
        """A stale sync sets sync_stale=True but sync_failed=False."""
        freshness = KnowledgeFreshness(sync_status="stale", sync_stale=True)
        assert freshness.sync_status == "stale"
        assert freshness.sync_stale is True
        assert freshness.sync_failed is False

    def test_sync_ok_flag(self):
        """A fresh sync (OK) sets both sync_stale and sync_failed to False."""
        freshness = KnowledgeFreshness(sync_status="ok")
        assert freshness.sync_status == "ok"
        assert freshness.sync_stale is False
        assert freshness.sync_failed is False


# ---------------------------------------------------------------------------
# L14 — DB_INDEX_TTL_HOURS must honour settings.db_index_ttl_hours
# ---------------------------------------------------------------------------


class TestKnowledgeFreshnessServiceTTL:
    """L14: the DB-index TTL must be driven by settings.db_index_ttl_hours."""

    async def test_ttl_read_from_settings(self, monkeypatch):
        """Monkeypatching settings.db_index_ttl_hours to 1 makes a 2h-old index stale."""
        from datetime import timedelta
        from unittest.mock import AsyncMock, MagicMock

        import app.services.knowledge_freshness_service as _mod

        # Patch the module-level settings object (now imported at top of module).
        monkeypatch.setattr(_mod.settings, "db_index_ttl_hours", 1)
        monkeypatch.setattr(_mod.settings, "lineage_enabled", False)
        monkeypatch.setattr(_mod.settings, "clustering_enabled", False)

        # Fake out inner service calls so no real DB is needed.
        db_svc_instance = MagicMock()
        db_svc_instance.get_index_age = AsyncMock(return_value=timedelta(hours=2))
        sync_svc_instance = MagicMock()
        sync_svc_instance.get_sync_status = AsyncMock(return_value="ok")

        monkeypatch.setattr(
            "app.services.db_index_service.DbIndexService",
            lambda: db_svc_instance,
        )
        monkeypatch.setattr(
            "app.services.code_db_sync_service.CodeDbSyncService",
            lambda: sync_svc_instance,
        )

        svc = _mod.KnowledgeFreshnessService()
        result = await svc.evaluate(
            MagicMock(),
            project_id="proj-1",
            connection_id="conn-1",
        )
        # With TTL=1h and index age=2h the index should be flagged stale.
        assert result.db_index_stale is True
