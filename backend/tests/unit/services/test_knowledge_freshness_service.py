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
