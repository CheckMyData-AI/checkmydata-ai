"""Tests for ContextLoader learning surfacing.

Re-audit regression: ``load_recent_learnings`` must rank the full candidate
pool by ``priority_score`` and only then slice to the display count — not let
``get_learnings`` truncate by confidence first (which would silently drop a
high-priority, lower-confidence learning).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.context_loader import ContextLoader
from app.services.agent_learning_service import AgentLearningService


def _learning(subject: str, *, confidence: float, confirmed: int, applied: int):
    return SimpleNamespace(
        category="schema",
        subject=subject,
        lesson=f"lesson for {subject}",
        confidence=confidence,
        times_confirmed=confirmed,
        times_applied=applied,
        times_exposed=0,
    )


class _SessionCM:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *args):
        pass


class TestLoadRecentLearnings:
    def _loader(self) -> ContextLoader:
        return ContextLoader(
            vector_store=MagicMock(),
            tracker=MagicMock(),
            mcp_cache={},
        )

    @pytest.mark.asyncio
    async def test_high_priority_low_confidence_learning_surfaces(self):
        """A heavily-confirmed learning with sub-top confidence must surface,
        even when 15 higher-confidence-but-unproven rows precede it."""
        # 15 fillers: high confidence, never confirmed/applied -> modest priority.
        fillers = [
            _learning(f"filler_{i}", confidence=0.9, confirmed=0, applied=0) for i in range(15)
        ]
        # Champion: lower confidence (still >= 0.6) but heavily proven -> top priority.
        champion = _learning("champion_table", confidence=0.65, confirmed=100, applied=50)
        # DB returns confidence-desc order: fillers first, champion last (index 15).
        db_rows = [*fillers, champion]

        # Sanity: champion really does out-rank every filler by priority_score.
        assert AgentLearningService.priority_score(champion) > max(
            AgentLearningService.priority_score(f) for f in fillers
        )

        context = SimpleNamespace(
            connection_config=SimpleNamespace(connection_id="conn-1"),
        )

        get_learnings = AsyncMock(return_value=db_rows)
        with (
            patch.object(AgentLearningService, "get_learnings", get_learnings),
            patch(
                "app.models.base.async_session_factory",
                return_value=_SessionCM(),
            ),
        ):
            out = await self._loader().load_recent_learnings(context)

        assert out is not None
        # The proven champion surfaced despite ranking 16th by confidence.
        assert "champion_table" in out
        # And only the display count is emitted (1 header + 15 rows).
        assert len(out.splitlines()) == 1 + ContextLoader._RECENT_LEARNINGS_DISPLAY
        # The fetch was NOT pre-truncated to the display count.
        _, kwargs = get_learnings.call_args
        assert kwargs["limit"] == ContextLoader._RECENT_LEARNINGS_FETCH_CAP

    @pytest.mark.asyncio
    async def test_returns_none_without_connection_id(self):
        context = SimpleNamespace(connection_config=SimpleNamespace(connection_id=None))
        assert await self._loader().load_recent_learnings(context) is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_learnings(self):
        context = SimpleNamespace(connection_config=SimpleNamespace(connection_id="conn-1"))
        with (
            patch.object(AgentLearningService, "get_learnings", AsyncMock(return_value=[])),
            patch("app.models.base.async_session_factory", return_value=_SessionCM()),
        ):
            assert await self._loader().load_recent_learnings(context) is None
