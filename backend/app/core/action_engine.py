"""Insight → Action Engine — transforms every insight into a concrete
recommended action with expected impact, priority, and confidence.

Not just "what's wrong" but "what to do about it".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ActionRecommendation:
    """A concrete, actionable recommendation derived from an insight."""

    action_type: str
    title: str
    description: str
    what_to_do: str
    expected_impact: str
    impact_metric: str
    impact_estimate_pct: float
    priority: str
    effort: str
    confidence: float = 0.5
    prerequisites: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    source_insight_type: str = ""
    source_insight_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "title": self.title,
            "description": self.description,
            "what_to_do": self.what_to_do,
            "expected_impact": self.expected_impact,
            "impact_metric": self.impact_metric,
            "impact_estimate_pct": round(self.impact_estimate_pct, 1),
            "priority": self.priority,
            "effort": self.effort,
            "confidence": round(self.confidence, 2),
            "prerequisites": self.prerequisites,
            "risks": self.risks,
            "source_insight_type": self.source_insight_type,
            "source_insight_title": self.source_insight_title,
        }


INSIGHT_ACTION_MAP: dict[str, dict[str, Any]] = {
    "anomaly": {
        "action_type": "investigate_and_fix",
        "effort": "medium",
        "base_impact": 5.0,
    },
    "opportunity": {
        "action_type": "capitalize",
        "effort": "medium",
        "base_impact": 10.0,
    },
    "loss": {
        "action_type": "stop_bleeding",
        "effort": "high",
        "base_impact": 15.0,
    },
    "trend": {
        "action_type": "monitor_and_respond",
        "effort": "low",
        "base_impact": 3.0,
    },
    "pattern": {
        "action_type": "leverage_pattern",
        "effort": "medium",
        "base_impact": 8.0,
    },
    "data_quality": {
        "action_type": "fix_data_pipeline",
        "effort": "medium",
        "base_impact": 5.0,
    },
}


class ActionEngine:
    """Transforms insights into concrete, prioritized actions."""

    def generate_actions(
        self,
        insights: list[dict[str, Any]],
    ) -> list[ActionRecommendation]:
        """Generate action recommendations from a list of insights."""
        actions: list[ActionRecommendation] = []

        for insight in insights:
            action = self._insight_to_action(insight)
            if action:
                actions.append(action)

        actions.sort(
            key=lambda a: self._priority_rank(a.priority),
            reverse=True,
        )
        return actions

    def enrich_insight(
        self,
        insight: dict[str, Any],
    ) -> dict[str, Any]:
        """Enrich an existing insight dict with action recommendation."""
        action = self._insight_to_action(insight)
        if action:
            insight["action"] = action.to_dict()
        return insight

    def _insight_to_action(
        self,
        insight: dict[str, Any],
    ) -> ActionRecommendation | None:
        """Convert a single insight into an action recommendation."""
        insight_type = insight.get("insight_type", "")
        severity = insight.get("severity", "info")
        title = insight.get("title", "")
        description = insight.get("description", "")
        confidence = float(insight.get("confidence", 0.5))
        rec_action = insight.get("recommended_action", "")
        exp_impact = insight.get("expected_impact", "")

        config = INSIGHT_ACTION_MAP.get(
            insight_type,
            {
                "action_type": "investigate",
                "effort": "low",
                "base_impact": 2.0,
            },
        )

        impact_pct = self._estimate_impact(
            float(config["base_impact"]),
            severity,
            confidence,
        )
        priority = self._determine_priority(severity, impact_pct, confidence)
        what_to_do = self._generate_action_steps(insight_type, severity, title, rec_action)
        impact_text = self._format_impact(exp_impact, impact_pct, insight_type)

        return ActionRecommendation(
            action_type=str(config["action_type"]),
            title=self._action_title(insight_type, title),
            description=description,
            what_to_do=what_to_do,
            expected_impact=impact_text,
            impact_metric=self._guess_metric(insight),
            impact_estimate_pct=impact_pct,
            priority=priority,
            effort=str(config["effort"]),
            confidence=confidence,
            prerequisites=self._get_prerequisites(insight_type),
            risks=self._get_risks(insight_type, severity),
            source_insight_type=insight_type,
            source_insight_title=title,
        )

    @staticmethod
    def _estimate_impact(base: float, severity: str, confidence: float) -> float:
        """Estimate impact percentage based on severity and confidence."""
        severity_multiplier = {
            "critical": 3.0,
            "warning": 1.5,
            "info": 0.5,
            "positive": 2.0,
        }.get(severity, 1.0)

        return round(base * severity_multiplier * confidence, 1)

    @staticmethod
    def _determine_priority(severity: str, impact_pct: float, confidence: float) -> str:
        """Determine action priority from severity and impact."""
        score = impact_pct * confidence
        if severity == "critical" or score > 15:
            return "critical"
        if severity == "warning" or score > 8:
            return "high"
        if score > 3:
            return "medium"
        return "low"

    @staticmethod
    def _generate_action_steps(
        insight_type: str,
        severity: str,
        title: str,
        existing_action: str,
    ) -> str:
        """Generate concrete action steps."""
        if existing_action:
            return existing_action

        templates: dict[str, str] = {
            "anomaly": (
                "1. Verify the data source is functioning correctly. "
                "2. Check for recent changes that could cause this anomaly. "
                "3. If confirmed, fix the root cause and set up monitoring."
            ),
            "opportunity": (
                "1. Validate the opportunity with a deeper analysis. "
                "2. Design a targeted experiment to capture this potential. "
                "3. Measure results and scale if positive."
            ),
            "loss": (
                "1. Quantify the total impact of this loss. "
                "2. Identify the root cause through detailed investigation. "
                "3. Implement a fix and track recovery."
            ),
            "trend": (
                "1. Set up automated monitoring for this metric. "
                "2. Investigate underlying drivers. "
                "3. Prepare response plan if trend continues."
            ),
            "pattern": (
                "1. Validate the pattern with additional data. "
                "2. Identify how to leverage this across other areas. "
                "3. Build it into standard operating procedures."
            ),
            "data_quality": (
                "1. Identify the pipeline stage causing the issue. "
                "2. Fix the data at the source. "
                "3. Add validation checks to prevent recurrence."
            ),
        }

        return templates.get(
            insight_type,
            "Investigate further and determine appropriate next steps.",
        )

    @staticmethod
    def _format_impact(
        existing_impact: str,
        impact_pct: float,
        insight_type: str,
    ) -> str:
        """Format the expected impact as a clear statement."""
        if existing_impact:
            return existing_impact

        verb = {
            "anomaly": "improve data accuracy",
            "opportunity": "increase the target metric",
            "loss": "recover lost revenue/users",
            "trend": "stay ahead of the trend",
            "pattern": "leverage this pattern for growth",
            "data_quality": "improve reporting reliability",
        }.get(insight_type, "improve the situation")

        return f"Expected to {verb} by ~{impact_pct:.0f}%"

    @staticmethod
    def _action_title(insight_type: str, insight_title: str) -> str:
        """Generate a clear action title."""
        prefix = {
            "anomaly": "Fix",
            "opportunity": "Capitalize on",
            "loss": "Stop",
            "trend": "Monitor",
            "pattern": "Leverage",
            "data_quality": "Fix data issue",
        }.get(insight_type, "Address")

        short_title = insight_title[:80] if insight_title else "this finding"
        return f"{prefix}: {short_title}"

    @staticmethod
    def _guess_metric(insight: dict[str, Any]) -> str:
        """Extract the primary metric from the insight."""
        for key in ("metric", "affected_metrics", "impact_metric"):
            val = insight.get(key)
            if val:
                if isinstance(val, list) and val:
                    return str(val[0])
                if isinstance(val, str):
                    return val
        return "primary metric"

    @staticmethod
    def _get_prerequisites(insight_type: str) -> list[str]:
        """Return prerequisites for the action."""
        defaults: dict[str, list[str]] = {
            "anomaly": [
                "Access to the data source",
                "Understanding of expected values",
            ],
            "opportunity": [
                "Budget for testing",
                "Team capacity to execute",
            ],
            "loss": [
                "Access to affected systems",
                "Stakeholder approval for changes",
            ],
            "data_quality": [
                "Access to data pipeline configuration",
            ],
        }
        return defaults.get(insight_type, [])

    @staticmethod
    def _get_risks(insight_type: str, severity: str) -> list[str]:
        """Return potential risks of the action."""
        risks: list[str] = []
        if severity == "critical":
            risks.append("Delaying action may increase impact")
        if insight_type == "opportunity":
            risks.append("Opportunity may be time-sensitive")
        if insight_type == "loss":
            risks.append("Fix may have side effects on other metrics")
        return risks

    @staticmethod
    def _priority_rank(priority: str) -> int:
        return {
            "critical": 4,
            "high": 3,
            "medium": 2,
            "low": 1,
        }.get(priority, 0)

    def format_actions(self, actions: list[ActionRecommendation]) -> str:
        """Format actions as markdown text."""
        if not actions:
            return ""

        lines = ["\n🎯 RECOMMENDED ACTIONS:"]
        for action in actions:
            icon = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🔵",
            }.get(action.priority, "⚪")

            lines.append(f"\n  {icon} **{action.title}**")
            lines.append(f"     📋 {action.what_to_do}")
            if action.expected_impact:
                lines.append(f"     📊 Expected: {action.expected_impact}")
            lines.append(f"     ⏱️ Effort: {action.effort} | Priority: {action.priority}")
        return "\n".join(lines)
