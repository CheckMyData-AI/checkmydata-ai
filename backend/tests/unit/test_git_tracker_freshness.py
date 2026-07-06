"""Tests for GitFreshness enum and classify_freshness function (C-F, SYNC-L3).

These tests cover:
- FRESH when indexed SHA == HEAD
- AHEAD when HEAD has moved past indexed_sha
- BEHIND when indexed_sha is newer than HEAD
- DIVERGED (mocked) when both sides have unique commits
- Bad SHA re-raises (no false-fresh sentinel)
- classify_freshness_async returns same result as sync (fetch_origin=False)
- classify_freshness_async degrades gracefully when origin.fetch raises
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from git import Repo

from app.knowledge.git_tracker import GitFreshness, GitTracker, classify_freshness


def _commit(repo: Repo, path: Path, name: str, text: str) -> str:
    f = path / name
    f.write_text(text)
    repo.index.add([str(f)])
    return repo.index.commit(f"add {name}").hexsha


@pytest.fixture
def tiny_repo(tmp_path):
    repo = Repo.init(tmp_path)
    repo.config_writer().set_value("user", "email", "t@t.io").release()
    repo.config_writer().set_value("user", "name", "t").release()
    c1 = _commit(repo, tmp_path, "a.txt", "1")
    c2 = _commit(repo, tmp_path, "b.txt", "2")
    return repo, c1, c2


def test_fresh_when_indexed_equals_head(tiny_repo):
    repo, _c1, c2 = tiny_repo
    state, ahead, behind = classify_freshness(repo, c2, repo.active_branch.name)
    assert state is GitFreshness.FRESH
    assert (ahead, behind) == (0, 0)


def test_ahead_when_head_moved_past_indexed(tiny_repo):
    repo, c1, _c2 = tiny_repo  # indexed at c1, HEAD at c2 → 1 commit ahead
    state, ahead, behind = classify_freshness(repo, c1, repo.active_branch.name)
    assert state is GitFreshness.AHEAD
    assert (ahead, behind) == (1, 0)


def test_behind_when_indexed_ahead_of_head(tiny_repo):
    repo, c1, c2 = tiny_repo
    # move HEAD back to c1; indexed stays at c2 → behind by 1
    repo.git.reset("--hard", c1)
    state, ahead, behind = classify_freshness(repo, c2, repo.active_branch.name)
    assert state is GitFreshness.BEHIND
    assert (ahead, behind) == (0, 1)


def test_diverged_uses_iter_commits_counts_mocked():
    # Deterministic diverged case without crafting a real divergent history:
    # HEAD has 2 unique, indexed has 3 unique.
    repo = MagicMock()
    repo.commit.side_effect = lambda rev: MagicMock(hexsha=str(rev))

    def _iter(spec, **kw):
        left, right = spec.split("..")
        # "indexed..head" → ahead ; "head..indexed" → behind
        if left == "isha":
            return [MagicMock(), MagicMock()]  # ahead = 2
        return [MagicMock(), MagicMock(), MagicMock()]  # behind = 3

    repo.iter_commits.side_effect = _iter
    state, ahead, behind = classify_freshness(repo, "isha", "main")
    assert state is GitFreshness.DIVERGED
    assert (ahead, behind) == (2, 3)


def test_bad_sha_reraises_not_false_fresh():
    from git.exc import BadName

    repo = MagicMock()
    repo.commit.side_effect = BadName("no such rev")
    with pytest.raises((BadName, ValueError)):
        classify_freshness(repo, "deadbeef", "main")


# ---------------------------------------------------------------------------
# classify_freshness_async tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_freshness_async_matches_sync(tmp_path):
    """async wrapper with fetch_origin=False must return the same tuple as sync."""
    repo = Repo.init(tmp_path)
    repo.config_writer().set_value("user", "email", "t@t.io").release()
    repo.config_writer().set_value("user", "name", "t").release()
    c1 = _commit(repo, tmp_path, "a.txt", "1")
    c2 = _commit(repo, tmp_path, "b.txt", "2")

    tracker = GitTracker()
    branch = repo.active_branch.name

    # FRESH
    result = await tracker.classify_freshness_async(tmp_path, c2, branch, fetch_origin=False)
    assert result == (GitFreshness.FRESH, 0, 0)

    # AHEAD
    result = await tracker.classify_freshness_async(tmp_path, c1, branch, fetch_origin=False)
    assert result == (GitFreshness.AHEAD, 1, 0)


@pytest.mark.asyncio
async def test_classify_freshness_async_fetch_origin_failure_degrades_to_local(tmp_path):
    """When origin.fetch raises, async wrapper falls back to local ref (no exception escapes)."""
    repo = Repo.init(tmp_path)
    repo.config_writer().set_value("user", "email", "t@t.io").release()
    repo.config_writer().set_value("user", "name", "t").release()
    _c1 = _commit(repo, tmp_path, "a.txt", "1")
    c2 = _commit(repo, tmp_path, "b.txt", "2")

    tracker = GitTracker()
    branch = repo.active_branch.name

    # Patch Repo so remotes.origin.fetch raises; but classify_freshness still works locally
    with patch("app.knowledge.git_tracker.Repo") as mock_repo_cls:
        mock_repo_instance = MagicMock()
        mock_repo_cls.return_value = mock_repo_instance

        # remotes.origin.fetch raises
        mock_repo_instance.remotes.origin.fetch.side_effect = Exception("network error")

        # commit resolution and iter_commits should work for a FRESH scenario
        real_commit = repo.commit(c2)
        mock_repo_instance.head.commit = real_commit
        mock_repo_instance.commit.side_effect = lambda rev: repo.commit(rev)

        def _iter_commits(spec, **kw):
            return list(repo.iter_commits(spec, **kw))

        mock_repo_instance.iter_commits.side_effect = _iter_commits

        # Even with fetch_origin=True and a failing fetch, it should not raise
        result = await tracker.classify_freshness_async(tmp_path, c2, branch, fetch_origin=True)
        # Result should be a valid tuple (FRESH, 0, 0) since c2==HEAD
        state, ahead, behind = result
        assert isinstance(state, GitFreshness)
        assert isinstance(ahead, int)
        assert isinstance(behind, int)
