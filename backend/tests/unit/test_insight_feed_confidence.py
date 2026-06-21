"""Regression: a non-numeric LLM-supplied confidence must not discard a whole
table's deep-analysis insights.

``InsightFeedAgent._llm_deep_analysis`` coerced ``item["confidence"]`` with a
bare ``float()`` inside a per-table ``try/except`` that returns ``[]`` on any
error. LLMs routinely emit ``"high"`` / ``"90%"`` for a confidence field, so a
single such item raised ``ValueError`` and dropped every insight the model
produced for that table.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.insight_feed_agent import InsightFeedAgent, _coerce_confidence


class TestCoerceConfidence:
    def test_numeric_passthrough(self):
        assert _coerce_confidence(0.83) == 0.83
        assert _coerce_confidence("0.42") == 0.42

    def test_junk_falls_back_to_default(self):
        assert _coerce_confidence("high") == 0.5
        assert _coerce_confidence(None) == 0.5
        assert _coerce_confidence("90%") == 0.5
        assert _coerce_confidence("nonsense", default=0.3) == 0.3


def _llm_returning(payload: list[dict]) -> MagicMock:
    llm = MagicMock()
    resp = MagicMock()
    resp.content = json.dumps(payload)
    llm.complete = AsyncMock(return_value=resp)
    return llm


class TestDeepAnalysisBadConfidence:
    @pytest.mark.asyncio
    async def test_bad_confidence_does_not_discard_other_insights(self):
        agent = InsightFeedAgent()
        llm = _llm_returning(
            [
                {"type": "trend", "title": "Sales up", "confidence": 0.9},
                {"type": "anomaly", "title": "Null spike", "confidence": "high"},
            ]
        )

        result = await agent._llm_deep_analysis(
            "orders", {"amount": "numeric"}, [{"amount": 10}], llm
        )

        # Both insights survive; the junk confidence is defaulted, not fatal.
        assert len(result) == 2
        titles = {r["title"] for r in result}
        assert titles == {"[orders] Sales up", "[orders] Null spike"}
        for r in result:
            assert isinstance(r["confidence"], float)
            assert 0.0 <= r["confidence"] <= 0.7
