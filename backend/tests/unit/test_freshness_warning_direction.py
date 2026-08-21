"""The git freshness warnings named the wrong subject, so they prescribed the wrong fix.

`classify_freshness`'s own docstring fixes the direction (`git_tracker.py:35-36`):

    ahead  = commits on the working ref (HEAD) not reachable from indexed_sha
    behind = commits reachable from indexed_sha but not on HEAD

So `ahead` means **the clone has commits the index has never seen** (the index is
stale), and `behind` means **the index references commits this clone no longer has**
(the clone was reset or force-pushed). `tests/unit/test_git_tracker_freshness.py`
pins both directions against a real repository.

The warnings took the knowledge base as their subject without flipping the terms:
BEHIND read "Knowledge base is N commit(s) BEHIND current HEAD; **pull** before
trusting answers about recent code" — but it is the clone that is missing commits, and
a pull cannot bring back history that was rewritten. A warning that prescribes an
action which cannot help is worse than silence: it spends the reader's trust and their
time, and then the discrepancy is still there.
"""

from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.git_tracker import GitFreshness
from app.services.knowledge_freshness_service import KnowledgeFreshnessService


async def _warn_for(state: GitFreshness, ahead: int, behind: int, tmp_path: Path) -> list[str]:
    svc = KnowledgeFreshnessService()
    tracker = MagicMock()
    tracker.get_last_indexed_sha = AsyncMock(return_value="deadbeef")
    tracker.classify_freshness_async = AsyncMock(return_value=(state, ahead, behind))

    with (
        patch("app.services.db_index_service.DbIndexService") as mock_db_cls,
        patch("app.services.code_db_sync_service.CodeDbSyncService") as mock_sync_cls,
        patch("app.knowledge.git_tracker.GitTracker", return_value=tracker),
    ):
        mock_db_cls.return_value.get_index_age = AsyncMock(return_value=timedelta(minutes=1))
        mock_sync_cls.return_value.get_sync_status = AsyncMock(return_value="completed")
        snap = await svc.evaluate(
            session=AsyncMock(),
            project_id="p1",
            connection_id="c1",
            repo_clone_dir=tmp_path,
        )
    return [w for w in snap.warnings if "commit" in w or "diverged" in w.lower()]


class TestWarningsNameTheRightSubject:
    @pytest.mark.asyncio
    async def test_ahead_says_the_index_is_missing_new_commits(self, tmp_path):
        """`ahead` = the clone has commits the index never saw → added code, not removed."""
        warnings = await _warn_for(GitFreshness.AHEAD, 3, 0, tmp_path)
        assert warnings, "AHEAD must warn"
        text = " ".join(warnings).lower()
        assert "3" in text
        assert "removed code" not in text, (
            "ahead means commits the index has not seen yet, so re-indexing picks up "
            f"ADDED code — not removed: {warnings}"
        )

    @pytest.mark.asyncio
    async def test_behind_says_the_clone_lost_commits_and_does_not_advise_a_pull(self, tmp_path):
        """`behind` = the index references commits this clone no longer has."""
        warnings = await _warn_for(GitFreshness.BEHIND, 0, 2, tmp_path)
        assert warnings, "BEHIND must warn"
        text = " ".join(warnings).lower()
        assert "2" in text
        assert "pull" not in text, (
            "the clone was rewound, so a pull cannot restore rewritten history — "
            f"advising it sends the reader to do something that cannot help: {warnings}"
        )
        assert "knowledge base is" not in text or "behind current head" not in text, (
            f"the subject is inverted — it is the clone that is behind: {warnings}"
        )

    @pytest.mark.asyncio
    async def test_diverged_does_not_attribute_both_counts_to_one_side(self, tmp_path):
        """ "N ahead, M behind" of the knowledge base swaps the two numbers."""
        warnings = await _warn_for(GitFreshness.DIVERGED, 4, 7, tmp_path)
        assert warnings, "DIVERGED must warn"
        text = " ".join(warnings)
        assert "4" in text and "7" in text, warnings
        assert "Knowledge base has diverged from HEAD (4 commit(s) ahead" not in text, (
            f"4 is HEAD's lead over the index, not the index's over HEAD: {warnings}"
        )

    @pytest.mark.asyncio
    async def test_fresh_says_nothing(self, tmp_path):
        assert await _warn_for(GitFreshness.FRESH, 0, 0, tmp_path) == []
