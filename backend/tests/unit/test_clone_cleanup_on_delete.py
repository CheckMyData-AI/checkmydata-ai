"""F-KNOW-08 — deleting a project left its entire source tree on disk.

`cleanup_project_artifacts` removed the BM25 snapshot and the Chroma collection and not
the git clone at `{repo_clone_base_dir}/{project_id}`. On Heroku the filesystem is
ephemeral, so it self-cleans at the next restart and the leak is invisible; on a
self-hosted deployment with a persistent volume, every deleted project keeps its whole
repository forever.

That is a retention question before it is a housekeeping one. Somebody who deletes a
project has asked for their code to stop being here.

**The dangerous part is the fix, not the bug.** This adds an `rmtree` on a path built from
an identifier, and an identifier that is empty or contains `..` turns that into
`rmtree("./data/repos")` — every project's clone, from a cleanup routine whose whole
contract is to never raise. Most of the tests below are about that, not about the deletion
working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.services import indexing_artifacts


@pytest.fixture
def repos(tmp_path, monkeypatch) -> Path:
    base = tmp_path / "repos"
    base.mkdir()
    monkeypatch.setattr(settings, "repo_clone_base_dir", str(base))
    # Two clones, so "it deleted something" and "it deleted the right thing" are
    # different assertions.
    for pid in ("proj-a", "proj-b"):
        (base / pid / ".git").mkdir(parents=True)
        (base / pid / "main.py").write_text("print('hi')\n")
    return base


@pytest.fixture(autouse=True)
def _no_other_artifacts(monkeypatch):
    """BM25 and Chroma are somebody else's tests; stub them so a failure here is about
    the clone."""
    monkeypatch.setattr(
        indexing_artifacts,
        "BM25Index",
        lambda *a, **k: type("_B", (), {"delete": lambda self, pid: None})(),
    )


class TestTheCloneIsRemoved:
    def test_the_project_s_clone_goes(self, repos):
        indexing_artifacts.cleanup_project_artifacts("proj-a")

        assert not (repos / "proj-a").exists()

    def test_another_project_s_clone_stays(self, repos):
        indexing_artifacts.cleanup_project_artifacts("proj-a")

        assert (repos / "proj-b" / "main.py").read_text() == "print('hi')\n"

    def test_a_missing_clone_is_not_an_error(self, repos):
        indexing_artifacts.cleanup_project_artifacts("never-cloned")

        assert repos.exists()


class TestItCannotDeleteTheWrongThing:
    """Each of these, before the containment check, is `rmtree` on a directory holding
    every project's source."""

    @pytest.mark.parametrize("pid", ["", "   ", ".", "..", "../..", "/", "//"])
    def test_a_degenerate_id_deletes_nothing(self, repos, pid):
        indexing_artifacts.cleanup_project_artifacts(pid)

        assert repos.exists()
        assert (repos / "proj-a" / "main.py").exists()
        assert (repos / "proj-b" / "main.py").exists()

    def test_a_traversal_id_cannot_escape_the_base_dir(self, repos, tmp_path):
        outside = tmp_path / "not-repos"
        outside.mkdir()
        (outside / "important.txt").write_text("keep me")

        indexing_artifacts.cleanup_project_artifacts("../not-repos")

        assert (outside / "important.txt").read_text() == "keep me"

    def test_the_base_directory_itself_is_never_the_target(self, repos):
        """`Path(base) / ""` is `base`. An empty id is the shape that turns a per-project
        cleanup into a wipe of all of them."""
        indexing_artifacts.cleanup_project_artifacts("")

        assert sorted(p.name for p in repos.iterdir()) == ["proj-a", "proj-b"]

    def test_a_symlink_pointing_out_is_not_followed(self, repos, tmp_path):
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "important.txt").write_text("keep me")
        (repos / "sneaky").symlink_to(outside, target_is_directory=True)

        indexing_artifacts.cleanup_project_artifacts("sneaky")

        assert (outside / "important.txt").read_text() == "keep me"

    def test_a_symlink_pointing_at_another_project_is_not_followed(self, repos):
        """The case containment cannot catch, and the reason the `is_symlink()` guard is
        not decoration.

        Measured: removing that guard left every other test green, because a symlink out
        of the tree resolves to a parent that is not the base directory and containment
        rejects it. A symlink pointing *inside* the tree resolves to a parent that IS the
        base directory — so containment passes, and `rmtree` follows the link and deletes
        another project's real source.
        """
        (repos / "shortcut").symlink_to(repos / "proj-b", target_is_directory=True)

        indexing_artifacts.cleanup_project_artifacts("shortcut")

        assert (repos / "proj-b" / "main.py").read_text() == "print('hi')\n"


class TestItStillNeverRaises:
    """The module's contract: cleanup runs inside the transaction boundary that ships the
    user-visible delete, so a leaked directory is preferable to a 500."""

    def test_an_rmtree_failure_is_swallowed(self, repos, monkeypatch):
        def _boom(*_a, **_k):
            raise OSError("read-only file system")

        monkeypatch.setattr(indexing_artifacts.shutil, "rmtree", _boom)

        indexing_artifacts.cleanup_project_artifacts("proj-a")  # must not raise

    def test_a_failure_is_logged_loudly_enough_to_find(self, repos, monkeypatch, caplog):
        """A leaked repository is a retention problem somebody may have to answer for, so
        this one does not go to `debug` with the rest."""
        import logging

        def _boom(*_a, **_k):
            raise OSError("read-only file system")

        monkeypatch.setattr(indexing_artifacts.shutil, "rmtree", _boom)

        with caplog.at_level(logging.DEBUG):
            indexing_artifacts.cleanup_project_artifacts("proj-a")

        # About the clone specifically. The first version asserted only that *some*
        # record at WARNING or above existed, and it passed with the log line demoted to
        # `debug` — satisfied by an unrelated warning from another cleanup step in the
        # same call. An assertion a neighbouring log line can satisfy is not an assertion.
        loud = [
            r.getMessage()
            for r in caplog.records
            if r.levelno >= logging.WARNING and "clone" in r.getMessage()
        ]
        assert loud, "a leaked repository must not be reported at debug"
        assert "proj-a" in loud[0]
