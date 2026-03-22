"""Tests for the Insight -> Action Engine."""

from app.core.action_engine import ActionEngine, ActionRecommendation, _safe_float


class TestActionEngine:
    def setup_method(self):
        self.engine = ActionEngine()

    def test_empty_insights_returns_empty(self):
        assert self.engine.generate_actions([]) == []

    def test_anomaly_insight_generates_action(self):
        insights = [
            {
                "insight_type": "anomaly",
                "severity": "warning",
                "title": "Missing data in revenue column",
                "description": "Column revenue is entirely NULL",
                "confidence": 0.7,
                "recommended_action": "Check data pipeline",
                "expected_impact": "Fix reporting accuracy",
            }
        ]
        actions = self.engine.generate_actions(insights)
        assert len(actions) == 1
        assert actions[0].action_type == "investigate_and_fix"
        assert "Fix" in actions[0].title
        assert actions[0].priority in ("high", "medium", "critical")

    def test_opportunity_insight_generates_action(self):
        insights = [
            {
                "insight_type": "opportunity",
                "severity": "positive",
                "title": "BR outperforms by 80% on revenue",
                "description": "Brazil segment converts 2x better",
                "confidence": 0.8,
            }
        ]
        actions = self.engine.generate_actions(insights)
        assert len(actions) == 1
        assert actions[0].action_type == "capitalize"
        assert "Capitalize" in actions[0].title

    def test_loss_insight_generates_action(self):
        insights = [
            {
                "insight_type": "loss",
                "severity": "critical",
                "title": "Checkout drop: 60% at step 3",
                "description": "Users drop off at payment",
                "confidence": 0.85,
            }
        ]
        actions = self.engine.generate_actions(insights)
        assert len(actions) == 1
        assert actions[0].action_type == "stop_bleeding"
        assert actions[0].priority == "critical"

    def test_multiple_insights_sorted_by_priority(self):
        insights = [
            {
                "insight_type": "trend",
                "severity": "info",
                "title": "Slight uptick",
                "description": "Minor trend",
                "confidence": 0.3,
            },
            {
                "insight_type": "loss",
                "severity": "critical",
                "title": "Major loss",
                "description": "Critical revenue loss",
                "confidence": 0.9,
            },
            {
                "insight_type": "opportunity",
                "severity": "positive",
                "title": "Growth chance",
                "description": "Big opportunity",
                "confidence": 0.7,
            },
        ]
        actions = self.engine.generate_actions(insights)
        assert len(actions) == 3
        assert actions[0].priority in ("critical", "high")
        priorities = [a.priority for a in actions]
        rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        ranks = [rank.get(p, 0) for p in priorities]
        assert ranks == sorted(ranks, reverse=True)

    def test_enrich_insight_adds_action(self):
        insight = {
            "insight_type": "anomaly",
            "severity": "warning",
            "title": "Test anomaly",
            "description": "Test desc",
            "confidence": 0.6,
        }
        enriched = self.engine.enrich_insight(insight)
        assert "action" in enriched
        assert enriched["action"]["action_type"] == "investigate_and_fix"

    def test_action_recommendation_to_dict(self):
        action = ActionRecommendation(
            action_type="investigate_and_fix",
            title="Fix: Missing data",
            description="Column is NULL",
            what_to_do="Check pipeline",
            expected_impact="Better accuracy",
            impact_metric="revenue",
            impact_estimate_pct=12.5,
            priority="high",
            effort="medium",
            confidence=0.7,
            prerequisites=["Access"],
            risks=["Delay risk"],
        )
        d = action.to_dict()
        assert d["action_type"] == "investigate_and_fix"
        assert d["impact_estimate_pct"] == 12.5
        assert len(d["prerequisites"]) == 1

    def test_format_actions_empty(self):
        assert self.engine.format_actions([]) == ""

    def test_format_actions_with_data(self):
        actions = [
            ActionRecommendation(
                action_type="stop_bleeding",
                title="Stop: Revenue leak",
                description="Users dropping off",
                what_to_do="Fix checkout flow",
                expected_impact="+15% conversion",
                impact_metric="conversion",
                impact_estimate_pct=15.0,
                priority="critical",
                effort="high",
            )
        ]
        text = self.engine.format_actions(actions)
        assert "RECOMMENDED ACTIONS" in text
        assert "Revenue leak" in text
        assert "critical" in text

    def test_unknown_insight_type_handled(self):
        insights = [
            {
                "insight_type": "custom_type",
                "severity": "info",
                "title": "Custom finding",
                "description": "Something custom",
                "confidence": 0.5,
            }
        ]
        actions = self.engine.generate_actions(insights)
        assert len(actions) == 1
        assert actions[0].action_type == "investigate"

    def test_impact_scales_with_severity(self):
        critical = ActionEngine._estimate_impact(10.0, "critical", 0.8)
        info = ActionEngine._estimate_impact(10.0, "info", 0.8)
        assert critical > info

    def test_priority_determination(self):
        assert ActionEngine._determine_priority("critical", 20, 0.9) == "critical"
        assert ActionEngine._determine_priority("info", 1, 0.3) == "low"

    def test_none_confidence_handled(self):
        insights = [
            {
                "insight_type": "anomaly",
                "severity": "warning",
                "title": "Test",
                "description": "Test with None confidence",
                "confidence": None,
            }
        ]
        actions = self.engine.generate_actions(insights)
        assert len(actions) == 1
        assert actions[0].confidence >= 0

    def test_non_numeric_confidence_handled(self):
        insights = [
            {
                "insight_type": "anomaly",
                "severity": "warning",
                "title": "Test",
                "description": "Test with string confidence",
                "confidence": "high",
            }
        ]
        actions = self.engine.generate_actions(insights)
        assert len(actions) == 1


class TestSafeFloat:
    def test_valid_float(self):
        assert _safe_float(3.14) == 3.14

    def test_valid_int(self):
        assert _safe_float(42) == 42.0

    def test_valid_string_number(self):
        assert _safe_float("0.5") == 0.5

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0
        assert _safe_float(None, 0.5) == 0.5

    def test_invalid_string_returns_default(self):
        assert _safe_float("high", 0.5) == 0.5

    def test_dict_returns_default(self):
        assert _safe_float({"a": 1}, 0.3) == 0.3
