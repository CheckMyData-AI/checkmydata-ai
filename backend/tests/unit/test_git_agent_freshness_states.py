"""F-GIT-04: GitAgent's freshness warning saw only one of four states.

`_freshness_warning` called `count_commits_ahead` and warned when the clone had moved
past the indexed SHA. W5 built `classify_freshness` — exact AHEAD/BEHIND/DIVERGED with
counts — and wired it into `KnowledgeFreshnessService`, leaving this second producer of
the same signal on the naive path.

The two states it could not see are the ones that matter most here. GitAgent answers
from the **working tree**: blame, diffs, file churn. When the clone is BEHIND the index
its answers describe a tree older than the knowledge base, and when the two have
DIVERGED the two sources can contradict each other outright — and the agent said
nothing at all.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.git_agent import GitAgent
from app.knowledge.git_tracker import GitFreshness


def _agent(state: GitFreshness, ahead: int, behind: int) -> GitAgent:
    agent = object.__new__(GitAgent)
    tracker = MagicMock()
    tracker.get_last_indexed_sha = AsyncMock(return_value="abcdef1234")
    tracker.classify_freshness_async = AsyncMock(return_value=(state, ahead, behind))
    tracker.count_commits_ahead = AsyncMock(return_value=ahead)
    agent._git_tracker = tracker
    return agent


async def _warning(state: GitFreshness, ahead: int = 0, behind: int = 0) -> str | None:
    agent = _agent(state, ahead, behind)
    with patch("app.models.base.async_session_factory"):
        return await agent._freshness_warning("p1", Path("/tmp/repo"))


class TestAllFourStatesAreReported:
    @pytest.mark.asyncio
    async def test_fresh_says_nothing(self):
        assert await _warning(GitFreshness.FRESH) is None

    @pytest.mark.asyncio
    async def test_ahead_warns_that_the_knowledge_base_lags(self):
        w = await _warning(GitFreshness.AHEAD, ahead=9)
        assert w and "9" in w
        assert "knowledge" in w.lower() or "index" in w.lower()

    @pytest.mark.asyncio
    async def test_behind_warns_that_the_tree_is_older_than_the_index(self):
        """The state GitAgent used to miss entirely, and the one that misleads most:
        every answer it gives comes from a tree the index has already moved past."""
        w = await _warning(GitFreshness.BEHIND, behind=4)
        assert w, "BEHIND must warn — the working tree is the answer's source"
        assert "4" in w
        assert "pull" not in w.lower(), "a rewound clone is not fixed by a pull"

    @pytest.mark.asyncio
    async def test_diverged_warns_and_says_the_two_can_contradict(self):
        w = await _warning(GitFreshness.DIVERGED, ahead=2, behind=3)
        assert w, "DIVERGED must warn"
        assert "2" in w and "3" in w
        assert "diverg" in w.lower()

    @pytest.mark.asyncio
    async def test_the_ahead_threshold_still_applies(self):
        """A clone one commit ahead is the normal state of any active repository;
        warning on it would be the noise that trains people to ignore warnings."""
        from app.config import settings

        w = await _warning(
            GitFreshness.AHEAD, ahead=max(1, settings.git_staleness_warn_commits - 1)
        )
        assert w is None

    @pytest.mark.asyncio
    async def test_behind_and_diverged_have_no_threshold(self):
        """Being behind by one commit is not a normal state — it means the clone lost
        history the index still describes, and no count makes that benign."""
        assert await _warning(GitFreshness.BEHIND, behind=1) is not None
        assert await _warning(GitFreshness.DIVERGED, ahead=1, behind=1) is not None

    @pytest.mark.asyncio
    async def test_an_unavailable_classifier_says_so_instead_of_going_quiet(self):
        """This test first asserted `is None`, which was the wrong standard.

        `None` from this method means "nothing to warn about" — indistinguishable from
        "this clone is in step with the index". The silent-degradation ratchet caught it
        in the same run: if the caller cannot tell your fallback from real emptiness,
        say so. Getting here means the repo *and* the indexed SHA both resolved and the
        comparison still failed, so it is a warning for the operator and a caveat for
        the reader — not silence for both.
        """
        agent = _agent(GitFreshness.FRESH, 0, 0)
        agent._git_tracker.classify_freshness_async = AsyncMock(side_effect=RuntimeError("no repo"))
        with patch("app.models.base.async_session_factory"):
            w = await agent._freshness_warning("p1", Path("/tmp/repo"))
        assert w and "unverified" in w.lower(), w

    @pytest.mark.asyncio
    async def test_no_indexed_sha_means_no_comparison_to_make(self):
        agent = _agent(GitFreshness.FRESH, 0, 0)
        agent._git_tracker.get_last_indexed_sha = AsyncMock(return_value=None)
        with patch("app.models.base.async_session_factory"):
            assert await agent._freshness_warning("p1", Path("/tmp/repo")) is None
