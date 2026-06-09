"""Unit tests for SchemaChangeDetector insight emission (Phase 5)."""

from __future__ import annotations

import pytest

from app.services.schema_change_detector import SchemaChangeDetector


class _StubInsightService:
    """Captures store_insight calls instead of touching the DB."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def store_insight(self, session, project_id, insight_type, title, description, **kwargs):  # noqa: ANN001, ANN002
        self.calls.append(
            {
                "project_id": project_id,
                "insight_type": insight_type,
                "title": title,
                "description": description,
                **kwargs,
            }
        )
        return object()


@pytest.fixture
def _patch_insight(monkeypatch):
    stub = _StubInsightService()
    monkeypatch.setattr(
        "app.core.insight_memory.InsightMemoryService",
        lambda: stub,
    )
    return stub


@pytest.mark.asyncio
async def test_first_index_emits_no_alert(_patch_insight) -> None:
    detector = SchemaChangeDetector()
    diff = await detector.detect_and_alert(
        session=None,
        project_id="p1",
        connection_id="c1",
        previous_fingerprint={},
        current_fingerprint={"t1": "a"},
    )
    assert diff.added == ["t1"]
    assert _patch_insight.calls == []


@pytest.mark.asyncio
async def test_no_change_emits_no_alert(_patch_insight) -> None:
    fp = {"t1": "a", "t2": "b"}
    await SchemaChangeDetector().detect_and_alert(
        session=None,
        project_id="p1",
        connection_id="c1",
        previous_fingerprint=fp,
        current_fingerprint=dict(fp),
    )
    assert _patch_insight.calls == []


@pytest.mark.asyncio
async def test_removal_emits_warning_insight(_patch_insight) -> None:
    await SchemaChangeDetector().detect_and_alert(
        session=None,
        project_id="p1",
        connection_id="c1",
        previous_fingerprint={"t1": "a", "gone": "b"},
        current_fingerprint={"t1": "a"},
    )
    assert len(_patch_insight.calls) == 1
    call = _patch_insight.calls[0]
    assert call["insight_type"] == "schema_change"
    assert call["severity"] == "warning"
    assert "gone" in call["description"]
    assert call["confidence"] == 0.85
    assert "re-run" in call["recommended_action"].lower()


@pytest.mark.asyncio
async def test_addition_only_emits_positive_insight(_patch_insight) -> None:
    await SchemaChangeDetector().detect_and_alert(
        session=None,
        project_id="p1",
        connection_id="c1",
        previous_fingerprint={"t1": "a"},
        current_fingerprint={"t1": "a", "fresh": "z"},
    )
    assert len(_patch_insight.calls) == 1
    call = _patch_insight.calls[0]
    # Additions-only is non-destructive → positive severity, clean confidence.
    assert call["severity"] == "positive"
    assert "fresh" in call["description"]
    assert call["confidence"] == 0.7


@pytest.mark.asyncio
async def test_change_only_emits_info_insight(_patch_insight) -> None:
    await SchemaChangeDetector().detect_and_alert(
        session=None,
        project_id="p1",
        connection_id="c1",
        previous_fingerprint={"t1": "a"},
        current_fingerprint={"t1": "MUTATED"},
    )
    assert len(_patch_insight.calls) == 1
    call = _patch_insight.calls[0]
    assert call["severity"] == "info"
    assert "t1" in call["description"]
    assert call["confidence"] == 0.7
