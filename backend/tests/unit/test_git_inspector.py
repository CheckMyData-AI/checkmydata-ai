"""Unit tests for GitInspector — read-only Git access over a temp repo."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.knowledge.git_inspector import (
    GitInspector,
    GitInspectorError,
    InvalidRefError,
    PathOutsideRepoError,
    RepoNotClonedError,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")


def _commit(repo, path: Path, content: str, message: str):
    path.write_text(content)
    repo.index.add([str(path.relative_to(Path(repo.working_tree_dir)))])
    return repo.index.commit(message)


@pytest.fixture
def temp_repo(tmp_path: Path):
    """Build a small repo: 3 commits, a tag, a merge, and a binary file."""
    from git import Repo

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = Repo.init(str(repo_dir))
    with repo.config_writer() as cw:
        cw.set_value("user", "email", "dev@example.com")
        cw.set_value("user", "name", "Dev One")

    f = repo_dir / "app.py"
    c1 = _commit(repo, f, "print('v1')\n", "feat: initial\n\nReviewed-by: Reviewer A <a@x.com>")
    _commit(repo, f, "print('v2')\n", "fix: bump\n\nCo-authored-by: Dev Two <two@x.com>")

    # Tag a release on the current HEAD.
    repo.create_tag("v1.0.0", message="release 1.0.0")

    # Binary file.
    (repo_dir / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01")
    repo.index.add(["logo.png"])
    repo.index.commit("chore: add binary")

    # A feature branch + merge commit.
    main = repo.active_branch.name
    repo.git.checkout("-b", "feature")
    _commit(repo, repo_dir / "feature.py", "x = 1\n", "feat: feature work")
    repo.git.checkout(main)
    repo.git.merge("feature", "--no-ff", "-m", "Merge branch 'feature' into main")

    return repo_dir, c1


class TestLog:
    async def test_log_returns_commits_newest_first(self, temp_repo):
        repo_dir, _ = temp_repo
        commits = await GitInspector(repo_dir).log(max_count=10)
        assert len(commits) >= 4
        # newest first → merge commit on top
        assert commits[0]["is_merge"] is True
        assert all("sha" in c and "author_name" in c for c in commits)

    async def test_log_filter_by_path(self, temp_repo):
        repo_dir, _ = temp_repo
        commits = await GitInspector(repo_dir).log(paths=["feature.py"], max_count=10)
        assert len(commits) == 1
        assert "feature" in commits[0]["message"]

    async def test_log_clamps_max_count(self, temp_repo):
        repo_dir, _ = temp_repo
        # Negative is clamped up to the floor (1), not an error.
        commits = await GitInspector(repo_dir).log(max_count=-5)
        assert len(commits) == 1


class TestShow:
    async def test_show_file_content(self, temp_repo):
        repo_dir, _ = temp_repo
        out = await GitInspector(repo_dir).show("HEAD", path="app.py")
        assert "print('v2')" in out

    async def test_show_binary_notice(self, temp_repo):
        repo_dir, _ = temp_repo
        out = await GitInspector(repo_dir).show("HEAD", path="logo.png")
        assert "binary" in out.lower()

    async def test_show_bad_sha_raises(self, temp_repo):
        repo_dir, _ = temp_repo
        with pytest.raises(InvalidRefError):
            await GitInspector(repo_dir).show("deadbeef", path="app.py")

    async def test_truncation(self, temp_repo):
        repo_dir, _ = temp_repo
        out = await GitInspector(repo_dir, max_output_bytes=10).show("HEAD", path="app.py")
        assert "truncated" in out


class TestDiff:
    async def test_diff_between_commits(self, temp_repo):
        repo_dir, first = temp_repo
        out = await GitInspector(repo_dir).diff(first.hexsha, "HEAD", paths=["app.py"])
        assert "v1" in out and "v2" in out

    async def test_diff_bad_ref(self, temp_repo):
        repo_dir, _ = temp_repo
        with pytest.raises(InvalidRefError):
            await GitInspector(repo_dir).diff("nope123", "HEAD")


class TestBlame:
    async def test_blame_lines(self, temp_repo):
        repo_dir, _ = temp_repo
        lines = await GitInspector(repo_dir).blame("app.py")
        assert lines
        assert lines[0]["author_name"] == "Dev One"
        assert lines[0]["line_number"] == 1


class TestReleases:
    async def test_list_releases(self, temp_repo):
        repo_dir, _ = temp_repo
        rels = await GitInspector(repo_dir).list_releases()
        assert any(r["tag_name"] == "v1.0.0" for r in rels)

    async def test_list_releases_prefix_filter(self, temp_repo):
        repo_dir, _ = temp_repo
        rels = await GitInspector(repo_dir).list_releases(tag_prefix="v2")
        assert rels == []


class TestStats:
    async def test_authors_stats(self, temp_repo):
        repo_dir, _ = temp_repo
        stats = await GitInspector(repo_dir).authors_stats()
        names = {s["author_name"] for s in stats}
        assert "Dev One" in names

    async def test_file_churn(self, temp_repo):
        repo_dir, _ = temp_repo
        churn = await GitInspector(repo_dir).file_churn()
        files = {c["file_path"] for c in churn}
        assert "app.py" in files


class TestReviewSignals:
    async def test_review_signals_on_first_commit(self, temp_repo):
        repo_dir, first = temp_repo
        sig = await GitInspector(repo_dir).review_signals(first.hexsha)
        assert sig["reviewers"] == ["Reviewer A <a@x.com>"]
        assert sig["is_merge_commit"] is False

    async def test_review_signals_merge(self, temp_repo):
        repo_dir, _ = temp_repo
        head = (await GitInspector(repo_dir).log(max_count=1))[0]
        sig = await GitInspector(repo_dir).review_signals(head["sha"])
        assert sig["is_merge_commit"] is True
        assert sig["merge_source_branch"] == "feature"

    async def test_review_signals_bad_sha(self, temp_repo):
        repo_dir, _ = temp_repo
        with pytest.raises(InvalidRefError):
            await GitInspector(repo_dir).review_signals("zzz999")


class TestCommitsTouching:
    async def test_pickaxe(self, temp_repo):
        repo_dir, _ = temp_repo
        commits = await GitInspector(repo_dir).commits_touching("v2")
        assert any("bump" in c["message"] for c in commits)

    async def test_empty_pattern_raises(self, temp_repo):
        repo_dir, _ = temp_repo
        with pytest.raises(GitInspectorError):
            await GitInspector(repo_dir).commits_touching("   ")


class TestSecurityAndEdgeCases:
    async def test_path_traversal_blocked(self, temp_repo):
        repo_dir, _ = temp_repo
        with pytest.raises(PathOutsideRepoError):
            await GitInspector(repo_dir).show("HEAD", path="../../etc/passwd")

    async def test_missing_clone_raises(self, tmp_path):
        with pytest.raises(RepoNotClonedError):
            await GitInspector(tmp_path / "nope").log()

    async def test_empty_repo_log_returns_empty(self, tmp_path):
        from git import Repo

        empty = tmp_path / "empty"
        empty.mkdir()
        Repo.init(str(empty))
        commits = await GitInspector(empty).log()
        assert commits == []
