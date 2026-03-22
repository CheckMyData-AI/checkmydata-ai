"""Trust Layer — confidence scoring and provenance for every insight.

Every insight produced by the system gets wrapped in a TrustedInsight that
carries confidence, source references, validation status, and freshness data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrustedInsight:
    """Wraps any insight with trust metadata for presentation to the user."""

    insight_id: str
    title: str
    description: str
    insight_type: str
    severity: str
    confidence: float
    confidence_label: str = ""
    sources: list[str] = field(default_factory=list)
    validation_method: str = "auto"
    data_freshness_hours: float = 0.0
    freshness_label: str = ""
    cross_validated: bool = False
    sample_size: int = 0
    recommended_action: str = ""
    expected_impact: str = ""

    def __post_init__(self) -> None:
        self.confidence_label = self._compute_confidence_label()
        self.freshness_label = self._compute_freshness_label()

    def _compute_confidence_label(self) -> str:
        if self.confidence >= 0.85:
            return "high"
        if self.confidence >= 0.6:
            return "medium"
        if self.confidence >= 0.3:
            return "low"
        return "very_low"

    def _compute_freshness_label(self) -> str:
        if self.data_freshness_hours <= 1:
            return "real_time"
        if self.data_freshness_hours <= 24:
            return "recent"
        if self.data_freshness_hours <= 168:
            return "this_week"
        return "stale"

    def to_dict(self) -> dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "title": self.title,
            "description": self.description,
            "insight_type": self.insight_type,
            "severity": self.severity,
            "confidence": round(self.confidence, 2),
            "confidence_label": self.confidence_label,
            "sources": self.sources,
            "validation_method": self.validation_method,
            "data_freshness_hours": round(self.data_freshness_hours, 1),
            "freshness_label": self.freshness_label,
            "cross_validated": self.cross_validated,
            "sample_size": self.sample_size,
            "recommended_action": self.recommended_action,
            "expected_impact": self.expected_impact,
        }


class TrustService:
    """Computes and manages trust scores for insights."""

    @staticmethod
    def compute_confidence(
        *,
        base_confidence: float = 0.5,
        data_points: int = 0,
        sources_count: int = 1,
        is_cross_validated: bool = False,
        user_confirmations: int = 0,
        user_dismissals: int = 0,
        data_freshness_hours: float = 0.0,
    ) -> float:
        """Compute a composite confidence score from multiple signals."""
        score = base_confidence

        if data_points >= 100:
            score += 0.1
        elif data_points >= 10:
            score += 0.05

        if sources_count >= 3:
            score += 0.1
        elif sources_count >= 2:
            score += 0.05

        if is_cross_validated:
            score += 0.15

        score += user_confirmations * 0.1
        score -= user_dismissals * 0.15

        if data_freshness_hours > 168:
            score -= 0.1
        elif data_freshness_hours > 24:
            score -= 0.05

        return max(0.0, min(1.0, round(score, 3)))

    @staticmethod
    def build_trusted_insight(
        insight_id: str,
        title: str,
        description: str,
        insight_type: str,
        severity: str,
        confidence: float,
        *,
        sources: list[str] | None = None,
        validation_method: str = "auto",
        data_freshness_hours: float = 0.0,
        cross_validated: bool = False,
        sample_size: int = 0,
        recommended_action: str = "",
        expected_impact: str = "",
    ) -> TrustedInsight:
        return TrustedInsight(
            insight_id=insight_id,
            title=title,
            description=description,
            insight_type=insight_type,
            severity=severity,
            confidence=confidence,
            sources=sources or [],
            validation_method=validation_method,
            data_freshness_hours=data_freshness_hours,
            cross_validated=cross_validated,
            sample_size=sample_size,
            recommended_action=recommended_action,
            expected_impact=expected_impact,
        )

    @staticmethod
    def severity_rank(severity: str) -> int:
        """Numeric rank for sorting (higher = more severe)."""
        return {"critical": 4, "warning": 3, "info": 2, "positive": 1}.get(severity, 0)

    @staticmethod
    def format_trust_badge(confidence: float) -> str:
        """Human-readable badge for display."""
        if confidence >= 0.85:
            return "High confidence"
        if confidence >= 0.6:
            return "Medium confidence"
        if confidence >= 0.3:
            return "Low confidence"
        return "Very low confidence"
