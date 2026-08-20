"""F-GIT-01 — a revision that starts with a dash is an option, and git obeys it.

`GitInspector.diff()` and `.show()` passed caller-supplied revisions as **leading argv**
to the git binary with no validation and no `--` separator, so `--output=<path>` is not a
revision at all: it is git's diff-output option, and git writes there. Measured against a
scratch repository before the fix:

    before: 'IMPORTANT ORIGINAL CONTENT\\n'
    after : 'diff --git a/f.txt b/f.txt\\nindex f719efd..6e5aa7c 100644\\n...'
    show also writes: 216 bytes

Any file the process can write, truncated and replaced. On a dyno that includes the
application's own source, which makes it remote code execution at the next boot.

**It is reachable from chat.** `git_agent.py:373/375/382/408` take `args["sha"]`,
`args["a_sha"]`, `args["b_sha"]` and `args["commit_sha"]` straight out of the model's tool
call, and the model is driven by a user's message — and by repository content, which is
attacker-authorable in its own right (see the untrusted-data prompt work).

The path arguments were already guarded by `_safe_relpath`; the revisions were not. That
asymmetry is the whole finding: a path *looks* dangerous, and a revision looks like an
opaque identifier until you notice that git parses it as argv.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.knowledge.git_inspector import GitInspector, UnsafeRevError


def _git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(directory),
        },
    ).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    directory = tmp_path / "repo"
    directory.mkdir()
    _git(directory, "init", "-q", ".")
    (directory / "f.txt").write_text("one\n")
    _git(directory, "add", "-A")
    _git(directory, "commit", "-qm", "one")
    (directory / "f.txt").write_text("two\n")
    _git(directory, "commit", "-qam", "two")
    (directory / "f.txt").write_text("dirty\n")  # so a diff has content to write out
    return directory


@pytest.fixture
def victim(tmp_path) -> Path:
    path = tmp_path / "victim.txt"
    path.write_text("IMPORTANT ORIGINAL CONTENT\n")
    return path


@pytest.fixture
def target(tmp_path) -> Path:
    """A path inside the test's own sandbox for the hostile values to aim at.

    They were written as a literal `/tmp/x` first, and a plant run — which removes the
    guard on purpose — **created it**: 216 bytes, at 14:30, outside any sandbox. A test
    that carries a proof-of-concept executes that proof-of-concept the moment the guard
    it checks is gone, which is exactly when someone is deliberately removing it.
    """
    return tmp_path / "should-not-exist.txt"


class TestTheProofOfConcept:
    """The two calls that were measured writing to disk."""

    async def test_diff_cannot_write_to_an_arbitrary_file(self, repo, victim):
        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).diff(f"--output={victim}", "HEAD")

        assert victim.read_text() == "IMPORTANT ORIGINAL CONTENT\n"

    async def test_diff_cannot_write_via_the_second_revision_either(self, repo, victim):
        """Both positions reach argv, so guarding only the first moves the hole."""
        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).diff("HEAD", f"--output={victim}")

        assert victim.read_text() == "IMPORTANT ORIGINAL CONTENT\n"

    async def test_show_cannot_write_to_an_arbitrary_file(self, repo, victim):
        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).show(f"--output={victim}")

        assert victim.read_text() == "IMPORTANT ORIGINAL CONTENT\n"

    async def test_a_file_that_did_not_exist_is_not_created(self, repo, tmp_path):
        """Creation matters as much as truncation: dropping a file into a watched
        directory is its own primitive."""
        target = tmp_path / "planted.txt"

        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).diff(f"--output={target}", "HEAD")

        assert not target.exists()


class TestEveryRevEntryPointIsGuarded:
    """One validator, applied everywhere a revision arrives — a guard on the two methods
    the proof-of-concept happened to use would leave the same class open next door."""

    @pytest.mark.parametrize("shape", ["--output={t}", "-o{t}", "--upload-pack=sh"])
    async def test_show(self, repo, target, shape):
        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).show(shape.format(t=target))

        assert not target.exists()

    @pytest.mark.parametrize("shape", ["--output={t}", "-o{t}"])
    async def test_blame(self, repo, target, shape):
        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).blame("f.txt", shape.format(t=target))

        assert not target.exists()

    @pytest.mark.parametrize("shape", ["--output={t}", "-o{t}"])
    async def test_log_rev(self, repo, target, shape):
        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).log(rev=shape.format(t=target))

        assert not target.exists()

    @pytest.mark.parametrize("shape", ["--output={t}", "-o{t}"])
    async def test_review_signals(self, repo, target, shape):
        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).review_signals(shape.format(t=target))

        assert not target.exists()

    async def test_a_rev_of_only_whitespace_is_refused(self, repo):
        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).show("   ")

    async def test_an_absurdly_long_rev_is_refused(self, repo):
        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).show("a" * 5000)


class TestLegitimateRevisionsStillWork:
    """A guard that breaks real usage gets removed, so the allowed set has to be the real
    one — git's revision syntax, not a hex-sha regex."""

    async def test_head(self, repo):
        assert await GitInspector(str(repo)).show("HEAD")

    async def test_relative_syntax(self, repo):
        assert await GitInspector(str(repo)).show("HEAD~1")
        assert await GitInspector(str(repo)).show("HEAD^")

    async def test_a_branch_with_slashes_and_dashes(self, repo):
        _git(repo, "branch", "feat/some-thing")

        assert await GitInspector(str(repo)).log(rev="feat/some-thing") != []

    async def test_a_two_dot_range_in_diff(self, repo):
        out = await GitInspector(str(repo)).diff("HEAD~1", "HEAD")

        assert "f.txt" in out

    async def test_a_full_sha(self, repo):
        sha = _git(repo, "rev-parse", "HEAD").strip()

        assert await GitInspector(str(repo)).show(sha)

    async def test_a_tag(self, repo):
        _git(repo, "tag", "v1.0.0")

        assert await GitInspector(str(repo)).show("v1.0.0")


class TestTheSameGapNextDoor:
    """`UpdateRepoRequest.branch` had no validator while `AddRepoRequest.branch` did.

    The branch reaches `repo.git.checkout(branch)` and `Repo.clone_from(branch=…)` as
    argv, so an unvalidated one is this same finding wearing a different field name. It
    is also the same *shape* of gap as the connection routes — guarded on create, free
    on PATCH — which is worth naming: a create-side validator reads as "this field is
    handled", and nothing points at the sibling model that copies the field and not the
    rule.
    """

    def test_the_update_model_rejects_an_option_shaped_branch(self):
        import pydantic

        from app.api.routes.repos import UpdateRepoRequest

        with pytest.raises(pydantic.ValidationError):
            UpdateRepoRequest(branch="--upload-pack=sh")

    def test_the_update_model_still_accepts_a_real_branch(self):
        from app.api.routes.repos import UpdateRepoRequest

        assert UpdateRepoRequest(branch="feat/some-thing").branch == "feat/some-thing"

    def test_omitting_the_branch_is_still_allowed(self):
        from app.api.routes.repos import UpdateRepoRequest

        assert UpdateRepoRequest(name="renamed").branch is None


class TestTheCharsetRuleEarnsItsPlace:
    """Measured: deleting the allow-list left all 24 other tests green.

    Every hostile value they carried started with a dash, so the leading-dash rule alone
    satisfied them and the second rule was decoration — the same finding as the two route
    guards exercised from one starting state, one file later. These are the values only
    the charset refuses: no leading dash, so rule one waves them through.
    """

    @pytest.mark.parametrize(
        "shape",
        [
            "HEAD -o {t}",  # a space: one string now, two arguments to anything that splits
            "HEAD\n--output={t}",  # a newline, which line-oriented consumers do split on
            "HEAD;rm -rf {t}",  # a metacharacter, harmless to argv and not to a future shell
            "HEAD$(whoami)",
            "HEAD`id`",
            "HEAD|tee {t}",
            "HEAD>{t}",
            "HEAD'--output={t}'",
        ],
    )
    async def test_a_rev_with_whitespace_or_metacharacters_is_refused(self, repo, target, shape):
        with pytest.raises(UnsafeRevError):
            await GitInspector(str(repo)).show(shape.format(t=target))

        assert not target.exists()
