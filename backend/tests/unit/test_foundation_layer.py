"""Tests for the foundation layer: Data Graph, Insight Memory, and Trust Layer."""

from unittest.mock import AsyncMock

import pytest

from app.core.data_graph import VALID_RELATIONSHIP_TYPES, DataGraphService
from app.core.insight_memory import VALID_INSIGHT_TYPES, InsightMemoryService
from app.core.trust_layer import TrustedInsight, TrustService


class TestTrustService:
    """Tests for the Trust Layer."""

    def test_compute_confidence_base(self):
        score = TrustService.compute_confidence(base_confidence=0.5)
        assert score == 0.5

    def test_compute_confidence_high_data_points(self):
        score = TrustService.compute_confidence(base_confidence=0.5, data_points=200)
        assert score == 0.6

    def test_compute_confidence_multiple_sources(self):
        score = TrustService.compute_confidence(base_confidence=0.5, sources_count=3)
        assert score == 0.6

    def test_compute_confidence_cross_validated(self):
        score = TrustService.compute_confidence(base_confidence=0.5, is_cross_validated=True)
        assert score == 0.65

    def test_compute_confidence_user_confirmations(self):
        score = TrustService.compute_confidence(base_confidence=0.5, user_confirmations=2)
        assert score == 0.7

    def test_compute_confidence_user_dismissals(self):
        score = TrustService.compute_confidence(base_confidence=0.5, user_dismissals=2)
        assert score == 0.2

    def test_compute_confidence_stale_data(self):
        score = TrustService.compute_confidence(base_confidence=0.5, data_freshness_hours=200)
        assert score == 0.4

    def test_compute_confidence_moderately_stale_data(self):
        score = TrustService.compute_confidence(base_confidence=0.5, data_freshness_hours=48)
        assert score == 0.45

    def test_compute_confidence_moderate_data_points(self):
        score = TrustService.compute_confidence(base_confidence=0.5, data_points=50)
        assert score == 0.55

    def test_compute_confidence_two_sources(self):
        score = TrustService.compute_confidence(base_confidence=0.5, sources_count=2)
        assert score == 0.55

    def test_compute_confidence_clamped(self):
        score = TrustService.compute_confidence(
            base_confidence=0.9,
            data_points=200,
            sources_count=5,
            is_cross_validated=True,
            user_confirmations=5,
        )
        assert score == 1.0

    def test_compute_confidence_clamped_low(self):
        score = TrustService.compute_confidence(base_confidence=0.1, user_dismissals=5)
        assert score == 0.0

    def test_build_trusted_insight(self):
        ti = TrustService.build_trusted_insight(
            insight_id="ins-1",
            title="Revenue dropped",
            description="Revenue fell 20%",
            insight_type="anomaly",
            severity="warning",
            confidence=0.75,
            sources=["stripe", "db"],
        )
        assert isinstance(ti, TrustedInsight)
        assert ti.confidence_label == "medium"
        assert ti.insight_id == "ins-1"
        assert len(ti.sources) == 2

    def test_trusted_insight_high_confidence(self):
        ti = TrustService.build_trusted_insight(
            insight_id="ins-2",
            title="Test",
            description="Desc",
            insight_type="trend",
            severity="info",
            confidence=0.9,
        )
        assert ti.confidence_label == "high"

    def test_trusted_insight_low_confidence(self):
        ti = TrustService.build_trusted_insight(
            insight_id="ins-3",
            title="Test",
            description="Desc",
            insight_type="trend",
            severity="info",
            confidence=0.35,
        )
        assert ti.confidence_label == "low"

    def test_trusted_insight_very_low_confidence(self):
        ti = TrustService.build_trusted_insight(
            insight_id="ins-4",
            title="Test",
            description="Desc",
            insight_type="trend",
            severity="info",
            confidence=0.1,
        )
        assert ti.confidence_label == "very_low"

    def test_trusted_insight_freshness_labels(self):
        real_time = TrustService.build_trusted_insight(
            insight_id="x",
            title="t",
            description="d",
            insight_type="trend",
            severity="info",
            confidence=0.5,
            data_freshness_hours=0.5,
        )
        assert real_time.freshness_label == "real_time"

        recent = TrustService.build_trusted_insight(
            insight_id="x",
            title="t",
            description="d",
            insight_type="trend",
            severity="info",
            confidence=0.5,
            data_freshness_hours=12,
        )
        assert recent.freshness_label == "recent"

        this_week = TrustService.build_trusted_insight(
            insight_id="x",
            title="t",
            description="d",
            insight_type="trend",
            severity="info",
            confidence=0.5,
            data_freshness_hours=72,
        )
        assert this_week.freshness_label == "this_week"

        stale = TrustService.build_trusted_insight(
            insight_id="x",
            title="t",
            description="d",
            insight_type="trend",
            severity="info",
            confidence=0.5,
            data_freshness_hours=200,
        )
        assert stale.freshness_label == "stale"

    def test_trusted_insight_to_dict(self):
        ti = TrustService.build_trusted_insight(
            insight_id="ins-5",
            title="Test",
            description="Desc",
            insight_type="anomaly",
            severity="critical",
            confidence=0.88,
            sources=["db"],
            recommended_action="Fix it",
            expected_impact="+5% revenue",
        )
        d = ti.to_dict()
        assert d["insight_id"] == "ins-5"
        assert d["confidence"] == 0.88
        assert d["confidence_label"] == "high"
        assert d["recommended_action"] == "Fix it"
        assert d["expected_impact"] == "+5% revenue"

    def test_severity_rank(self):
        assert TrustService.severity_rank("critical") == 4
        assert TrustService.severity_rank("warning") == 3
        assert TrustService.severity_rank("info") == 2
        assert TrustService.severity_rank("positive") == 1
        assert TrustService.severity_rank("unknown") == 0

    def test_format_trust_badge(self):
        assert TrustService.format_trust_badge(0.9) == "High confidence"
        assert TrustService.format_trust_badge(0.7) == "Medium confidence"
        assert TrustService.format_trust_badge(0.4) == "Low confidence"
        assert TrustService.format_trust_badge(0.1) == "Very low confidence"


class TestDataGraphService:
    """Tests for the Data Graph module — pure logic tests."""

    def test_guess_category_revenue(self):
        assert DataGraphService._guess_category("monthly_revenue") == "revenue"

    def test_guess_category_cost(self):
        assert DataGraphService._guess_category("ad_cost") == "cost"

    def test_guess_category_conversion(self):
        assert DataGraphService._guess_category("conversion_rate") == "conversion"

    def test_guess_category_engagement(self):
        assert DataGraphService._guess_category("page_views") == "engagement"

    def test_guess_category_retention(self):
        assert DataGraphService._guess_category("user_retention") == "retention"

    def test_guess_category_acquisition(self):
        assert DataGraphService._guess_category("new_signups") == "acquisition"

    def test_guess_category_general(self):
        assert DataGraphService._guess_category("some_random_column") == "general"

    def test_valid_relationship_types(self):
        assert "correlation" in VALID_RELATIONSHIP_TYPES
        assert "dependency" in VALID_RELATIONSHIP_TYPES
        assert "causation_hypothesis" in VALID_RELATIONSHIP_TYPES
        assert "foreign_key" in VALID_RELATIONSHIP_TYPES
        assert "derived_from" in VALID_RELATIONSHIP_TYPES
        assert "same_entity" in VALID_RELATIONSHIP_TYPES


class TestInsightMemoryService:
    """Tests for the Insight Memory Layer — pure logic tests."""

    def test_valid_insight_types(self):
        assert "anomaly" in VALID_INSIGHT_TYPES
        assert "opportunity" in VALID_INSIGHT_TYPES
        assert "loss" in VALID_INSIGHT_TYPES
        assert "trend" in VALID_INSIGHT_TYPES
        assert "pattern" in VALID_INSIGHT_TYPES
        assert "reconciliation_mismatch" in VALID_INSIGHT_TYPES
        assert "data_quality" in VALID_INSIGHT_TYPES
        assert "observation" in VALID_INSIGHT_TYPES

    @pytest.mark.asyncio
    async def test_store_insight_invalid_type(self):
        svc = InsightMemoryService()
        mock_session = AsyncMock()
        with pytest.raises(ValueError, match="Invalid insight_type"):
            await svc.store_insight(
                mock_session,
                "proj-1",
                "invalid_type",
                "title",
                "description",
            )
