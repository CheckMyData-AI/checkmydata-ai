"""F-GIT-05: `list_releases` resolved every tag, sorted them all, then kept N.

The loop called `tag.commit` for each tag in the repository — an object lookup per
tag — built a dict for each, sorted the whole list, and only then sliced to
`max_count`. On a repository that tags every CI build, returning 100 releases meant
thousands of object resolutions and a full sort, on the answer path.

The ordering and the limit are things git does natively, so it does them: one
`for-each-ref --sort=-creatordate --count=N` picks the tags, and the existing
per-tag extraction — which is what the other tests cover — runs over N of them
instead of all of them.

**Ordering note, stated rather than smuggled:** the sort key is now git's
`creatordate`. For a lightweight tag that is the commit date, identical to before.
For an annotated tag it is when the tag was made, which is when the release was cut —
previously such a tag sorted by the date of the commit it points at, so an annotated
tag cut later from an older commit used to sort as if it were old.
"""

from pathlib import Path

import pytest
from git import Repo


def _commit(repo: Repo, path: Path, text: str, msg: str, when: str | None = None) -> str:
    """Commit, optionally at an explicit date.

    Distinct dates are not decoration: git and the old Python sort both order tags at
    second resolution, so twelve commits made in the same second have no defined
    "newest" and any ordering assertion over them tests the tie-break, not the sort.
    """
    path.write_text(text)
    repo.index.add([str(path)])
    kw = {"commit_date": when, "author_date": when} if when else {}
    return repo.index.commit(msg, **kw).hexsha


@pytest.fixture
def tagged_repo(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = Repo.init(str(repo_dir))
    with repo.config_writer() as cw:
        cw.set_value("user", "email", "dev@example.com")
        cw.set_value("user", "name", "Dev")
    f = repo_dir / "a.txt"
    for i in range(12):
        # One minute apart, oldest first, so "newest" is unambiguous.
        _commit(repo, f, f"v{i}\n", f"commit {i}", when=f"2026-01-01 00:{i:02d}:00 +0000")
        repo.create_tag(f"v0.{i}.0", message=f"release 0.{i}.0")
    # A tag outside the prefix, to prove filtering still happens.
    repo.create_tag("nightly-1")
    return repo_dir, repo


class TestReleaseScanIsBounded:
    @pytest.mark.asyncio
    async def test_only_the_requested_count_comes_back(self, tagged_repo):
        from app.knowledge.git_inspector import GitInspector

        repo_dir, _ = tagged_repo
        rels = await GitInspector(repo_dir).list_releases(max_count=3)
        assert len(rels) == 3

    @pytest.mark.asyncio
    async def test_the_newest_tags_are_the_ones_returned(self, tagged_repo):
        from app.knowledge.git_inspector import GitInspector

        repo_dir, _ = tagged_repo
        rels = await GitInspector(repo_dir).list_releases(tag_prefix="v0.", max_count=3)
        assert [r["tag_name"] for r in rels] == ["v0.11.0", "v0.10.0", "v0.9.0"]

    @pytest.mark.asyncio
    async def test_the_prefix_filter_still_applies(self, tagged_repo):
        from app.knowledge.git_inspector import GitInspector

        repo_dir, _ = tagged_repo
        rels = await GitInspector(repo_dir).list_releases(tag_prefix="nightly")
        assert [r["tag_name"] for r in rels] == ["nightly-1"]

    @pytest.mark.asyncio
    async def test_the_shape_of_each_release_is_unchanged(self, tagged_repo):
        from app.knowledge.git_inspector import GitInspector

        repo_dir, _ = tagged_repo
        rel = (await GitInspector(repo_dir).list_releases(max_count=1))[0]
        assert set(rel) == {"tag_name", "commit_sha", "short_sha", "commit_date", "message"}
        assert rel["short_sha"] == rel["commit_sha"][:10]
        assert rel["message"], "an annotated tag's own message is preferred"

    @pytest.mark.asyncio
    async def test_no_tag_resolution_happens_beyond_the_requested_count(self, tagged_repo):
        """The whole point: work proportional to what was asked for, not to the repo.

        Counting object resolutions is what distinguishes the fix from the shape it
        replaced — every other assertion here passed before it too.
        """
        from app.knowledge import git_inspector as mod

        repo_dir, _ = tagged_repo
        resolved: list[str] = []
        # `_ts_to_iso` is a staticmethod taking one argument — the spy has to match, or
        # every call raises TypeError and the test fails for a reason of its own making.
        real_ts = mod.GitInspector._ts_to_iso

        def _spy(ts):  # noqa: ANN001
            resolved.append(str(ts))
            return real_ts(ts)

        mod.GitInspector._ts_to_iso = staticmethod(_spy)  # type: ignore[method-assign]
        try:
            await mod.GitInspector(repo_dir).list_releases(tag_prefix="v0.", max_count=2)
        finally:
            mod.GitInspector._ts_to_iso = staticmethod(real_ts)  # type: ignore[method-assign]

        assert len(resolved) == 2, (
            f"resolved {len(resolved)} tags to return 2 — the scan is still proportional "
            "to the repository, not to the request"
        )

    @pytest.mark.asyncio
    async def test_a_repo_with_no_tags_returns_empty(self, tmp_path):
        from app.knowledge.git_inspector import GitInspector

        d = tmp_path / "bare"
        d.mkdir()
        r = Repo.init(str(d))
        with r.config_writer() as cw:
            cw.set_value("user", "email", "d@e.io")
            cw.set_value("user", "name", "D")
        _commit(r, d / "x.txt", "x", "init")
        assert await GitInspector(d).list_releases() == []


class TestTransportGuardLivesInTheCallee:
    """F-GIT-02: auto-pull inherits the `repo_url` guard because it is in the callee.

    The risk (`e642c67`) is transport injection — `ext::`, `fd::`, `file://`, option
    injection — and `GitAgent._maybe_auto_pull` passes `project.repo_url` and
    `project.repo_branch` straight through without checking either. That is safe only
    because `RepoAnalyzer.clone_or_pull` validates them itself, so every caller
    inherits the protection instead of having to remember it.

    Hoisting the validation to the callers would leave this path unguarded and no other
    test would notice, which is exactly what happened to the freshness signal in
    F-GIT-04. So the location is asserted, not just the behaviour.
    """

    def test_clone_or_pull_validates_its_own_arguments(self):
        import ast
        import inspect

        from app.knowledge import repo_analyzer as mod

        tree = ast.parse(inspect.getsource(mod))
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == "clone_or_pull"
        )
        called = {
            n.func.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "validate_repo_url" in called, (
            "clone_or_pull must validate the URL itself — GitAgent's auto-pull passes an "
            "unchecked repo_url and relies on this"
        )
        assert "validate_git_ref" in called, (
            "clone_or_pull must validate the branch itself — auto-pull passes an "
            "unchecked project.repo_branch"
        )

    def test_the_protocol_allowlist_is_pinned_inside_clone_or_pull(self):
        import inspect

        from app.knowledge.repo_analyzer import RepoAnalyzer

        src = inspect.getsource(RepoAnalyzer.clone_or_pull)
        assert "GIT_ALLOW_PROTOCOL" in src, (
            "the transport allowlist must be pinned on the env this function builds, not "
            "left to whatever the caller happens to pass"
        )

    def test_auto_pull_still_passes_the_values_through_unchecked(self):
        """Not a complaint — the record of *why* the callee-side guard is load-bearing.

        If this ever stops being true the guard could move; while it holds, moving it
        breaks auto-pull silently.
        """
        import ast
        import inspect

        from app.agents import git_agent as mod

        tree = ast.parse(inspect.getsource(mod))
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_maybe_auto_pull"
        )
        called = {
            n.func.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "validate_repo_url" not in called
